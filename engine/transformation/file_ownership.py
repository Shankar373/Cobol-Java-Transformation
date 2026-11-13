"""Which FD owns which record: one rule, shared by the parser and by discovery.

Ownership is a FILE SECTION fact.  Every ``01`` record of every FD is an owner key; a
record declared under more than one FD is *ambiguous* and is reported as such - there is
no last-wins and no inference from names (``-REC`` / ``-FILE`` and the like).

The qualified-name pass renames a data name declared twice (``REC`` -> ``REC-X``,
``REC-X-X``, ...) before the parser sees it, so a duplicated record no longer appears
under its source name.  A family of such renamed records spread over several FDs is
therefore reported as ambiguous under the original name, but only when the original
name is not itself declared (a declared ``REC`` next to a separate ``REC-X`` is two
distinct records, not a renamed family).
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from engine.transformation.ir import FileDefinition

_RENAMED = re.compile(r"(.+?)((?:-X)+)")


@dataclass(frozen=True)
class RecordOwnership:
    owners: dict[str, str] = field(default_factory=dict)  # record -> its only FD
    ambiguous: dict[str, tuple[str, ...]] = field(default_factory=dict)  # record -> FDs that declare it
    file_records: dict[str, tuple[str, ...]] = field(default_factory=dict)  # FD -> its 01 records, declaration order
    buffer_record: dict[str, str] = field(default_factory=dict)  # FD -> FileDefinition.record_name

    def owner_of(self, record: str) -> str | None:
        return self.owners.get(record)

    def candidates(self, record: str) -> tuple[str, ...]:
        """The FDs a record is ambiguous between (empty when it is not ambiguous)."""
        return self.ambiguous.get(record, ())


def record_ownership(file_definitions: Iterable[FileDefinition]) -> RecordOwnership:
    declared: dict[str, list[str]] = {}
    file_records: dict[str, tuple[str, ...]] = {}
    buffer_record: dict[str, str] = {}
    for fd in file_definitions:
        if not fd.name:
            continue
        records = [g.name for g in fd.record_groups if g.name]
        if fd.record_name and fd.record_name not in records:
            records.append(fd.record_name)
        file_records[fd.name] = tuple(dict.fromkeys(records))
        if fd.record_name:
            buffer_record[fd.name] = fd.record_name
        for record in dict.fromkeys(records):
            fds = declared.setdefault(record, [])
            if fd.name not in fds:
                fds.append(fd.name)

    owners = {record: fds[0] for record, fds in declared.items() if len(fds) == 1}
    ambiguous = {record: tuple(sorted(fds)) for record, fds in declared.items() if len(fds) > 1}

    families: dict[str, set[str]] = {}
    for record, record_fds in declared.items():
        found = _RENAMED.fullmatch(record)
        if found and found.group(1) not in declared:
            families.setdefault(found.group(1), set()).update(record_fds)
    for base, family_fds in families.items():
        if len(family_fds) > 1:
            ambiguous[base] = tuple(sorted(family_fds))
    return RecordOwnership(owners, ambiguous, file_records, buffer_record)
