"""Load a form-template config and expose it as typed objects.

Field ids are flat strings so that every value — for validation messages, the
officer review queue, WhatsApp corrections and the audit trail — can be named
the same way everywhere:

    header.<key>                     header.shg_name
    weekly.<key>.<col>               weekly.savings.W3, weekly.savings.Total
    page2.<key>                      page2.group_goal
    page2.<table>.<i>.<col>          page2.overdue_members.0.amount_left
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).parent / "config"
WEEKS = ["W1", "W2", "W3", "W4", "W5"]


@dataclass(frozen=True)
class WeeklyRow:
    row: int
    key: str
    label: str
    type: str
    kind: str = "flow"          # flow | balance | derived | unclear
    weeks: bool = True          # W1..W5 cells are fillable
    total: bool = True          # Total cell is fillable

    @property
    def columns(self) -> list[str]:
        cols = list(WEEKS) if self.weeks else []
        if self.total:
            cols.append("Total")
        return cols

    def field_id(self, col: str) -> str:
        return f"weekly.{self.key}.{col}"


@dataclass(frozen=True)
class SimpleField:
    key: str
    label: str
    type: str
    required: bool = False
    min: float | None = None
    max: float | None = None
    columns: tuple = ()
    max_rows: int = 0


@dataclass
class Template:
    id: str
    raw: dict[str, Any]
    header: list[SimpleField] = field(default_factory=list)
    weekly: list[WeeklyRow] = field(default_factory=list)
    sections: dict[int, str] = field(default_factory=dict)
    page2: list[SimpleField] = field(default_factory=list)

    @property
    def workbook(self) -> dict[str, Any]:
        return self.raw["workbook"]

    @property
    def validation(self) -> dict[str, Any]:
        return self.raw.get("validation", {})

    @property
    def table_shape(self) -> tuple[int, int]:
        """(rows, cols) of the weekly table including the header row."""
        last = max([r.row for r in self.weekly] + list(self.sections))
        return last + 1, len(self.raw["weekly_table"]["columns"])

    def weekly_row(self, key: str) -> WeeklyRow:
        for r in self.weekly:
            if r.key == key:
                return r
        raise KeyError(key)

    def all_field_ids(self) -> list[str]:
        ids = [f"header.{f.key}" for f in self.header]
        for r in self.weekly:
            ids += [r.field_id(c) for c in r.columns]
        for f in self.page2:
            if f.type == "table":
                for i in range(f.max_rows):
                    ids += [f"page2.{f.key}.{i}.{c['key']}" for c in f.columns]
            else:
                ids.append(f"page2.{f.key}")
        return ids

    def field_type(self, field_id: str) -> str:
        parts = field_id.split(".")
        if parts[0] == "header":
            return next(f.type for f in self.header if f.key == parts[1])
        if parts[0] == "weekly":
            return self.weekly_row(parts[1]).type
        f = next(f for f in self.page2 if f.key == parts[1])
        if f.type == "table":
            return next(c["type"] for c in f.columns if c["key"] == parts[3])
        return f.type

    def field_label(self, field_id: str) -> str:
        parts = field_id.split(".")
        if parts[0] == "header":
            return next(f.label for f in self.header if f.key == parts[1])
        if parts[0] == "weekly":
            return f"{self.weekly_row(parts[1]).label} — {parts[2]}"
        f = next(f for f in self.page2 if f.key == parts[1])
        if f.type == "table":
            return f"{f.label} — row {int(parts[2]) + 1}, {parts[3]}"
        return f.label


def _simple(d: dict[str, Any]) -> SimpleField:
    return SimpleField(
        key=d["key"], label=d["label"], type=d["type"],
        required=d.get("required", False), min=d.get("min"), max=d.get("max"),
        columns=tuple(d.get("columns", ())), max_rows=d.get("max_rows", 0),
    )


@lru_cache
def load_template(template_id: str = "palmera_shg_monthly_v3") -> Template:
    raw = yaml.safe_load((CONFIG_DIR / f"{template_id}.yaml").read_text(encoding="utf-8"))
    t = Template(id=raw["template_id"], raw=raw)
    t.header = [_simple(d) for d in raw["header_fields"]]
    t.page2 = [_simple(d) for d in raw["page2_fields"]]
    for d in raw["weekly_table"]["rows"]:
        if "section" in d:
            t.sections[d["row"]] = d["section"]
        else:
            t.weekly.append(WeeklyRow(
                row=d["row"], key=d["key"], label=d["label"], type=d["type"],
                kind=d.get("kind", "flow"), weeks=d.get("weeks", True), total=d.get("total", True),
            ))
    return t
