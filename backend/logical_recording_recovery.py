"""Dry-run audit and idempotent recovery helpers for legacy transport chunks.

The recovery path never changes completed or in-flight logical recordings by
default.  It only reports legacy rows that look like transport pieces and can
be reviewed before an operator explicitly applies a migration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_CHUNK_NAME = re.compile(r"^(?P<stem>.+)_chunk(?P<index>\d{3})(?P<suffix>\.[^.]+)$")


@dataclass(frozen=True)
class LegacyChunk:
    recording_id: int
    filename: str
    chunk_index: int
    start_time: str | None
    end_time: str | None
    transcribed: int
    synced: int


def parse_legacy_chunk_name(filename: str) -> tuple[str, int] | None:
    """Return the stable source stem and numeric index from an old chunk name."""
    match = _CHUNK_NAME.match(Path(filename).name)
    if not match:
        return None
    return match.group("stem"), int(match.group("index"))


def audit_legacy_chunks(rows: Iterable[dict]) -> dict:
    """Build a read-only migration report without changing database state."""
    candidates = []
    for row in rows:
        parsed = parse_legacy_chunk_name(row.get("filename") or "")
        if parsed is None:
            continue
        stem, index = parsed
        candidates.append({
            "recording_id": row["id"],
            "filename": row["filename"],
            "logical_stem": stem,
            "chunk_index": index,
            "transcribed": row.get("transcribed", 0),
            "synced": row.get("synced", 0),
            "safe_to_review": row.get("transcribed", 0) == 0 and row.get("synced", 0) == 0,
        })
    candidates.sort(key=lambda item: (item["logical_stem"], item["chunk_index"], item["recording_id"]))
    groups: dict[str, list[dict]] = {}
    for item in candidates:
        groups.setdefault(item["logical_stem"], []).append(item)
    return {
        "candidate_count": len(candidates),
        "group_count": len(groups),
        "groups": [
            {"logical_stem": stem, "chunk_count": len(items), "chunks": items}
            for stem, items in sorted(groups.items())
        ],
    }


def transport_order(rows: Iterable[dict]) -> list[dict]:
    """Sort chunks by explicit transport order, then stable recording fields."""
    return sorted(
        rows,
        key=lambda row: (
            row.get("transport_offset_bytes") is None,
            row.get("transport_offset_bytes") if row.get("transport_offset_bytes") is not None else 0,
            row.get("transport_chunk_index") is None,
            row.get("transport_chunk_index") if row.get("transport_chunk_index") is not None else 0,
            row.get("segment_index", 0),
            row.get("start_time") or "",
            row.get("id", 0),
        ),
    )
