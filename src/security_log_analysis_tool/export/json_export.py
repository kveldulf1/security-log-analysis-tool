"""JSON export of findings — the canonical machine-readable format."""

from __future__ import annotations

import json
from collections.abc import Sequence

from ..models import Finding
from . import findings_to_dicts


def to_json(findings: Sequence[Finding]) -> str:
    return json.dumps(findings_to_dicts(findings), indent=2, ensure_ascii=False)


def write_json(findings: Sequence[Finding], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_json(findings))
