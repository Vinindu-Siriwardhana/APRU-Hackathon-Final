"""Align a photo to the form template and locate every field on it.

Page 1: the main weekly table is the anchor. Its cells come from the rectified grid
(precise); header cells are mapped from the blank template through the same
page homography.
Page 2: the 'overdue members' table is the anchor; answer areas are mapped from the
blank template.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from ..schema import CONFIG_DIR, Template
from .grid import TableGrid, find_tables, grid_score, quick_lines, rectify_table


@lru_cache
def load_layout(template_id: str) -> dict:
    return json.loads((CONFIG_DIR / f"{template_id}.layout.json").read_text(encoding="utf-8"))


def _quad(b: list[float]) -> np.ndarray:
    x0, y0, x1, y1 = b
    return np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


@dataclass
class Alignment:
    page: int                           # 1 or 2
    H: np.ndarray                       # blank-page fractions (0..1) -> photo pixels
    image: np.ndarray
    grid: Optional[TableGrid] = None    # main table, page 1 only
    score: float = 0.0                  # how well the grid matched the template

    def page_box_to_photo(self, box: list[float]) -> tuple[float, float, float, float]:
        pts = cv2.perspectiveTransform(_quad(box).reshape(-1, 1, 2), self.H).reshape(-1, 2)
        h, w = self.image.shape[:2]
        x0, y0 = max(0.0, pts[:, 0].min() / w), max(0.0, pts[:, 1].min() / h)
        x1, y1 = min(1.0, pts[:, 0].max() / w), min(1.0, pts[:, 1].max() / h)
        return float(x0), float(y0), float(x1), float(y1)

    def crop_box(self, box: tuple[float, float, float, float], margin: float = 0.004) -> np.ndarray:
        h, w = self.image.shape[:2]
        x0, y0, x1, y1 = box
        return self.image[int(max(0, y0 - margin) * h):int(min(1, y1 + margin) * h),
                          int(max(0, x0 - margin) * w):int(min(1, x1 + margin) * w)]


class FormLocator:
    def __init__(self, template: Template):
        self.t = template
        self.L = load_layout(template.id)

    # --------------------------------------------------------------- aligning
    def align(self, img: np.ndarray) -> Optional[Alignment]:
        """Find page 1's main table (or page 2's anchor table). Candidates are judged by how
        well their inner grid matches the template, not by size — the paper's own edge is
        often the biggest rectangle in the photo."""
        quads = find_tables(img)
        if not quads:
            return None
        main = self.L["main_table"]
        exp_rows, exp_cols = main["rows"], main["cols"]
        best, best_score = None, 0.0
        for q in quads:
            rows, cols = quick_lines(img, q)
            score = min(grid_score(rows, exp_rows, 1, 0.012), grid_score(cols, exp_cols, 1, 0.015))
            if score > best_score:
                best, best_score = q, score
        if best is not None and best_score >= 0.7:
            g = rectify_table(img, best, exp_rows, exp_cols)
            g.notes.append(f"grid match {best_score:.0%}")
            H = cv2.getPerspectiveTransform(np.float32(main["quad_frac"]), best)
            return Alignment(page=1, H=H, image=img, grid=g, score=best_score)
        # page 2: anchor = the table with ~6 rows x 4 columns
        anchor = self.L["page2"]["tables"][self.L["page2"]["anchor"]]
        exp_r = [i / anchor["rows"] for i in range(anchor["rows"] + 1)]
        exp_c = None
        best, best_score = None, 0.0
        for q in quads:
            rows, cols = quick_lines(img, q)
            if len(cols) != anchor["cols"] + 1 or not anchor["rows"] <= len(rows) <= anchor["rows"] + 2:
                continue
            w = np.linalg.norm(q[1] - q[0]); h = np.linalg.norm(q[3] - q[0])
            bw, bh = anchor["bbox"][2] - anchor["bbox"][0], anchor["bbox"][3] - anchor["bbox"][1]
            if not 0.6 < (w / h) / (bw / (bh * 1.414)) < 1.6:   # page is A4 (1:1.414)
                continue
            score = grid_score(rows, exp_r, 1, 0.03)
            if score > best_score:
                best, best_score = q, score
        if best is None or best_score < 0.6:
            return None
        H = cv2.getPerspectiveTransform(_quad(anchor["bbox"]), best)
        return Alignment(page=2, H=H, image=img, score=best_score)

    # --------------------------------------------------------------- fields
    def field_box(self, al: Alignment, field_id: str) -> Optional[tuple[float, float, float, float]]:
        parts = field_id.split(".")
        if parts[0] == "weekly" and al.page == 1:
            r = self.t.weekly_row(parts[1]).row
            c = self.L["main_table"]["col_index"][parts[2]]
            return al.grid.cell_box_original(r, c)
        if parts[0] == "header" and al.page == 1:
            ht = self.L["header_table"]
            r, c = ht["cells"][parts[1]]
            q = np.float32(ht["quad_frac"])
            x0, y0 = q[:, 0].min(), q[:, 1].min()
            w, h = q[:, 0].max() - x0, q[:, 1].max() - y0
            box = [x0 + ht["cols"][c] * w, y0 + ht["rows"][r] * h,
                   x0 + ht["cols"][c + 1] * w, y0 + ht["rows"][r + 1] * h]
            return al.page_box_to_photo(box)
        if parts[0] == "page2" and al.page == 2:
            p2 = self.L["page2"]
            if parts[1] in p2["regions"]:
                return al.page_box_to_photo(p2["regions"][parts[1]])
            if parts[1] in p2["tables"]:
                tb = p2["tables"][parts[1]]
                x0, y0, x1, y1 = tb["bbox"]
                r = int(parts[2]) + tb["header_rows"]
                c = tb["columns"].index(parts[3])
                rh, cw = (y1 - y0) / tb["rows"], (x1 - x0) / tb["cols"]
                return al.page_box_to_photo([x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh])
        return None

    def crop(self, al: Alignment, field_id: str) -> Optional[np.ndarray]:
        parts = field_id.split(".")
        if parts[0] == "weekly" and al.page == 1:
            r = self.t.weekly_row(parts[1]).row
            c = self.L["main_table"]["col_index"][parts[2]]
            return al.grid.crop(r, c)
        box = self.field_box(al, field_id)
        return None if box is None else al.crop_box(box)

    def weekly_ink(self, al: Alignment) -> dict[str, float]:
        """Ink per weekly cell: lets us spot values the model missed or invented."""
        out = {}
        for row in self.t.weekly:
            for col in row.columns:
                out[row.field_id(col)] = al.grid.ink(row.row, self.L["main_table"]["col_index"][col])
        return out


def save_crop(img: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    from .io import write_image
    write_image(path, img, 88)
