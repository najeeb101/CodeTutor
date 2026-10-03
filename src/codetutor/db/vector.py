"""A pgvector `vector(n)` column for SQLAlchemy, without the pgvector package (Week 4).

The pgvector Python package needs numpy; we only need two small things: send a list of floats
as pgvector's text form '[0.1,0.2,...]', and read that text back into a list. pgvector stores
4-byte floats, so numbers come back slightly rounded (fine for search, not for exact maths).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import Float, cast
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType[list[float]]):
    """A `vector(dimensions)` column: a fixed-length list of floats."""

    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: Any) -> str:
        return "VECTOR" if self.dimensions is None else f"VECTOR({self.dimensions})"

    def bind_expression(self, bindvalue: Any) -> ColumnElement[Any]:
        # An explicit cast, so Postgres never has to guess the type of the '[...]' text.
        return cast(bindvalue, self)

    def bind_processor(self, dialect: Any) -> Callable[[Sequence[float] | None], str | None]:
        def process(value: Sequence[float] | None) -> str | None:
            return None if value is None else to_text(value, self.dimensions)

        return process

    def result_processor(self, dialect: Any, coltype: Any) -> Callable[[str | None], Any]:
        def process(value: str | None) -> list[float] | None:
            return None if value is None else from_text(value)

        return process

    class comparator_factory(UserDefinedType.Comparator[list[float]]):
        """Adds `column.cosine_distance(vector)`: pgvector's `<=>` (0 = same direction)."""

        def cosine_distance(self, other: Sequence[float]) -> ColumnElement[float]:
            return self.op("<=>", return_type=Float())(other)


def to_text(values: Sequence[float], dimensions: int | None = None) -> str:
    """pgvector's text form of `values`. Refuses a wrong length, NaN and infinity."""
    if dimensions is not None and len(values) != dimensions:
        raise ValueError(f"vector has {len(values)} numbers, the column needs {dimensions}")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("vector contains NaN or infinity")
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


def from_text(text: str) -> list[float]:
    """Parse pgvector's text form '[0.1,0.2]' into a list of floats."""
    inner = text.strip().removeprefix("[").removesuffix("]")
    return [float(part) for part in inner.split(",")] if inner else []


# Let SQLAlchemy recognise `vector` columns when it reads a table's structure back (Alembic's
# drift check does). This changes a dictionary inside SQLAlchemy once, at import time: global
# state, but it is how the Postgres dialect is meant to learn new types.
ischema_names["vector"] = Vector
