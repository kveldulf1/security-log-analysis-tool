"""CSV export of findings — flattened for spreadsheet/ticketing tools."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from io import StringIO

from ..models import Finding
from . import finding_to_dict

_SCALAR_FIELDS = [
    "finding_id",
    "rule_id",
    "severity",
    "title",
    "description",
    "ip",
    "first_seen",
    "last_seen",
    "count",
]
_FIELDS = [*_SCALAR_FIELDS, "users", "correlated_rule_ids", "evidence"]


def to_csv(findings: Sequence[Finding]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_FIELDS)
    writer.writeheader()
    for finding in findings:
        row = finding_to_dict(finding)
        writer.writerow(
            {
                **{key: row[key] for key in _SCALAR_FIELDS},
                "users": ";".join(row["users"]),
                "correlated_rule_ids": ";".join(row["correlated_rule_ids"]),
                "evidence": ";".join(f"{e['file']}:{e['line_no']}" for e in row["evidence"]),
            }
        )
    return buffer.getvalue()


def write_csv(findings: Sequence[Finding], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(to_csv(findings))
