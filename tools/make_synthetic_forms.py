"""Make realistic 'phone photos' of filled-in Palmera SHG forms for testing and demos.

Writes each value of a FormRecord into the blank form in a handwriting font, then
simulates a phone photo: paper on a table, tilt/perspective, uneven light, noise and
JPEG compression. Also produces deliberately bad photos for the quality gate.

    python tools/make_synthetic_forms.py            # -> samples/synthetic/
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.imaging.io import write_image  # noqa: E402
from app.imaging.layout import load_layout  # noqa: E402
from app.sample_data import make_month  # noqa: E402
from app.schema import load_template  # noqa: E402

FONTS = ROOT / "tools" / "fonts"
HAND = [FONTS / "Caveat-Regular.ttf", FONTS / "Kalam-Regular.ttf"]
SCRIPT_FONT = {"ta": FONTS / "NotoSansTamil-Regular.ttf", "si": FONTS / "NotoSansSinhala-Regular.ttf"}
INKS = [(20, 40, 140), (25, 25, 35), (30, 50, 110)]          # blue / black ballpoint (RGB)


def fmt_money(v, rng):
    v = int(v)
    return rng.choice([f"{v}", f"{v:,}", f"{v}/-"]) if v >= 1000 else str(v)


def fmt(v, ftype, rng):
    if v is None:
        return None
    if ftype == "yesno":
        return "Yes" if v else "No"
    if ftype == "money":
        return fmt_money(v, rng)
    if ftype == "month":
        y, m = v.split("-")
        return rng.choice([f"{m}/{y}", f"{int(m)}/{y[2:]}", ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                           "Aug", "Sep", "Oct", "Nov", "Dec"][int(m) - 1] + f" {y}"])
    return str(v)


def _script(ch: str) -> str:
    if "\u0B80" <= ch <= "\u0BFF":
        return "ta"
    if "\u0D80" <= ch <= "\u0DFF":
        return "si"
    return "latin"


def runs(text: str) -> list[tuple[str, str]]:
    """Split text into (script, chunk); spaces/punctuation stay with the current run."""
    out: list[tuple[str, str]] = []
    for ch in text:
        sc = _script(ch)
        if out and (sc == out[-1][0] or (sc == "latin" and not ch.isalnum() and out[-1][0] != "latin"
                                         and ch == " ")):
            out[-1] = (out[-1][0], out[-1][1] + ch)
        else:
            out.append((sc, ch))
    return out


def font_for(script: str, size: int, hand: Path) -> ImageFont.FreeTypeFont:
    if script in SCRIPT_FONT:
        return ImageFont.truetype(str(SCRIPT_FONT[script]), int(size * 0.72))
    return ImageFont.truetype(str(hand), size)


def text_width(text: str, size: int, hand: Path) -> float:
    return sum(font_for(sc, size, hand).getlength(chunk) for sc, chunk in runs(text))


def write_in_box(draw, box_px, text, rng, hand, ink, max_size=None, align="left"):
    x0, y0, x1, y1 = box_px
    h, w = y1 - y0, x1 - x0
    size = int(min(max_size or 1e9, h * rng.uniform(0.62, 0.8)))
    while text_width(text, size, hand) > w * 0.9 and size > 10:
        size -= 2
    tw = text_width(text, size, hand)
    x = x0 + (w - tw) / 2 + rng.uniform(-0.05, 0.05) * w if align == "center" else x0 + w * rng.uniform(0.03, 0.08)
    y = y0 + (h - size) / 2 + rng.uniform(-0.12, 0.08) * h - size * 0.12
    for sc, chunk in runs(text):
        f = font_for(sc, size, hand)
        dy = size * 0.18 if sc in SCRIPT_FONT else 0
        draw.text((x, y + dy), chunk, font=f, fill=ink)
        x += f.getlength(chunk)


def fill_page(page_img: Image.Image, page: int, rec, t, L, rng) -> Image.Image:
    img = page_img.convert("RGB").copy()
    W, H = img.size
    draw = ImageDraw.Draw(img)
    hand, ink = rng.choice(HAND), rng.choice(INKS)
    if page == 1:
        mt = L["main_table"]
        q = np.array(mt["quad_frac"]) * [W, H]
        x0, y0 = q[:, 0].min(), q[:, 1].min()
        tw, th = q[:, 0].max() - x0, q[:, 1].max() - y0
        for row in t.weekly:
            for col in row.columns:
                v = rec.get(row.field_id(col))
                s = fmt(v, row.type, rng)
                if s is None:
                    continue
                c = mt["col_index"][col]
                box = (x0 + mt["cols"][c] * tw, y0 + mt["rows"][row.row] * th,
                       x0 + mt["cols"][c + 1] * tw, y0 + mt["rows"][row.row + 1] * th)
                write_in_box(draw, box, s, rng, hand, ink, max_size=int(th * 0.03), align="center")
        ht = L["header_table"]
        q = np.array(ht["quad_frac"]) * [W, H]
        x0, y0 = q[:, 0].min(), q[:, 1].min()
        tw, th = q[:, 0].max() - x0, q[:, 1].max() - y0
        for f in t.header:
            s = fmt(rec.get(f"header.{f.key}"), f.type, rng)
            if s is None:
                continue
            r, c = ht["cells"][f.key]
            box = (x0 + ht["cols"][c] * tw, y0 + ht["rows"][r] * th,
                   x0 + ht["cols"][c + 1] * tw, y0 + ht["rows"][r + 1] * th)
            write_in_box(draw, box, s, rng, hand, ink, max_size=int(H * 0.018))
    else:
        p2 = L["page2"]
        for key, b in p2["regions"].items():
            s = rec.get(f"page2.{key}")
            if s is None:
                continue
            box = (b[0] * W, b[1] * H, b[2] * W, b[3] * H)
            write_in_box(draw, box, str(s), rng, hand, ink, max_size=int(H * 0.02))
        for key, tb in p2["tables"].items():
            x0, y0, x1, y1 = tb["bbox"]
            rh, cw = (y1 - y0) / tb["rows"], (x1 - x0) / tb["cols"]
            for i in range(tb["rows"] - tb["header_rows"]):
                for j, col in enumerate(tb["columns"]):
                    v = rec.get(f"page2.{key}.{i}.{col}")
                    if v is None:
                        continue
                    s = fmt_money(v, rng) if col == "amount_left" else str(v)
                    r = i + tb["header_rows"]
                    box = ((x0 + j * cw) * W, (y0 + r * rh) * H, (x0 + (j + 1) * cw) * W, (y0 + (r + 1) * rh) * H)
                    write_in_box(draw, box, s, rng, hand, ink, max_size=int(H * 0.018))
    return img


# --------------------------------------------------------------------- photo simulation
def camera_quad(pw: int, ph: int, cx: float, cy: float, tilt_x: float, tilt_y: float = 0.0,
                focal: float = 0.72) -> np.ndarray:
    """Where the page's corners land in a photo taken by a phone camera tilted away from
    straight-above: `tilt_x` degrees with the top edge of the page farther away, `tilt_y`
    with the right edge farther away. `focal` is the focal length as a share of the page's
    long side (about a phone's main camera with the page filling the frame). The page is
    scaled to fit the untilted page's size, centred on (cx, cy)."""
    f = focal * max(pw, ph)
    ax, ay = np.radians(tilt_x), np.radians(tilt_y)
    Rx = np.array([[1, 0, 0], [0, np.cos(ax), np.sin(ax)], [0, -np.sin(ax), np.cos(ax)]])   # top (y < 0) away
    Ry = np.array([[np.cos(ay), 0, -np.sin(ay)], [0, 1, 0], [np.sin(ay), 0, np.cos(ay)]])   # right (x > 0) away
    pts = []
    for x, y in [(-pw / 2, -ph / 2), (pw / 2, -ph / 2), (pw / 2, ph / 2), (-pw / 2, ph / 2)]:
        X, Y, Z = Ry @ (Rx @ np.array([x, y, 0.0]))
        pts.append([f * X / (f + Z), f * Y / (f + Z)])
    pts = np.float32(pts)
    pts *= min(pw / np.ptp(pts[:, 0]), ph / np.ptp(pts[:, 1]))
    return pts - pts.mean(0) + np.float32([cx, cy])


def to_photo(page: Image.Image, rng: random.Random, *, tilt=0.06, rot=4.0, blur=0.0, dark=1.0,
             shadow=False, glare=False, crop_bottom=0.0, out_w=1600, view=None) -> np.ndarray:
    """`view=(tilt_x, tilt_y)` places the page with a real camera tilt (see camera_quad)
    instead of the default small random corner jitter."""
    pg = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
    ph, pw = pg.shape[:2]
    # background: wooden table / cloth
    bw, bh = int(pw * 1.35), int(ph * 1.25)
    base = np.array(rng.choice([(70, 100, 140), (60, 70, 80), (120, 130, 150), (40, 60, 95)]), np.uint8)
    bg = np.full((bh, bw, 3), base, np.uint8)
    noise = cv2.GaussianBlur(np.random.default_rng(rng.randint(0, 10**6)).integers(0, 40, (bh, bw), dtype=np.uint8), (0, 0), 6)
    bg = cv2.add(bg, cv2.merge([noise] * 3))
    ox, oy = (bw - pw) // 2, (bh - ph) // 2
    src = np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]])
    j = lambda s: rng.uniform(-s, s)
    if view is not None:
        dst = camera_quad(pw, ph, bw / 2, bh / 2, *view)
    else:
        dst = np.float32([[ox + j(tilt) * pw, oy + j(tilt) * ph], [ox + pw + j(tilt) * pw, oy + j(tilt) * ph],
                          [ox + pw + j(tilt) * pw, oy + ph + j(tilt) * ph], [ox + j(tilt) * pw, oy + ph + j(tilt) * ph]])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(pg, M, (bw, bh), borderValue=(0, 0, 0))
    mask = cv2.warpPerspective(np.full((ph, pw), 255, np.uint8), M, (bw, bh))
    photo = np.where(mask[..., None] > 0, warped, bg)
    R = cv2.getRotationMatrix2D((bw / 2, bh / 2), j(rot), 1.0)
    photo = cv2.warpAffine(photo, R, (bw, bh), borderMode=cv2.BORDER_REFLECT)
    # uneven light: soft gradient + slight warm tint
    yy, xx = np.mgrid[0:bh, 0:bw].astype(np.float32)
    ang = rng.uniform(0, 2 * np.pi)
    grad = 0.82 + 0.25 * ((np.cos(ang) * xx / bw + np.sin(ang) * yy / bh) % 1.0)
    grad = cv2.GaussianBlur(grad, (0, 0), 80)
    photo = np.clip(photo.astype(np.float32) * grad[..., None] * dark * np.float32([0.97, 1.0, 1.04]), 0, 255)
    if shadow:
        poly = np.int32([[rng.uniform(0.3, 0.6) * bw, 0], [bw, 0], [bw, bh], [rng.uniform(0.5, 0.8) * bw, bh]])
        sm = np.zeros((bh, bw), np.float32)
        cv2.fillPoly(sm, [poly], 1.0)
        sm = cv2.GaussianBlur(sm, (0, 0), 25)
        photo *= (1 - 0.6 * sm)[..., None]
    if glare:
        gm = np.zeros((bh, bw), np.float32)
        cv2.ellipse(gm, (int(bw * 0.55), int(bh * 0.45)), (int(bw * 0.18), int(bh * 0.12)), 20, 0, 360, 1.0, -1)
        gm = cv2.GaussianBlur(gm, (0, 0), 30)
        photo = photo + 255 * 1.4 * gm[..., None]
    photo = np.clip(photo, 0, 255).astype(np.uint8)
    if blur:
        photo = cv2.GaussianBlur(photo, (0, 0), blur)
    if crop_bottom:
        photo = photo[: int(bh * (1 - crop_bottom))]
    photo = cv2.add(photo, np.random.default_rng(rng.randint(0, 10**6)).integers(0, 8, photo.shape, dtype=np.uint8))
    scale = out_w / photo.shape[1]
    photo = cv2.resize(photo, (out_w, int(photo.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    ok, enc = cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, rng.randint(72, 88)])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)


# The demo's "Handwriting marked unclear" cell (DEMO_ERRORS in app/demo_reader.py) is
# smudged on the photo, so the flag is visibly justified.
SMUDGED = {"sisila_2026-10": ["weekly.principal_repaid.W4"]}
STEEP_VIEW = (46, 0)


def weekly_cell_box(t, L, size, field_id: str) -> tuple[float, float, float, float]:
    """Pixel box of a weekly-table cell on the blank page 1 (same geometry as fill_page)."""
    W, H = size
    mt = L["main_table"]
    q = np.array(mt["quad_frac"]) * [W, H]
    x0, y0 = q[:, 0].min(), q[:, 1].min()
    tw, th = q[:, 0].max() - x0, q[:, 1].max() - y0
    _, key, col = field_id.split(".")
    r, c = t.weekly_row(key).row, mt["col_index"][col]
    return (x0 + mt["cols"][c] * tw, y0 + mt["rows"][r] * th, x0 + mt["cols"][c + 1] * tw, y0 + mt["rows"][r + 1] * th)


def smudge(page: Image.Image, box, rng: random.Random) -> None:
    """Rub the ink in one cell: faded, smeared sideways, with a grey thumb mark over it.
    Stays inside the cell so the ruled lines (what alignment relies on) are untouched."""
    x0, y0, x1, y1 = box
    px, py = (x1 - x0) * 0.06, (y1 - y0) * 0.14
    x0, y0, x1, y1 = int(x0 + px), int(y0 + py), int(x1 - px), int(y1 - py)
    a = np.array(page)
    cell = a[y0:y1, x0:x1].astype(np.float32)
    k = np.zeros((1, 15), np.float32); k[0, :] = 1 / 15                       # sideways smear
    smear = cv2.filter2D(cell, -1, k)
    out = 0.45 * cell + 0.55 * smear
    paper = np.percentile(cell.reshape(-1, 3), 90, axis=0).astype(np.float32)   # the cell's own paper colour
    out = paper + (out - paper) * 0.62                                        # ink faded
    h, w = out.shape[:2]
    mark = np.zeros((h, w), np.float32)
    cv2.ellipse(mark, (int(w * rng.uniform(0.4, 0.6)), int(h * 0.5)), (int(w * 0.38), int(h * 0.42)),
                rng.uniform(-15, 15), 0, 360, 1.0, -1)
    mark = cv2.GaussianBlur(mark, (0, 0), max(2.0, h * 0.18))
    out = out * (1 - 0.22 * mark[..., None]) + np.float32([120, 115, 110]) * 0.22 * mark[..., None]
    a[y0:y1, x0:x1] = np.clip(out, 0, 255).astype(np.uint8)
    page.paste(Image.fromarray(a))


def truth(rec) -> dict:
    return {k: v.value for k, v in rec.fields.items()}


def main(out_dir: Path = ROOT / "samples" / "synthetic") -> None:
    t = load_template()
    L = load_layout(t.id)
    blank1 = Image.open(ROOT / "samples" / "blank_page1.png")
    blank2 = Image.open(ROOT / "samples" / "blank_page2.png")
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)

    cases = {
        "kalaimagal_2026-10": make_month(t),
        "kalaimagal_2026-11": make_month(t, month="2026-11", prior_cash=make_month(t).get("weekly.cash_in_hand.W4"),
                                         prior_savings=95400, prior_outstanding=65300),
    }
    # Sinhala-speaking group, page-2 answers in Sinhala
    si = make_month(t, shg="Sisila", gn="Kotmale North", members=12, prior_cash=8000,
                    prior_savings=40000, prior_outstanding=22000,
                    weeks=[dict(held=True, att=11, sav=1200, prin=1500, intr=150, oth=0, dist=3000, ig=3000, em=0, ot=0, ref=0, wo=0, oexp=0, dep=0),
                           dict(held=True, att=12, sav=1200, prin=1000, intr=120, oth=100, dist=0, ig=0, em=0, ot=0, ref=0, wo=0, oexp=250, dep=0),
                           dict(held=False, att=0, sav=0, prin=0, intr=0, oth=0, dist=0, ig=0, em=0, ot=0, ref=0, wo=0, oexp=0, dep=0),
                           dict(held=True, att=10, sav=1100, prin=1200, intr=130, oth=0, dist=2000, ig=0, em=2000, ot=0, ref=0, wo=0, oexp=0, dep=5000)])
    si.set("page2.social_work", "ගම්මානයේ පාසල පිරිසිදු කළා")
    si.set("page2.group_goal", "මාසෙට රු. 5000ක් ඉතුරු කිරීම")
    si.set("page2.overdue_members.0.name", "W. Kumari")
    si.set("page2.overdue_members.1.name", "P. Nilmini")
    cases["sisila_2026-10"] = si
    # Tamil-speaking, younger and growing: 19 members (one joined this month, her
    # membership fee is W1's other income), savings up every month (12,400 in October,
    # above its Rs 12,000 goal). Follows on from its September in tools/seed_demo_workbook.py:
    # cash 9,340, savings to date 52,600, loans outstanding 42,000.
    ta = make_month(t, shg="Vasantham", gn="Mullaitivu Town", members=19, prior_cash=9340,
                    prior_savings=52600, prior_outstanding=42000, inactive=0, overdue=1,
                    weeks=[dict(held=True, att=18, sav=3100, prin=2100, intr=240, oth=200, dist=5000, ig=5000, em=0, ot=0, ref=0, wo=0, oexp=0, dep=0),
                           dict(held=True, att=17, sav=2900, prin=1800, intr=230, oth=0, dist=0, ig=0, em=0, ot=0, ref=0, wo=0, oexp=180, dep=0),
                           dict(held=True, att=19, sav=3300, prin=2400, intr=270, oth=0, dist=9000, ig=6000, em=3000, ot=0, ref=0, wo=0, oexp=0, dep=0),
                           dict(held=True, att=18, sav=3100, prin=2000, intr=250, oth=100, dist=4000, ig=0, em=0, ot=4000, ref=0, wo=0, oexp=120, dep=6000)],
                    header={"last_audit_date": "28/07/2026", "graded_last_3_months": "Yes 11/09/2026",
                            "constitution_updated": "03/2026"},
                    page2={"overdue_members.0.name": "R. Kalaivani", "overdue_members.0.amount_left": 3000,
                           "overdue_members.0.months_overdue": 1, "overdue_members.0.last_meeting_attended": "W4",
                           "overdue_members.1.name": None, "overdue_members.1.amount_left": None,
                           "overdue_members.1.months_overdue": None, "overdue_members.1.last_meeting_attended": None,
                           "social_work": "கிராம கிணற்றை சுத்தம் செய்தோம்",
                           "members_with_goals": 14,
                           "group_goal": "இந்த மாதம் ரூ. 12000 சேமிப்பு",
                           "govt_ngo_support": "பால்மேரா கணக்கு பயிற்சி 21/10",
                           "issues.0.issue": "புதிய உறுப்பினர்களுக்கு கடன் விதிகள் தெரியாது",
                           "issues.0.support_from_cluster": "கிளஸ்டர் கூட்டத்தில் விளக்க வேண்டும்"})
    cases["vasantham_2026-10"] = ta

    manifest = {}
    for name, rec in cases.items():
        p1 = fill_page(blank1, 1, rec, t, L, rng)
        p2 = fill_page(blank2, 2, rec, t, L, rng)
        for fid in SMUDGED.get(name, []):
            smudge(p1, weekly_cell_box(t, L, p1.size, fid), random.Random(f"{name}/{fid}"))
        p1.save(out_dir / f"{name}_scan_p1.png")
        write_image(out_dir / f"{name}_p1.jpg", to_photo(p1, rng))
        write_image(out_dir / f"{name}_p2.jpg", to_photo(p2, rng))
        (out_dir / f"{name}.truth.json").write_text(json.dumps(truth(rec), ensure_ascii=False, indent=1), encoding="utf-8")
        manifest[name] = {"pages": [f"{name}_p1.jpg", f"{name}_p2.jpg"], "truth": f"{name}.truth.json"}

    # Bad photos get their own random stream, so changing a group's numbers above
    # doesn't change them. `problem` is what the quality gate must answer.
    rng = random.Random(11)
    p1 = fill_page(blank1, 1, cases["kalaimagal_2026-10"], t, L, rng)
    bad = {"bad_blurry": ("blurry", dict(blur=5.0)), "bad_dark": ("too_dark", dict(dark=0.28)),
           "bad_shadow": ("shadow", dict(shadow=True)), "bad_cropped": ("cut_off", dict(crop_bottom=0.33)),
           "bad_glare": ("glare", dict(glare=True)),
           # a real camera tilt: the top of the page tipped about 46 degrees away
           "bad_steep_angle": ("steep_angle", dict(view=STEEP_VIEW, rot=6))}
    for name, (problem, kw) in bad.items():
        write_image(out_dir / f"{name}_p1.jpg", to_photo(p1, rng, **kw))
        manifest[name] = {"pages": [f"{name}_p1.jpg"], "expect": "reject", "problem": problem}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"wrote {len(manifest)} cases to {out_dir}")


if __name__ == "__main__":
    main()
