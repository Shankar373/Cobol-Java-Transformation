"""DB2 SQLCODE / SQLSTATE status handling model.

Models the subset of DB2 SQL status semantics used by embedded SQL host
programs.  Values are DB2-documented constants (syntax/semantic domain):

- 0      / '00000' successful completion
- 100    / '02000' no row found (singleton SELECT or end of FETCH)
- -811   / '21000' cardinality violation: singleton SELECT returned > 1 row
- -803   / '23505' duplicate key on INSERT/UPDATE

Plus one explicit lane sentinel for failures outside the mapped subset
(BL-060): -1 / '56000' via ``Db2SqlStatus.unmapped_error`` — a
well-formed ERROR, never a claim about the exact DB2 code for that
condition.

Scope discipline (see module docstring on ``engine/sql``): these are DB2
*semantic* constants.  They make test databases behave like DB2 at the
status boundary, but a passing controller does NOT prove DB2 runtime
equivalence.  That requires verification against a real DB2 subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

SQLCODE_SUCCESS = 0
SQLSTATE_SUCCESS = "00000"

SQLCODE_NO_DATA = 100
SQLSTATE_NO_DATA = "02000"

SQLCODE_TOO_MANY_ROWS = -811
SQLSTATE_TOO_MANY_ROWS = "21000"

SQLCODE_DUPLICATE_KEY = -803
SQLSTATE_DUPLICATE_KEY = "23505"

#: Lane sentinel for a failure OUTSIDE the mapped subset (BL-060).
#: SQLCODE -1 is not a DB2-documented code in this modeled subset: it
#: marks "unclassified failure on the controlled database" so error
#: handlers always return a well-formed ERROR status instead of
#: constructing an invalid one.  SQLSTATE '56000' sits in DB2 class 56
#: (internal error processing) and is used here as the lane's unmapped
#: placeholder — it does NOT claim the exact DB2 SQLSTATE for the
#: specific condition.
SQLCODE_UNMAPPED_ERROR = -1
SQLSTATE_UNMAPPED_ERROR = "56000"


class Db2SqlCodeCategory(Enum):
    """Broad category of a DB2 SQLCODE value."""

    SUCCESS = "SUCCESS"
    NO_DATA = "NO_DATA"
    ERROR = "ERROR"


def classify_sqlcode(sqlcode: int) -> Db2SqlCodeCategory:
    """Classify a DB2 SQLCODE value into a broad category.

    DB2 convention:
    - 0         successful completion
    - positive  warning / informational (module models only NO_DATA = 100)
    - negative  error
    """
    if sqlcode == SQLCODE_SUCCESS:
        return Db2SqlCodeCategory.SUCCESS
    if sqlcode == SQLCODE_NO_DATA:
        return Db2SqlCodeCategory.NO_DATA
    if sqlcode < 0:
        return Db2SqlCodeCategory.ERROR
    return Db2SqlCodeCategory.SUCCESS


@dataclass(frozen=True)
class Db2SqlStatus:
    """A single execution status in DB2-compatible domain values.

    Attributes mirror the DB2 status fields exposed to host programs:
    ``SQLCODE`` (int) and ``SQLSTATE`` (5-char code).
    """

    sqlcode: int = SQLCODE_SUCCESS
    sqlstate: str = SQLSTATE_SUCCESS
    message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.sqlcode, int):
            raise TypeError(f"sqlcode must be int, got {type(self.sqlcode)!r}")
        if not isinstance(self.sqlstate, str) or len(self.sqlstate) != 5:
            raise ValueError(f"sqlstate must be a 5-char string, got {self.sqlstate!r}")

    @property
    def category(self) -> Db2SqlCodeCategory:
        return classify_sqlcode(self.sqlcode)

    @property
    def is_success(self) -> bool:
        return self.sqlcode == SQLCODE_SUCCESS

    @property
    def is_no_data(self) -> bool:
        return self.sqlcode == SQLCODE_NO_DATA

    @property
    def is_error(self) -> bool:
        return self.sqlcode < 0

    @classmethod
    def success(cls) -> Db2SqlStatus:
        return cls(sqlcode=SQLCODE_SUCCESS, sqlstate=SQLSTATE_SUCCESS)

    @classmethod
    def no_data(cls) -> Db2SqlStatus:
        return cls(sqlcode=SQLCODE_NO_DATA, sqlstate=SQLSTATE_NO_DATA)

    @classmethod
    def too_many_rows(cls) -> Db2SqlStatus:
        return cls(
            sqlcode=SQLCODE_TOO_MANY_ROWS,
            sqlstate=SQLSTATE_TOO_MANY_ROWS,
            message="SELECT INTO (or FETCH) returned more than one row",
        )

    @classmethod
    def duplicate_key(cls) -> Db2SqlStatus:
        return cls(
            sqlcode=SQLCODE_DUPLICATE_KEY,
            sqlstate=SQLSTATE_DUPLICATE_KEY,
            message="Duplicate key value in unique or primary index",
        )

    @classmethod
    def unmapped_error(cls, message: str) -> Db2SqlStatus:
        """Well-formed status for a failure outside the mapped subset.

        Used by the controlled-database error handlers so an unmapped
        ``IntegrityError``/``OperationalError`` is reported as a normal
        ERROR result instead of crashing the handler (BL-060).
        """
        return cls(
            sqlcode=SQLCODE_UNMAPPED_ERROR,
            sqlstate=SQLSTATE_UNMAPPED_ERROR,
            message=message,
        )


#: Aggregate of statuses a singleton SELECT INTO can produce.
SINGLETON_SELECT_STATUSES = (
    Db2SqlStatus.success(),
    Db2SqlStatus.no_data(),
    Db2SqlStatus.too_many_rows(),
)

#: Aggregate of statuses a DML statement can produce within the subset.
DML_STATUSES = (
    Db2SqlStatus.success(),
    Db2SqlStatus.duplicate_key(),
)

#: DELETE within the subset has no unique-key outcome.
DELETE_STATUSES = (
    Db2SqlStatus.success(),
)