"""Find the form's tables in a phone photo and cut out each cell.

The paper form is a fixed template, and the Sinhala / Tamil / English versions share
the same grid, so the grid itself (not the printed words) is what we align to:

1. build a mask of ruled lines (adaptive threshold + long horizontal/vertical kernels;
   filled header rows only contribute their edges, so blue/grey shading doesn't matter)
2. the biggest grid-shaped blob is the main weekly table; fit its 4 corners
3. warp the table to a flat rectangle (undoes tilt and perspective)
4. find the row and column lines in the flat table; snap to the template's expected
   layout so a faint or missing line doesn't shift every row after it
5. every cell gets a crop (for the officer) and a box in original-photo coordinates
   (for the audit trail)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

FLAT_W, FLAT_H = 1400, 2000          # canonical size of a rectified table


@dataclass
class TableGrid:
    quad: np.ndarray                  # 4x2 corners in the original image (tl, tr, br, bl)
    H: np.ndarray                     # homography original -> flat
    flat: np.ndarray                  # rectified table image (BGR)
    rows: list[int]                   # y of each horizontal line in flat image
    cols: list[int]                   # x of each vertical line in flat image
    image_shape: tuple[int, int]
    snapped: int = 0                  # lines placed from the template instead of detected
    notes: list[str] = field(default_factory=list)

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.rows) - 1, len(self.cols) - 1

    def cell_flat(self, r: int, c: int, pad: int = 3) -> tuple[int, int, int, int]:
        return (self.cols[c] + pad, self.rows[r] + pad, self.cols[c + 1] - pad, self.rows[r + 1] - pad)

    def crop(self, r: int, c: int, margin: int = 6) -> np.ndarray:
        """Cell image plus a little context, so the officer sees what was written."""
        x0, y0, x1, y1 = self.cell_flat(r, c, pad=-margin)
        h, w = self.flat.shape[:2]
        return self.flat[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]

    def cell_box_original(self, r: int, c: int) -> tuple[float, float, float, float]:
        """Cell bounding box in the original photo, normalised 0..1."""
        x0, y0, x1, y1 = self.cell_flat(r, c, pad=0)
        pts = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]).reshape(-1, 1, 2)
        back = cv2.perspectiveTransform(pts, np.linalg.inv(self.H)).reshape(-1, 2)
        h, w = self.image_shape
        return (float(back[:, 0].min() / w), float(back[:, 1].min() / h),
                float(back[:, 0].max() / w), float(back[:, 1].max() / h))

    def ink(self, r: int, c: int) -> float:
        """Fraction of dark pixels in a cell — cheap 'is anything written here?' signal."""
        x0, y0, x1, y1 = self.cell_flat(r, c, pad=12)   # stay clear of borders and band edges
        cell = cv2.cvtColor(self.flat[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        if cell.size == 0:
            return 0.0
        th = cv2.adaptiveThreshold(cell, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))   # drop JPEG speckle
        return float(th.mean() / 255)


def line_mask(gray: np.ndarray, scale: int = 30) -> tuple[np.ndarray, np.ndarray]:
    th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 8)
    th = cv2.dilate(th, np.ones((3, 3), np.uint8))      # thin lines survive a little residual tilt
    h, w = gray.shape
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, w // scale), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, h // scale)))
    horiz = cv2.dilate(cv2.erode(th, hk), hk)
    vert = cv2.dilate(cv2.erode(th, vk), vk)
    return horiz, vert


def _order(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.float32([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]])


def skew_angle(gray: np.ndarray, vertical: bool = False) -> float:
    """Dominant angle (degrees) of near-horizontal ruled lines (or, with vertical=True, how
    far near-vertical lines lean from upright: positive = top leans right)."""
    edges = cv2.Canny(gray, 50, 150)
    h, w = gray.shape
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=150,
                            minLineLength=(h // 6 if vertical else w // 5), maxLineGap=8)
    if lines is None:
        return 0.0
    angs = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):   # OpenCV 4 and 5 shapes differ
        if vertical:
            a = np.degrees(np.arctan2(x2 - x1, y2 - y1))
            a = a - 180 if a > 90 else a + 180 if a < -90 else a
            if abs(a) < 20:
                angs.append(-a)
        else:
            a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if abs(a) < 35:
                angs.append(a)
    return float(np.median(angs)) if angs else 0.0


def _corners(hull: np.ndarray) -> np.ndarray:
    """Four corners of a (roughly rectangular) outline from its extreme points."""
    pts = hull.reshape(-1, 2).astype(np.float32)
    s, d = pts.sum(1), pts[:, 0] - pts[:, 1]
    return np.float32([pts[s.argmin()], pts[d.argmax()], pts[s.argmax()], pts[d.argmin()]])


def find_tables(img: np.ndarray, min_area_frac: float = 0.01) -> list[np.ndarray]:
    """Candidate table outlines (tl, tr, br, bl in original-image pixels), largest first.

    Dark header bands hide the vertical rules, so one printed table can show up as a stack
    of fragments. Besides each fragment we therefore also offer every vertical run of
    fragments that share left/right edges; the caller scores candidates against the
    template grid and keeps the best, so over-generating here is cheap and safe."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    H, W = gray.shape
    ang = skew_angle(gray)
    R = np.vstack([cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0), [0, 0, 1]])
    rot = cv2.warpAffine(gray, R[:2], (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # perspective leaves the vertical rules leaning after rotation: undo with a shear
    lean = np.tan(np.radians(skew_angle(rot, vertical=True)))
    S = np.float64([[1, lean, -lean * H / 2], [0, 1, 0], [0, 0, 1]])
    A = (S @ R)[:2]
    straight = cv2.warpAffine(gray, A, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    Rinv = cv2.invertAffineTransform(A)
    horiz, vert = line_mask(straight, scale=45)
    grid = cv2.dilate(cv2.bitwise_or(horiz, vert), np.ones((5, 5), np.uint8))
    # RETR_LIST, not EXTERNAL: the paper's own edge often forms a closed outline with the
    # tables nested inside it
    contours, _ = cv2.findContours(grid, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    pieces = []
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:40]:
        if cv2.contourArea(c) < 0.002 * H * W:
            break
        x, y, w, h = cv2.boundingRect(c)
        pieces.append((x, y, w, h, cv2.convexHull(c).reshape(-1, 2)))

    cands: list[np.ndarray] = [p[4] for p in pieces if p[2] * p[3] >= min_area_frac * H * W]
    tol = 0.02 * W
    pieces.sort(key=lambda p: p[1])
    for i, a in enumerate(pieces):
        pts = [a[4]]
        for b in pieces[i + 1:]:
            if abs(b[0] - a[0]) < tol and abs((b[0] + b[2]) - (a[0] + a[2])) < tol:
                pts.append(b[4])
                cands.append(np.vstack(pts))

    out: list[np.ndarray] = []
    for pts in sorted(cands, key=lambda p: cv2.contourArea(cv2.convexHull(p)), reverse=True):
        q = _corners(cv2.convexHull(pts.astype(np.float32)))
        q = cv2.transform(q.reshape(-1, 1, 2), Rinv).reshape(4, 2).astype(np.float32)
        if any(np.abs(q - o).max() < 0.015 * max(H, W) for o in out):
            continue                      # near-duplicate outline
        out.append(q)
    return out[:15]


def _peaks(profile: np.ndarray, min_frac: float, min_gap: int) -> list[int]:
    """Centres of runs where the profile is high; thick runs (filled bands) give both edges."""
    k = 9                                   # smooth: slightly slanted lines spread over a few rows
    profile = np.convolve(profile, np.ones(k) / k, mode="same")
    thr = profile.max() * min_frac
    on = profile > thr
    runs, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1)); start = None
    if start is not None:
        runs.append((start, len(on) - 1))
    lines: list[int] = []
    for a, b in runs:
        if b - a > 3 * min_gap:           # a filled band: its top and bottom edges are lines
            lines += [a, b]
        else:
            lines.append((a + b) // 2)
    merged: list[int] = []
    for y in lines:
        if merged and y - merged[-1] < min_gap:
            merged[-1] = (merged[-1] + y) // 2
        else:
            merged.append(y)
    return merged


def _snap(detected: list[int], expected: list[float], length: int, tol: float) -> tuple[list[int], int]:
    """Use the template's expected line positions, moved onto a detected line when one is close."""
    out, snapped = [], 0
    for e in expected:
        target = e * length
        near = [d for d in detected if abs(d - target) <= tol * length]
        if near:
            out.append(int(min(near, key=lambda d: abs(d - target))))
        else:
            out.append(int(round(target)))
            snapped += 1
    return out, snapped


def grid_score(detected: list[int], expected: list[float], length: int, tol: float = 0.01) -> float:
    """Share of the template's lines that have a detected line nearby (1.0 = perfect match)."""
    if not expected:
        return 0.0
    hit = sum(1 for e in expected if any(abs(d - e * length) <= tol * length for d in detected))
    return hit / len(expected)


def quick_lines(img: np.ndarray, quad: np.ndarray, width: int = 700) -> tuple[list[float], list[float]]:
    """Row/column line positions (0..1) of a candidate, at low resolution — for scoring.
    Keeps the candidate's own proportions so thin lines aren't stretched into bands."""
    qw = (np.linalg.norm(quad[1] - quad[0]) + np.linalg.norm(quad[2] - quad[3])) / 2
    qh = (np.linalg.norm(quad[3] - quad[0]) + np.linalg.norm(quad[2] - quad[1])) / 2
    w, h = width, int(np.clip(width * qh / max(qw, 1), 100, 1400))
    dst = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    flat = cv2.warpPerspective(img, cv2.getPerspectiveTransform(quad, dst), (w, h))
    gray = cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY) if flat.ndim == 3 else flat
    horiz, vert = line_mask(gray, scale=12)
    rows = _peaks(horiz.sum(1).astype(float), 0.3, 4)
    cols = _peaks(vert.sum(0).astype(float), 0.3, 4)
    return [y / h for y in rows], [x / w for x in cols]


def rectify_table(img: np.ndarray, quad: np.ndarray,
                  expected_rows: Optional[list[float]] = None,
                  expected_cols: Optional[list[float]] = None) -> TableGrid:
    dst = np.float32([[0, 0], [FLAT_W - 1, 0], [FLAT_W - 1, FLAT_H - 1], [0, FLAT_H - 1]])
    H = cv2.getPerspectiveTransform(quad, dst)
    flat = cv2.warpPerspective(img, H, (FLAT_W, FLAT_H), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)
    gray = cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY)
    horiz, vert = line_mask(gray, scale=12)
    rows = _peaks(horiz.sum(1).astype(float), 0.3, 8)
    cols = _peaks(vert.sum(0).astype(float), 0.3, 8)
    g = TableGrid(quad=quad, H=H, flat=flat, rows=rows, cols=cols, image_shape=img.shape[:2])
    if expected_rows is not None:
        g.rows, n1 = _snap(rows, expected_rows, FLAT_H, 0.008)
        g.cols, n2 = _snap(cols, expected_cols, FLAT_W, 0.012)
        g.snapped = n1 + n2
        if g.snapped:
            g.notes.append(f"{g.snapped} grid lines not found in the photo; placed from the template")
    return g


def _dedupe(lines: list[int], min_gap: int) -> list[int]:
    out: list[int] = []
    for v in lines:
        if out and v - out[-1] < min_gap:
            continue                      # keep the first of a close pair (border, not fill edge)
        out.append(v)
    return out


def learn_layout(img: np.ndarray, quad: np.ndarray, min_gap_frac: float = 0.015) -> dict:
    """Run once on a clean render of the blank form to record where a table's lines are."""
    g = rectify_table(img, quad)
    rows = _dedupe(g.rows, int(min_gap_frac * FLAT_H))
    cols = _dedupe(g.cols, int(min_gap_frac * FLAT_W))
    return {"rows": [round(y / FLAT_H, 5) for y in rows],
            "cols": [round(x / FLAT_W, 5) for x in cols]}
