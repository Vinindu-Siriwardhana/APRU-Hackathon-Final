"""Round 1, imaging + sample data: the quality gate answers every sample photo the way
samples/synthetic/manifest.json says, isn't so strict that an ordinary slightly tilted
phone photo fails, and the demo data chains together (seeded history -> October forms)."""
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import openpyxl
import pytest
from PIL import Image

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_synthetic_forms as gen  # noqa: E402
from seed_demo_workbook import GROUPS, cash_check, seed  # noqa: E402

from app.extraction import SimulatedReader
from app.imaging.io import read_image
from app.imaging.layout import FormLocator
from app.imaging.quality import MESSAGES, THRESHOLDS, check
from app.models import Severity
from app.pipeline import Pipeline, Status, Store
from app.schema import load_template

T = load_template()
LOC = FormLocator(T)
SYN = ROOT / "samples" / "synthetic"
MANIFEST = json.loads((SYN / "manifest.json").read_text(encoding="utf-8"))
REJECTS = {case: info for case, info in MANIFEST.items() if info.get("expect") == "reject"}
GOOD_PAGES = sorted([p for case, info in MANIFEST.items() if case not in REJECTS for p in info["pages"]]
                    + [p.name for p in SYN.glob("*_scan_p1.png")])
MAX_ANGLE = THRESHOLDS["max_view_angle"]


def truth(case):
    return json.loads((SYN / f"{case}.truth.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the quality gate
@pytest.mark.parametrize("case", sorted(REJECTS))
def test_every_bad_sample_is_rejected_with_the_right_problem(case):
    info = REJECTS[case]
    assert info.get("problem") in MESSAGES, f"{case}: manifest must name the expected problem"
    for page in info["pages"]:
        q = check(read_image(SYN / page), LOC)
        assert not q.ok and q.problem == info["problem"], (page, q.problem, q.metrics)
        for lang in ("en", "si", "ta"):
            assert q.message(lang) == MESSAGES[q.problem][lang]


@pytest.mark.parametrize("page", GOOD_PAGES)
def test_every_good_sample_page_is_accepted_with_margin(page):
    q = check(read_image(SYN / page), LOC)
    assert q.ok, (page, q.problem, q.metrics)
    assert q.page == (2 if page.endswith("_p2.jpg") else 1)
    # well clear of the steep-angle limit, so a re-render can't tip a good page over
    assert q.metrics["view_angle"] <= MAX_ANGLE - 5, q.metrics


def test_steep_angle_message_is_kind_and_says_what_to_do():
    m = MESSAGES["steep_angle"]
    assert m["en"].startswith("The photo is taken from an angle.") and "straight above the page" in m["en"]
    assert "කෙළින්ම ඉහළින්" in m["si"] and "நேராக மேலே" in m["ta"]


SCAN = SYN / "kalaimagal_2026-10_scan_p1.png"


def _photo(view, turn=0.0, seed=3):
    """The clean page photographed with a real camera tilt `view` (degrees: top edge away,
    right edge away), then the phone turned by `turn` degrees."""
    img = gen.to_photo(Image.open(SCAN), random.Random(seed), rot=0.0, view=view)
    if turn:
        h, w = img.shape[:2]
        R = cv2.getRotationMatrix2D((w / 2, h / 2), turn, 1.0)
        img = cv2.warpAffine(img, R, (w, h), borderMode=cv2.BORDER_REPLICATE)
    return img


@pytest.mark.parametrize("view,turn", [((0, 0), 5), ((0, 0), -5), ((10, 0), 5), ((15, 5), -5),
                                       ((20, 0), 3), ((-12, 8), -4), ((8, -10), 5)])
def test_ordinary_slightly_tilted_phone_photos_pass(view, turn):
    q = check(_photo(view, turn), LOC)
    assert q.ok, (view, turn, q.problem, q.metrics)
    assert q.metrics["view_angle"] < MAX_ANGLE - 10, q.metrics


def test_mild_random_perspective_like_the_generator_default_passes():
    """The generator's own 'good photo' distortion (random corner jitter, +-4 degree turn)."""
    page = Image.open(SCAN)
    for seed in range(4):
        q = check(gen.to_photo(page, random.Random(100 + seed)), LOC)
        assert q.ok, (seed, q.problem, q.metrics)


@pytest.mark.parametrize("view,turn", [((46, 0), 4), ((44, 0), -6)])
def test_steep_camera_angles_are_rejected_as_steep(view, turn):
    q = check(_photo(view, turn), LOC)
    assert not q.ok and q.problem == "steep_angle", q.metrics


def test_view_angle_ignores_turning_and_distance():
    a = check(_photo((0, 0), 0), LOC).metrics["view_angle"]
    b = check(_photo((0, 0), 5), LOC).metrics["view_angle"]
    assert a < 5 and b < 5


# ---------------------------------------------------------------- sample data
def test_demo_values_the_script_relies_on_are_unchanged():
    k = truth("kalaimagal_2026-10")
    assert k["weekly.savings.Total"] == 11400 and k["weekly.cash_in_hand.W4"] == 20160
    assert k["weekly.interest_repaid.Total"] == 1160 and k["weekly.interest_repaid.W3"] == 310
    assert k["weekly.savings.W2"] == 2800
    s = truth("sisila_2026-10")
    assert s["weekly.principal_repaid.W4"] == 1200 and s["header.shg_name"] == "Sisila"


def test_vasantham_is_its_own_group_not_a_copy_of_kalaimagal():
    k, v = truth("kalaimagal_2026-10"), truth("vasantham_2026-10")
    filled = [f for f in k if k[f] not in (None, True, False)]
    same = [f for f in filled if v.get(f) == k[f]]
    assert len(same) <= 4, same                       # month, "2%" and a couple of coincidences
    assert v["header.total_members"] == 19 and v["weekly.savings.Total"] == 12400
    assert v["page2.overdue_members.0.name"] != k["page2.overdue_members.0.name"]


def _prior_from_form(rec):
    """Last month's closing figures implied by the form's first week."""
    inc = sum(rec.get(f"weekly.{x}.W1") or 0 for x in ("savings", "principal_repaid", "interest_repaid", "other_income"))
    exp = sum(rec.get(f"weekly.{x}.W1") or 0 for x in ("loans_distributed", "savings_refunded", "other_expenses"))
    cash = rec["weekly.expected_balance.W1"] - inc + exp
    sav = rec["weekly.savings_to_date.W1"] - (rec.get("weekly.savings.W1") or 0)
    out = rec["weekly.loans_outstanding.W1"] - (rec.get("weekly.loans_distributed.W1") or 0) + \
        (rec.get("weekly.principal_repaid.W1") or 0)
    return cash, sav, out


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    return seed(tmp_path_factory.mktemp("seed") / "gn.xlsx")


@pytest.mark.parametrize("case", ["kalaimagal_2026-10", "sisila_2026-10", "vasantham_2026-10"])
def test_october_forms_follow_on_from_the_seeded_september(seeded, case):
    from app.workbook import GNWorkbook
    rec = truth(case)
    prior = GNWorkbook(seeded, T).prior_month(rec["header.shg_name"], "2026-10")
    assert prior.month == "2026-09"
    assert (prior.cash_in_hand, prior.savings_to_date, prior.loans_outstanding) == _prior_from_form(rec)


def test_seeded_workbook_balances_in_palmeras_formulas_and_opens_on_kalaimagal(seeded):
    rows = cash_check(seeded)
    assert len(rows) == 4 * len(GROUPS)
    assert all(book == app for _, _, book, app in rows), [r for r in rows if r[2] != r[3]]
    wb = openpyxl.load_workbook(seeded)
    assert wb.active.title == "Kalaimagal"
    assert [ws.title for ws in wb.worksheets if ws.sheet_view.tabSelected] == ["Kalaimagal"]


def test_clean_vasantham_report_has_no_blocking_checks(tmp_path):
    wb = seed(tmp_path / "gn.xlsx")
    p = Pipeline(Store(tmp_path / "data"), wb, SimulatedReader(T, truth("vasantham_2026-10")), T)
    p.receive_image("m-vas", read_image(SYN / "vasantham_2026-10_p1.jpg"), lang="ta")
    sub, reply = p.receive_image("m-vas", read_image(SYN / "vasantham_2026-10_p2.jpg"))
    errors = [i for i in sub.validation.issues if i.severity == Severity.error]
    assert not errors, [(i.rule, i.message) for i in errors]
    assert sub.status == Status.awaiting_member
    assert sub.prior.cash_in_hand == 9340 and "12,400" in reply


def test_sisila_unclear_cell_is_smudged_but_still_has_ink():
    """The demo flags Sisila's W4 principal as 'handwriting unclear': the photo must show
    why (faint, smeared) while the cell still visibly holds something."""
    al = LOC.align(read_image(SYN / "sisila_2026-10_p1.jpg"))
    ink = LOC.weekly_ink(al)
    assert ink["weekly.principal_repaid.W4"] > 0.02             # not read as blank
    def contrast(fid):
        g = cv2.cvtColor(LOC.crop(al, fid), cv2.COLOR_BGR2GRAY)
        h, w = g.shape
        g = g[h // 5: -h // 5, w // 8: -w // 8]                   # away from the ruled lines
        return float(np.percentile(g, 95) - np.percentile(g, 2))
    assert contrast("weekly.principal_repaid.W4") < 0.7 * contrast("weekly.principal_repaid.W1")
