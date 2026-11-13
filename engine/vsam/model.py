"""Semantic model of a VSAM-style dataset, and what is and is not proven for it.

Deterministic data definitions only; nothing here executes a program.  Two
things are kept apart on purpose:

* ``DatasetDefinition`` describes one dataset (organization, record format,
  keys, encoding) and ``validate()`` refuses combinations IBM VSAM does not
  allow, naming each problem;
* ``CAPABILITIES`` classifies every capability separately, with the evidence
  class that actually backs it.  There is no ``VSAM_SUPPORTED`` flag: ESDS,
  RRDS, alternate indexes and IDCAMS commands have different status.

Evidence classes (never promoted to one another):
``GNUCOBOL_DIFFERENTIAL`` - generated Java compared with GnuCOBOL 3.1.2 on a
bounded shape; ``DETERMINISTIC_TEST`` - repository tests only, no reference
runtime; ``DOCUMENTED_SEMANTICS`` - implemented from IBM documentation with no
IBM runtime; ``NONE``.  ``IBM_RUNTIME_VERIFIED`` would need a licensed z/OS
environment and appears nowhere here.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Organization(str, Enum):
    SEQUENTIAL = "SEQUENTIAL"
    KSDS = "KSDS"  # key-sequenced
    ESDS = "ESDS"  # entry-sequenced (RBA)
    RRDS = "RRDS"  # relative record (RRN)


class RecordFormat(str, Enum):
    FIXED = "FIXED"
    VARIABLE = "VARIABLE"  # 4-byte RDW (big-endian length incl. RDW, 2 zero bytes) before each record


class Encoding(str, Enum):
    ASCII = "ASCII"
    EBCDIC_CP037 = "EBCDIC_CP037"


class AccessMode(str, Enum):
    SEQUENTIAL = "SEQUENTIAL"
    RANDOM = "RANDOM"
    DYNAMIC = "DYNAMIC"


class KeyKind(str, Enum):
    CHARACTER = "CHARACTER"  # collates by the dataset encoding's byte order
    BINARY = "BINARY"  # packed/binary: compared as raw bytes, never translated


@dataclass(frozen=True)
class KeyDefinition:
    offset: int  # zero-based byte offset inside the record
    length: int
    unique: bool = True
    kind: KeyKind = KeyKind.CHARACTER


@dataclass(frozen=True)
class DatasetDefinition:
    name: str
    organization: Organization
    record_format: RecordFormat = RecordFormat.FIXED
    record_length: int = 0  # fixed: the length; variable: the maximum length (without the RDW)
    encoding: Encoding = Encoding.ASCII
    primary_key: KeyDefinition | None = None
    alternate_keys: tuple[KeyDefinition, ...] = ()
    access_modes: tuple[AccessMode, ...] = (AccessMode.SEQUENTIAL,)

    def validate(self) -> tuple[str, ...]:
        """Every reason this definition cannot describe a real VSAM dataset."""
        problems: list[str] = []
        if not self.name:
            problems.append("dataset has no name")
        if self.record_length <= 0:
            problems.append(f"{self.name}: record length must be positive")
        org = self.organization
        if org is Organization.KSDS:
            if self.primary_key is None:
                problems.append(f"{self.name}: a KSDS requires a primary key")
            elif not self.primary_key.unique:
                problems.append(f"{self.name}: a KSDS primary key must be unique")
        else:
            if self.primary_key is not None:
                problems.append(f"{self.name}: only a KSDS has a primary key ({org.value} is addressed by "
                                f"{'RBA' if org is Organization.ESDS else 'RRN' if org is Organization.RRDS else 'position'})")
            if self.alternate_keys and org is Organization.RRDS:
                problems.append(f"{self.name}: an RRDS cannot have an alternate index")
            if self.alternate_keys and org is Organization.SEQUENTIAL:
                problems.append(f"{self.name}: a sequential dataset cannot have an alternate index")
        for index, key in enumerate((self.primary_key, *self.alternate_keys)):
            if key is None:
                continue
            label = "primary key" if index == 0 else f"alternate key {index}"
            if key.length <= 0 or key.offset < 0:
                problems.append(f"{self.name}: {label} has a non-positive length or negative offset")
            elif self.record_length and key.offset + key.length > self.record_length:
                problems.append(f"{self.name}: {label} (offset {key.offset}, length {key.length}) "
                                f"lies outside the {self.record_length}-byte record")
        if org is Organization.RRDS and self.record_format is RecordFormat.VARIABLE:
            problems.append(f"{self.name}: variable-length RRDS is not modelled (fixed-length slots only)")
        return tuple(problems)


@dataclass(frozen=True)
class Capability:
    id: str
    organization: Organization | None
    status: str  # IMPLEMENTED_AND_VERIFIED | IMPLEMENTED_NOT_RUNTIME_VERIFIED | PARTIAL | UNSUPPORTED | NOT_IMPLEMENTED
    evidence_class: str
    note: str


_G = "GNUCOBOL_DIFFERENTIAL"
CAPABILITIES: tuple[Capability, ...] = (
    Capability("ksds.primary_key.sequential_random_dynamic", Organization.KSDS, "IMPLEMENTED_AND_VERIFIED", _G,
               "ORGANIZATION INDEXED, primary RECORD KEY, ACCESS SEQUENTIAL/RANDOM/DYNAMIC, START, READ NEXT, "
               "REWRITE, DELETE, FILE STATUS; certified bounded subset (fixtures workload-indexed*). "
               "GnuCOBOL INDEXED is not IBM KSDS: ordering above ASCII keys, spanned records and CI/CA behaviour untested"),
    Capability("ksds.alternate_key.bounded_browse", Organization.KSDS, "PARTIAL", _G,
               "alternate-key random read and the single certified browse shape (ACCESS DYNAMIC, two alternate keys, "
               "PIC X(2), FILE STATUS only); not generalised to other alternate indexes"),
    Capability("ksds.ebcdic_key_collation", Organization.KSDS, "IMPLEMENTED_NOT_RUNTIME_VERIFIED", "DETERMINISTIC_TEST",
               "engine.vsam.collation orders EBCDIC cp037 keys by byte value; no IBM or GnuCOBOL EBCDIC run"),
    Capability("esds.entry_sequence_rba", Organization.ESDS, "NOT_IMPLEMENTED", "NONE",
               "GnuCOBOL has no ESDS or RBA addressing, so no local reference exists; needs an IBM environment"),
    Capability("rrds.relative_record_number", Organization.RRDS, "PARTIAL", _G,
               "ORGANIZATION RELATIVE verified against GnuCOBOL on a bounded shape (workload-relative*); "
               "IBM RRDS slot reuse, variable RRDS and file-status details are not established"),
    Capability("records.variable_length_rdw", None, "PARTIAL", "DETERMINISTIC_TEST",
               "RDW parsing in engine.vsam.reconcile; record-sequential variable files are compared with GnuCOBOL "
               "(workload-record-sequential), spanned records are not supported"),
    Capability("records.packed_binary_fields", None, "IMPLEMENTED_AND_VERIFIED", _G,
               "COMP / COMP-3 fields compared with GnuCOBOL (workload-comp, workload-comp3, workload-binary-values)"),
    Capability("migration.reconciliation_report", None, "IMPLEMENTED_NOT_RUNTIME_VERIFIED", "DETERMINISTIC_TEST",
               "engine.vsam.reconcile: counts, rejected records, duplicate keys, key set, ordering and hashes"),
    Capability("idcams.define_gdg_repro_delete_setmaxcc", None, "PARTIAL", "DOCUMENTED_SEMANTICS",
               "engine.jcl.orchestrator native subset; reference runner refuses IDCAMS, so no oracle comparison"),
    Capability("idcams.define_cluster_listcat_bldindex_alter", None, "NOT_IMPLEMENTED", "NONE",
               "refused with a diagnostic; no cluster catalogue exists"),
    Capability("vsam.spanned_records_linear_datasets", None, "UNSUPPORTED", "NONE", "refused by name"),
    Capability("vsam.rba_rrn_direct_addressing", None, "NOT_IMPLEMENTED", "NONE",
               "needs ESDS/RRDS reference behaviour that only an IBM environment can supply"),
    Capability("vsam.ibm_runtime_equivalence", None, "NOT_IMPLEMENTED", "NONE",
               "no IBM runtime evidence exists; nothing in this model is IBM_RUNTIME_VERIFIED"),
)


def capability(capability_id: str) -> Capability:
    for item in CAPABILITIES:
        if item.id == capability_id:
            return item
    raise KeyError(capability_id)
