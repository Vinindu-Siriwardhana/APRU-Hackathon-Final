"""Shared helpers for the pipeline/API tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from seed_demo_workbook import seed as _seed  # noqa: E402

from app import workbook as W  # noqa: E402


def seed(out: Path) -> Path:
    """The demo workbook. Seeding creates the demo groups' tabs, which write_month only
    does when asked (create_tab=True); this works whether or not seed() asks for it."""
    orig = W.GNWorkbook.write_month

    def write_month(self, *a, **kw):
        kw.setdefault("create_tab", True)
        return orig(self, *a, **kw)

    W.GNWorkbook.write_month = write_month
    try:
        return _seed(out)
    finally:
        W.GNWorkbook.write_month = orig
