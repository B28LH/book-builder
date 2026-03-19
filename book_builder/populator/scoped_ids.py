"""Persistent scoped XML ID registry for CNXML conversion.

This module keeps generated `xml:id` assignments stable across repeated runs of
the CNXML import pipeline. It stores deterministic scope keys for source nodes
and only falls back to random suffixes when the non-random base ID collides
with another reserved or existing project ID.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


_RANDOM_SUFFIX_RE = re.compile(r"-[A-Za-z0-9]{8}$")


@dataclass(slots=True)
class ScopedIdAssignment:
    """Stored metadata for one scoped ID assignment."""

    base_id: str
    final_id: str
    source_path: str
    target_file: str
    target_section_id: str
    original_id: str
    fallback: str
    resource_code: str = ""


class ScopedIdRegistry:
    """Resolve and persist stable `xml:id` assignments for CNXML imports."""

    def __init__(self, store_path: Path, known_ids: set[str] | None = None) -> None:
        self.store_path = store_path
        self.assignments: dict[str, ScopedIdAssignment] = {}
        self.final_id_to_scope: dict[str, str] = {}
        self.used_ids: set[str] = set(known_ids or set())
        self.dirty = False

    @classmethod
    def load(cls, store_path: Path, known_ids: set[str] | None = None) -> "ScopedIdRegistry":
        """Load registry state from disk if it exists."""
        registry = cls(store_path, known_ids)
        if not store_path.exists():
            return registry

        raw = json.loads(store_path.read_text(encoding="utf-8"))
        for scope_key, payload in raw.get("assignments", {}).items():
            assignment = ScopedIdAssignment(**payload)
            registry.assignments[scope_key] = assignment
            registry.final_id_to_scope[assignment.final_id] = scope_key
            registry.used_ids.add(assignment.final_id)
        return registry

    def save(self) -> None:
        """Write registry state to disk when assignments changed."""
        if not self.dirty:
            return

        payload = {
            "version": 1,
            "assignments": {
                scope_key: asdict(assignment) for scope_key, assignment in sorted(self.assignments.items())
            },
        }
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._write_csv_map()
        self.dirty = False

    def _write_csv_map(self) -> None:
        """Emit a flat CSV map for easier auditing and downstream joins."""
        csv_path = self.store_path.with_suffix(".csv")
        fieldnames = [
            "resource_code",
            "source_path",
            "original_id",
            "new_id",
            "target_file",
            "target_section_id",
            "fallback",
        ]
        rows = [
            {
                "resource_code": assignment.resource_code,
                "source_path": assignment.source_path,
                "original_id": assignment.original_id,
                "new_id": assignment.final_id,
                "target_file": assignment.target_file,
                "target_section_id": assignment.target_section_id,
                "fallback": assignment.fallback,
            }
            for _, assignment in sorted(self.assignments.items())
            if assignment.original_id
        ]

        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def make_scope_key(
        self,
        *,
        source_path: str,
        local_id_prefix: str,
        original_id: str,
        fallback: str,
    ) -> str:
        """Build the deterministic lookup key for a source node ID."""
        return "|".join([source_path, local_id_prefix, original_id, fallback])

    def make_simple_scope_key(
        self,
        *,
        source_path: str,
        resource_code: str,
        original_id: str,
    ) -> str:
        """Build a stable key for original source IDs mapped to short codes."""
        return "|".join([source_path, resource_code, original_id])

    def resolve_simple_code(
        self,
        *,
        scope_key: str,
        resource_code: str,
        source_path: str,
        target_file: str,
        target_section_id: str,
        original_id: str,
        fallback: str,
        random_token_factory,
    ) -> str:
        """Return a stable `{RESOURCE}-XXXXXXXXXX` ID for one original source ID."""
        existing = self.assignments.get(scope_key)
        if existing is not None:
            self.used_ids.add(existing.final_id)
            self.final_id_to_scope[existing.final_id] = scope_key
            return existing.final_id

        clean_resource = re.sub(r"[^A-Za-z0-9]+", "", (resource_code or "SRC").upper()) or "SRC"
        while True:
            candidate = f"{clean_resource}-{random_token_factory(10)}"
            if candidate in self.used_ids or candidate in self.final_id_to_scope:
                continue
            return self._store(
                scope_key=scope_key,
                base_id=clean_resource,
                final_id=candidate,
                source_path=source_path,
                target_file=target_file,
                target_section_id=target_section_id,
                original_id=original_id,
                fallback=fallback,
                resource_code=clean_resource,
            )

    def resolve(
        self,
        *,
        scope_key: str,
        base_id: str,
        source_path: str,
        target_file: str,
        target_section_id: str,
        original_id: str,
        fallback: str,
        existing_target_ids: set[str] | None = None,
        random_token_factory,
    ) -> str:
        """Return a stable final ID, allocating a suffix only when required."""
        existing = self.assignments.get(scope_key)
        if existing is not None:
            self.used_ids.add(existing.final_id)
            self.final_id_to_scope[existing.final_id] = scope_key
            return existing.final_id

        adopted = self._adopt_existing_target_id(base_id, scope_key, existing_target_ids or set())
        if adopted is not None:
            return self._store(
                scope_key=scope_key,
                base_id=base_id,
                final_id=adopted,
                source_path=source_path,
                target_file=target_file,
                target_section_id=target_section_id,
                original_id=original_id,
                fallback=fallback,
            )

        owner = self.final_id_to_scope.get(base_id)
        if base_id not in self.used_ids or owner in {None, scope_key}:
            return self._store(
                scope_key=scope_key,
                base_id=base_id,
                final_id=base_id,
                source_path=source_path,
                target_file=target_file,
                target_section_id=target_section_id,
                original_id=original_id,
                fallback=fallback,
            )

        while True:
            candidate = f"{base_id}-{random_token_factory(8)}"
            if candidate not in self.used_ids and candidate not in self.final_id_to_scope:
                return self._store(
                    scope_key=scope_key,
                    base_id=base_id,
                    final_id=candidate,
                    source_path=source_path,
                    target_file=target_file,
                    target_section_id=target_section_id,
                    original_id=original_id,
                    fallback=fallback,
                )

    def _adopt_existing_target_id(self, base_id: str, scope_key: str, existing_target_ids: set[str]) -> str | None:
        if base_id in existing_target_ids and self.final_id_to_scope.get(base_id) in {None, scope_key}:
            return base_id

        patterned = sorted(
            candidate
            for candidate in existing_target_ids
            if candidate.startswith(f"{base_id}-") and _RANDOM_SUFFIX_RE.search(candidate)
        )
        if len(patterned) == 1 and self.final_id_to_scope.get(patterned[0]) in {None, scope_key}:
            return patterned[0]
        return None

    def _store(
        self,
        *,
        scope_key: str,
        base_id: str,
        final_id: str,
        source_path: str,
        target_file: str,
        target_section_id: str,
        original_id: str,
        fallback: str,
        resource_code: str = "",
    ) -> str:
        assignment = ScopedIdAssignment(
            base_id=base_id,
            final_id=final_id,
            source_path=source_path,
            target_file=target_file,
            target_section_id=target_section_id,
            original_id=original_id,
            fallback=fallback,
            resource_code=resource_code,
        )
        self.assignments[scope_key] = assignment
        self.final_id_to_scope[final_id] = scope_key
        self.used_ids.add(final_id)
        self.dirty = True
        return final_id