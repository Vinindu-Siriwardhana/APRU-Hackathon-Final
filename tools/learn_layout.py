"""Record the grid layout of a blank form render (run once per template).

    soffice --headless --convert-to pdf form.docx && pdftoppm -r 200 -png form.pdf blank
    python tools/learn_layout.py blank-1.png backend/app/config/palmera_shg_monthly_v3.layout.json
"""
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))
from app.imaging.grid import find_tables, learn_layout  # noqa: E402
from app.imaging.io import read_image  # noqa: E402

img = read_image(sys.argv[1])
quads = find_tables(img)
main = quads[0]
# header table: the biggest other table whose bottom edge is above the main table's top
header = next(q for q in quads[1:] if q[:, 1].max() <= main[:, 1].min() + 5)
out = {"page_px": list(img.shape[:2]),
       "main_table": {"quad_frac": (main / [img.shape[1], img.shape[0]]).round(5).tolist(),
                      **learn_layout(img, main)},
       "header_table": {"quad_frac": (header / [img.shape[1], img.shape[0]]).round(5).tolist(),
                        **learn_layout(img, header)}}
print(len(out["main_table"]["rows"]) - 1, "x", len(out["main_table"]["cols"]) - 1, "main;",
      len(out["header_table"]["rows"]) - 1, "x", len(out["header_table"]["cols"]) - 1, "header")
Path(sys.argv[2]).write_text(json.dumps(out, indent=1), encoding="utf-8")
