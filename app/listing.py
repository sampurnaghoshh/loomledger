"""Paged, searchable, sortable lists — one helper for every `/list`-style endpoint.

    GET ...?page=1&page_size=25&q=meridian&sort=-promised_date&status=in_production
    -> {"items": [...], "total": 312, "page": 1, "page_size": 25}

Safety: nothing from the request is ever interpolated into SQL. A sort key or filter name is looked up in the
endpoint's whitelist (a dict) and the *mapped* column is composed with psycopg.sql.Identifier; every value is a
bound parameter. An unknown sort key is a 422 (VALIDATION_FAILED, fields.sort). page_size above MAX_PAGE_SIZE is
clamped (the response says which size was used). Search is a case-insensitive "contains" over the listed columns,
with LIKE wildcards in the input escaped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Generic, Literal, TypeVar

import psycopg
from fastapi import Depends, Query
from psycopg import sql
from pydantic import BaseModel

from app.errors import ApiError

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
T = TypeVar("T")

FilterOp = Literal["eq", "gte", "lt", "positive"]   # positive: True -> col > 0, False -> col is 0 or null
_OPS = {"eq": "=", "gte": ">=", "lt": "<"}


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class ListQuery:
    page: int
    page_size: int
    q: str | None
    sort: str | None


def list_query(page: Annotated[int, Query(ge=1, le=100_000)] = 1,
               page_size: Annotated[int, Query(ge=1, le=10_000)] = DEFAULT_PAGE_SIZE,
               q: Annotated[str | None, Query(max_length=100)] = None,
               sort: Annotated[str | None, Query(max_length=40)] = None) -> ListQuery:
    return ListQuery(page=page, page_size=min(page_size, MAX_PAGE_SIZE), q=(q or "").strip() or None, sort=sort)


ListParams = Annotated[ListQuery, Depends(list_query)]


@dataclass(frozen=True)
class Filter:
    column: str
    op: FilterOp = "eq"


@dataclass(frozen=True)
class Listing:
    """source: a SELECT (no ORDER BY / LIMIT) whose output columns are the item fields; it may use %(name)s
    parameters given to fetch(). sort: API sort key -> output column. tiebreak: a unique output column so pages
    never overlap. search: output columns matched by `q`. filters: API filter name -> Filter."""
    source: str
    sort: dict[str, str]
    default_sort: str
    tiebreak: str
    search: tuple[str, ...] = ()
    filters: dict[str, Filter] = field(default_factory=dict)

    def __post_init__(self):
        key = self.default_sort.removeprefix("-")
        assert key in self.sort, f"default sort {key!r} is not whitelisted"

    def _order(self, requested: str | None) -> sql.Composed:
        raw = requested or self.default_sort
        desc = raw.startswith("-")
        key = raw.removeprefix("-")
        column = self.sort.get(key)
        if column is None:
            raise ApiError("VALIDATION_FAILED", "Please correct the highlighted fields.", 422,
                           fields={"sort": f"unknown sort column {key!r}; use one of: {', '.join(sorted(self.sort))} "
                                           "(prefix with - for descending)"})
        direction = sql.SQL("DESC NULLS LAST" if desc else "ASC NULLS LAST")
        return sql.SQL("{} {}, {} {}").format(sql.Identifier(column), direction, sql.Identifier(self.tiebreak), direction)

    def fetch(self, conn: psycopg.Connection, query: ListQuery, filters: dict[str, Any] | None = None,
              params: dict[str, Any] | None = None) -> dict:
        args: dict[str, Any] = dict(params or {})
        where: list[sql.Composable] = []
        for name, value in (filters or {}).items():
            if value is None:
                continue
            f = self.filters[name]                         # a KeyError here is a programming error, not input
            key = f"f_{name}"
            col = sql.Identifier(f.column)
            if f.op == "positive":
                where.append(sql.SQL("{} > 0").format(col) if value else sql.SQL("COALESCE({}, 0) = 0").format(col))
                continue
            args[key] = value
            where.append(sql.SQL("{} {} {}").format(col, sql.SQL(_OPS[f.op]), sql.Placeholder(key)))
        if query.q and self.search:
            args["q"] = "%" + query.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append(sql.SQL("({})").format(sql.SQL(" OR ").join(
                sql.SQL("{}::text ILIKE {}").format(sql.Identifier(c), sql.Placeholder("q")) for c in self.search)))
        where_sql = sql.SQL("WHERE ") + sql.SQL(" AND ").join(where) if where else sql.SQL("")
        order = self._order(query.sort)
        args |= {"_limit": query.page_size, "_offset": (query.page - 1) * query.page_size}
        rows = conn.execute(
            sql.SQL("SELECT t.*, count(*) OVER () AS _total FROM ({source}) AS t {where} ORDER BY {order} "
                    "LIMIT %(_limit)s OFFSET %(_offset)s").format(source=sql.SQL(self.source), where=where_sql, order=order),
            args).fetchall()
        if rows:
            total = rows[0]["_total"]
        else:                                              # past the last page: still report how many there are
            total = conn.execute(sql.SQL("SELECT count(*) AS n FROM ({source}) AS t {where}").format(
                source=sql.SQL(self.source), where=where_sql), args).fetchone()["n"]
        for r in rows:
            r.pop("_total", None)
        return {"items": rows, "total": total, "page": query.page, "page_size": query.page_size}
