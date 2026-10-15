"""
Open5GS subscriber-document schema compatibility.

Open5GS up to 2.6 kept provisioned sessions in a top-level ``session`` array.
Open5GS 2.7 and later — including 2.8.0, which the testbed images build — keep
them under ``slice[].session[]``.  Documents written by the WebUI may carry
both arrays at once.

Every tool in this artifact reads and writes subscriber sessions through the
helpers below, so one traversal covers either layout.

Background: artifact evaluation (AE #59, reviewers A and C) found the tools
querying only the legacy top-level path.  On an Open5GS 2.8.0 testbed that
matched zero documents, so policy writes moved nothing and the collector read
empty AMBR values — while the write still reported success.  See
``PolicyManager._apply_via_direct_mongo`` for the matching success-reporting
fix.
"""

from __future__ import annotations

from typing import Any, Iterator

# Dotted paths at which a provisioned session's name can live.
SESSION_NAME_PATHS = ("session.name", "slice.session.name")

# Projection that retrieves both layouts.
SESSION_PROJECTION = {"imsi": 1, "session": 1, "slice": 1}


def subscriber_query(slice_name: str, imsi: str | None = None) -> dict[str, Any]:
    """
    Build a Mongo filter matching subscribers that provision ``slice_name``
    under either schema.
    """
    query: dict[str, Any] = {"$or": [{path: slice_name} for path in SESSION_NAME_PATHS]}
    if imsi:
        query = {"$and": [query, {"imsi": imsi}]}
    return query


def iter_sessions(subscriber: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """
    Yield every provisioned session dict in ``subscriber``, under either schema.

    Sessions are yielded by reference, so a caller may mutate them in place and
    then persist the result with :func:`session_update_doc`.
    """
    for session in subscriber.get("session") or []:
        yield session
    for slice_entry in subscriber.get("slice") or []:
        for session in slice_entry.get("session") or []:
            yield session


def iter_named_sessions(
    subscriber: dict[str, Any], slice_name: str
) -> Iterator[dict[str, Any]]:
    """Yield only the sessions in ``subscriber`` whose name is ``slice_name``."""
    for session in iter_sessions(subscriber):
        if session.get("name") == slice_name:
            yield session


def session_update_doc(subscriber: dict[str, Any]) -> dict[str, Any]:
    """
    Build the ``$set`` document that persists in-place session edits, covering
    whichever of the two arrays this subscriber actually carries.
    """
    update: dict[str, Any] = {}
    if subscriber.get("session") is not None:
        update["session"] = subscriber["session"]
    if subscriber.get("slice") is not None:
        update["slice"] = subscriber["slice"]
    return update
