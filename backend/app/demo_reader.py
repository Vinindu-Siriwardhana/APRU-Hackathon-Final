"""Offline demo: 'read' the synthetic sample photos from their ground truth.

With no ANTHROPIC_API_KEY the app can still show the whole flow, but only for the
sample photos in samples/synthetic/. A photo is recognised by the hash of its bytes.
Anything else (a real form, a blank page, a re-saved sample) is NOT read: the
submission fails with a clear message instead of being filled with another
group's numbers.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from .extraction import SimulatedReader
from .schema import Template

# Realistic reading mistakes, so the review flow has something to do.
DEMO_ERRORS = {
    # the second reading takes the 8 for a 3: the two readings disagree
    "kalaimagal_2026-10": {"weekly.savings.W2": {"pass": 1, "raw": "2300"},
                           # both readings agree on a wrong digit: only the ledger can catch it
                           "weekly.interest_repaid.W3": {"pass": "both", "raw": "810"}},
    # a smudged cell the model isn't sure about
    "sisila_2026-10": {"weekly.principal_repaid.W4": {"pass": "both", "raw": "1200", "legibility": "unclear"}},
}


class UnknownSamplePhoto(Exception):
    """Offline demo mode was given a photo that isn't one of the samples."""
    member_key = "demo_unknown_photo"          # which bot message the member gets


class SampleIndex:
    """Sample photo file name ↔ hash ↔ sample report ('case')."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.by_hash: dict[str, str] = {}
        self.case_of: dict[str, str] = {}
        manifest = self.folder / "manifest.json"
        cases = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        for case, info in cases.items():
            for page in info.get("pages", []):
                self.case_of[page] = case
        for p in sorted(self.folder.glob("*.jpg")):
            self.by_hash[hashlib.md5(p.read_bytes()).hexdigest()] = p.name

    def names(self) -> list[str]:
        return sorted(p.name for p in self.folder.glob("*.jpg"))

    def match(self, data: bytes) -> Optional[str]:
        """The sample file these exact bytes are, or None."""
        return self.by_hash.get(hashlib.md5(data).hexdigest())


class DemoReader:
    def __init__(self, t: Template, samples: SampleIndex, errors: Optional[dict[str, dict]] = None):
        self.t = t
        self.samples = samples
        self.errors = DEMO_ERRORS if errors is None else errors
        self.current: Optional[SimulatedReader] = None      # kept for callers of read()

    def truth(self, case: str) -> Optional[dict[str, Any]]:
        p = self.samples.folder / f"{case}.truth.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def for_submission(self, sub: Any) -> SimulatedReader:
        """A reader for one submission, chosen from where each of its pages came from.
        Stateless, so two reports being read at the same time can't mix."""
        cases = {self.samples.case_of.get(sub.page_sources.get(p) or "") for p in sub.pages}
        if not cases or None in cases:
            raise UnknownSamplePhoto("Offline demo mode only reads the sample photos, and this photo isn't one "
                                     "of them. Set ANTHROPIC_API_KEY to read real forms.")
        if len(cases) > 1:
            raise UnknownSamplePhoto(f"The pages come from different sample reports ({', '.join(sorted(cases))}).")
        case = cases.pop()
        truth = self.truth(case)
        if truth is None:
            raise UnknownSamplePhoto(f"The sample '{case}' has no ground truth to read from.")
        return SimulatedReader(self.t, truth, self.errors.get(case))

    def read(self, images, prompt, schema):
        if self.current is None:
            raise UnknownSamplePhoto("Offline demo mode only reads the sample photos. "
                                     "Set ANTHROPIC_API_KEY to read real forms.")
        return self.current.read(images, prompt, schema)
