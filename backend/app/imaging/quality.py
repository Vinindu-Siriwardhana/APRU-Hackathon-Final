"""Image quality gate: decide at the moment of capture whether a photo is good enough,
and if not, tell the sender in plain words what to fix.

Checks run cheapest-first and stop at the first hard failure, so the member gets one
clear instruction rather than a list:
  too_small -> too_dark -> blurry -> not_found / cut_off -> steep_angle -> too_far -> glare -> shadow
Thresholds were set on synthetic photos (samples/synthetic) and must be re-tuned on
real photos from Palmera groups before the pilot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from .grid import find_tables
from .layout import Alignment, FormLocator

PAGE_W, PAGE_H = 700, 990

THRESHOLDS = {
    "min_side_px": 900,          # shorter side of the photo
    "min_brightness": 90,        # median grey level of the page
    "min_sharpness": 80,         # 99.5th percentile |Laplacian| at 1000 px width
    "min_row_px": 16,            # average table row height in the photo
    "max_glare": 0.04,           # share of the table where printed lines are washed out
    "min_light_ratio": 0.45,     # darkest / brightest part of the paper
    "max_outside": 0.01,         # share of the printed content area lying outside the photo
    # How far from straight-on the page is seen, in degrees, where the form's table is
    # (see view_angle). Phone straight above the page: about 0-3. A real camera tilt of
    # 15 / 30 / 40 degrees measures about 11 / 27 / 37. The synthetic "good" photos
    # measure at most 26 (random corner jitter: 32 in 1 of 1000), the steep-angle sample
    # 43: 35 leaves about 8 degrees on each side.
    "max_view_angle": 35.0,
}

# Plain-language retake requests. Sinhala and Tamil drafts must be checked by
# native speakers from Palmera's team before use.
MESSAGES = {
    "too_small": {
        "en": "The photo is too small to read. Please send the photo at full size (not a screenshot).",
        "si": "ඡායාරූපය කියවීමට තරම් විශාල නැත. කරුණාකර සම්පූර්ණ ප්‍රමාණයෙන් ඡායාරූපය එවන්න.",
        "ta": "புகைப்படம் படிக்க முடியாத அளவுக்கு சிறியது. தயவுசெய்து முழு அளவில் புகைப்படத்தை அனுப்புங்கள்.",
    },
    "too_dark": {
        "en": "The photo is too dark. Please take it again near a window or in daylight.",
        "si": "ඡායාරූපය ඉතා අඳුරුයි. කරුණාකර ජනේලයක් අසල හෝ දිවා ආලෝකයේ නැවත ගන්න.",
        "ta": "புகைப்படம் மிகவும் இருட்டாக உள்ளது. ஜன்னல் அருகில் அல்லது பகல் வெளிச்சத்தில் மீண்டும் எடுங்கள்.",
    },
    "blurry": {
        "en": "The photo is blurry. Please hold the phone still, tap the screen on the form to focus, and take it again.",
        "si": "ඡායාරූපය පැහැදිලි නැත. දුරකථනය නොසැලී තබාගෙන, පෝරමය මත තට්ටු කර, නැවත ගන්න.",
        "ta": "புகைப்படம் மங்கலாக உள்ளது. தொலைபேசியை அசையாமல் பிடித்து, படிவத்தின் மீது தட்டி, மீண்டும் எடுங்கள்.",
    },
    "not_found": {
        "en": "I couldn't find the report form in this photo. Please lay the page flat and take the photo from above, with the whole page showing.",
        "si": "මෙම ඡායාරූපයේ වාර්තා පෝරමය හමු නොවීය. පිටුව පැතලිව තබා, මුළු පිටුවම පෙනෙන සේ ඉහළ සිට ගන්න.",
        "ta": "இந்த புகைப்படத்தில் அறிக்கை படிவம் கிடைக்கவில்லை. பக்கத்தை தட்டையாக வைத்து, முழு பக்கமும் தெரியும்படி மேலிருந்து எடுங்கள்.",
    },
    "cut_off": {
        "en": "Part of the page is cut off. Please step back a little so all four corners of the page are in the photo.",
        "si": "පිටුවේ කොටසක් කැපී ඇත. පිටුවේ කොන් හතරම පෙනෙන සේ ටිකක් පසුපසට වී නැවත ගන්න.",
        "ta": "பக்கத்தின் ஒரு பகுதி வெட்டப்பட்டுள்ளது. நான்கு மூலைகளும் தெரியும்படி சற்று பின்னால் நின்று எடுங்கள்.",
    },
    "too_far": {
        "en": "The page is too far away to read the numbers. Please move closer so the page fills the screen.",
        "si": "ඉලක්කම් කියවීමට පිටුව ඉතා දුරින් ඇත. පිටුව තිරය පිරෙන සේ ළං වී ගන්න.",
        "ta": "எண்களைப் படிக்க பக்கம் மிகவும் தொலைவில் உள்ளது. பக்கம் திரையை நிரப்பும்படி அருகில் வந்து எடுங்கள்.",
    },
    "glare": {
        "en": "There is a bright reflection on the page. Please turn off the flash or tilt the page slightly away from the light.",
        "si": "පිටුව මත දීප්තිමත් පරාවර්තනයක් ඇත. ෆ්ලෑෂ් එක නිවා දමන්න හෝ පිටුව ආලෝකයෙන් මදක් ඈත් කරන්න.",
        "ta": "பக்கத்தில் பிரகாசமான ஒளி பிரதிபலிப்பு உள்ளது. ஃபிளாஷை அணைக்கவும் அல்லது பக்கத்தை வெளிச்சத்திலிருந்து சற்று சாய்க்கவும்.",
    },
    "steep_angle": {
        "en": "The photo is taken from an angle. Please hold the phone straight above the page, "
              "with the whole page showing, and take it again.",
        "si": "ඡායාරූපය ඇල කෝණයකින් ගෙන ඇත. කරුණාකර දුරකථනය පිටුවට කෙළින්ම ඉහළින් අල්ලාගෙන, "
              "මුළු පිටුවම පෙනෙන සේ නැවත ගන්න.",
        "ta": "புகைப்படம் சாய்வாக எடுக்கப்பட்டுள்ளது. தயவுசெய்து தொலைபேசியை பக்கத்திற்கு நேராக மேலே "
              "பிடித்து, முழு பக்கமும் தெரியும்படி மீண்டும் எடுங்கள்.",
    },
    "shadow": {
        "en": "A shadow is covering part of the page. Please move so your hand or phone doesn't block the light, and take it again.",
        "si": "පිටුවේ කොටසක් සෙවණැල්ලකින් වැසී ඇත. ඔබේ අත හෝ දුරකථනය ආලෝකය නොවසන සේ නැවත ගන්න.",
        "ta": "பக்கத்தின் ஒரு பகுதியை நிழல் மறைக்கிறது. உங்கள் கை அல்லது தொலைபேசி வெளிச்சத்தை மறைக்காதபடி மீண்டும் எடுங்கள்.",
    },
}


@dataclass
class QualityResult:
    ok: bool
    problem: Optional[str] = None
    page: Optional[int] = None
    alignment: Optional[Alignment] = None
    metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def message(self, lang: str = "en") -> Optional[str]:
        return MESSAGES[self.problem].get(lang, MESSAGES[self.problem]["en"]) if self.problem else None


# where the printing is, as page fractions (x0, y0, x1, y1): blank margins may be cut off
CONTENT = {1: (0.10, 0.06, 0.97, 0.89), 2: (0.10, 0.09, 0.98, 0.91)}


def _page_image(al: Alignment) -> tuple[np.ndarray, float]:
    """The page warped flat to a standard size, and the share of its printed area outside the photo."""
    S = np.float64([[PAGE_W, 0, 0], [0, PAGE_H, 0], [0, 0, 1]])
    M = S @ np.linalg.inv(al.H)
    page = cv2.warpPerspective(al.image, M, (PAGE_W, PAGE_H), borderValue=(0, 0, 0))
    inside = cv2.warpPerspective(np.full(al.image.shape[:2], 255, np.uint8), M, (PAGE_W, PAGE_H))
    x0, y0, x1, y1 = CONTENT[al.page]
    region = inside[int(y0 * PAGE_H):int(y1 * PAGE_H), int(x0 * PAGE_W):int(x1 * PAGE_W)]
    return page, float((region == 0).mean())


def _jacobian(H: np.ndarray, x: float, y: float) -> np.ndarray:
    """Local linear part of a homography at (x, y): how a tiny square there is stretched."""
    p = H @ np.array([x, y, 1.0])
    u, v = p[0] / p[2], p[1] / p[2]
    return np.array([[H[0, 0] - u * H[2, 0], H[0, 1] - u * H[2, 1]],
                     [H[1, 0] - v * H[2, 0], H[1, 1] - v * H[2, 1]]]) / p[2]


def anchor_centre(layout: dict, page: int) -> tuple[float, float]:
    """Centre of the table the alignment is anchored on, in blank-page fractions."""
    if page == 1:
        q = np.float64(layout["main_table"]["quad_frac"])
        return float(q[:, 0].mean()), float(q[:, 1].mean())
    x0, y0, x1, y1 = layout["page2"]["tables"][layout["page2"]["anchor"]]["bbox"]
    return (x0 + x1) / 2, (y0 + y1) / 2


def view_angle(al: Alignment, layout: dict) -> float:
    """How far from straight-on the page is seen, in degrees, at the centre of the table
    the alignment is anchored on (the weekly table on page 1, the overdue-members table
    on page 2).

    Paper seen at an angle t is squashed by cos(t) along the tilt, so a small square of
    the page shows up as a rectangle with short/long sides = cos(t). The alignment
    already maps the page onto the photo, and its local stretch gives that ratio.
    Turning the phone (rotation) or holding it nearer or farther (scale) doesn't change
    the ratio, so only a real slant counts."""
    A4 = np.diag([1.0, np.sqrt(2.0), 1.0])             # blank-page fractions -> A4 proportions
    H = al.H @ np.linalg.inv(A4)
    cx, cy = anchor_centre(layout, al.page)
    s = np.linalg.svd(_jacobian(H, cx, cy * np.sqrt(2.0)), compute_uv=False)
    return float(np.degrees(np.arccos(np.clip(s[1] / s[0], 0.0, 1.0))))


def runs_off_photo(img: np.ndarray, min_area: float = 0.15, margin: float = 0.005) -> bool:
    """A big ruled table that reaches the photo's edge: the page continues outside the
    photo. Used only when the form couldn't be aligned, to pick the right retake message."""
    h, w = img.shape[:2]
    for q in find_tables(img)[:3]:
        if cv2.contourArea(q) < min_area * h * w:
            continue
        gap = min(q[:, 0].min(), q[:, 1].min(), w - 1 - q[:, 0].max(), h - 1 - q[:, 1].max())
        if gap < margin * max(h, w):
            return True
    return False


def washed_out(flat: np.ndarray, block: int = 100) -> float:
    """Share of the table where the printed grid can't be seen (glare or burnt-out light).
    Every block this size spans at least one ruled line, so a flat block means lost print."""
    g = cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    flat_blocks = total = 0
    for y in range(0, h - block + 1, block // 2):
        for x in range(0, w - block + 1, block // 2):
            b = g[y:y + block, x:x + block]
            total += 1
            if int(np.percentile(b, 98)) - int(np.percentile(b, 2)) < 40:
                flat_blocks += 1
    return flat_blocks / max(1, total)


def check(img: np.ndarray, locator: FormLocator, th: dict = THRESHOLDS) -> QualityResult:
    m: dict = {}
    h, w = img.shape[:2]
    m["size"] = [w, h]
    if min(h, w) < th["min_side_px"]:
        return QualityResult(False, "too_small", metrics=m)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (1000, int(1000 * h / w)))
    cy, cx = small.shape[0] // 2, small.shape[1] // 2
    m["brightness"] = float(np.median(small[cy // 2:cy + cy // 2, cx // 2:cx + cx // 2]))
    if m["brightness"] < th["min_brightness"]:
        return QualityResult(False, "too_dark", metrics=m)
    m["sharpness"] = float(np.percentile(np.abs(cv2.Laplacian(small, cv2.CV_64F)), 99.5))
    if m["sharpness"] < th["min_sharpness"]:
        return QualityResult(False, "blurry", metrics=m)

    al = locator.align(img)
    if al is None:
        # a big ruled table reaching the photo's edge means the page runs off the photo.
        # (This replaced "dark pixels along the top/bottom edge", which fired for every
        # photo taken on a dark table and missed pages cut off on a light one.)
        return QualityResult(False, "cut_off" if runs_off_photo(img) else "not_found", metrics=m)
    m["grid_match"] = round(al.score, 3)

    page, outside = _page_image(al)
    m["outside"] = round(outside, 3)
    if outside > th["max_outside"]:
        return QualityResult(False, "cut_off", page=al.page, alignment=al, metrics=m)

    m["view_angle"] = round(view_angle(al, locator.L), 1)
    if m["view_angle"] > th.get("max_view_angle", THRESHOLDS["max_view_angle"]):
        return QualityResult(False, "steep_angle", page=al.page, alignment=al, metrics=m)

    if al.grid is not None:
        q = al.grid.quad
        height = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
        m["row_px"] = round(float(height / (len(al.grid.rows) - 1)), 1)
        if m["row_px"] < th["min_row_px"]:
            return QualityResult(False, "too_far", page=al.page, alignment=al, metrics=m)

    pg = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
    m["glare"] = round(washed_out(al.grid.flat), 3) if al.grid is not None else 0.0
    # paper brightness with print and ink removed (closing wipes dark marks smaller than the kernel)
    bg = cv2.GaussianBlur(cv2.morphologyEx(pg, cv2.MORPH_CLOSE, np.ones((71, 71), np.uint8)), (0, 0), 15)
    m["light_ratio"] = round(float(np.percentile(bg, 3) / max(1.0, np.percentile(bg, 97))), 3)

    res = QualityResult(True, page=al.page, alignment=al, metrics=m)
    if al.grid is not None and al.grid.snapped > 2:
        res.warnings.append(f"{al.grid.snapped} table lines hard to see")
    if m["glare"] > th["max_glare"]:
        res.ok, res.problem = False, "glare"
    elif m["light_ratio"] < th["min_light_ratio"]:
        res.ok, res.problem = False, "shadow"
    return res
