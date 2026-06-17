"""Persistent event logging.

Writes structured events to the ``EventLog`` table. Two call styles:

* ``log_event(..., session=s)`` — write through an existing session (used by
  request handlers so the row lands in the same DB the request sees, and in
  tests the in-memory DB). Commits immediately.
* ``log_event(...)`` with no session — opens its own short-lived session on the
  global engine and commits at once. This is deliberately a *separate*
  transaction so an event survives even if the surrounding work (e.g. a sync
  that is about to raise) rolls back. Used by the background sync jobs.

Every event is also mirrored to stdout so it shows up in ``docker logs``.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlmodel import Session, select, delete as sa_delete

from app.database import engine
from app.models import EventLog

# Keep the table bounded — this is a single-user personal app, so the newest
# few thousand events are plenty of history. Trim periodically rather than on
# every write to avoid the extra query on the hot path.
_MAX_ROWS = 5000
_TRIM_EVERY = 100
_write_count = 0


def _coerce_details(details: Any) -> Optional[str]:
    if details is None:
        return None
    if isinstance(details, str):
        return details
    try:
        return json.dumps(details, default=str, sort_keys=True)
    except Exception:
        return str(details)


def _maybe_trim(session: Session) -> None:
    global _write_count
    _write_count += 1
    if _write_count % _TRIM_EVERY != 0:
        return
    stale_ids = session.exec(
        select(EventLog.id).order_by(EventLog.id.desc()).offset(_MAX_ROWS)
    ).all()
    if stale_ids:
        session.exec(sa_delete(EventLog).where(EventLog.id.in_(stale_ids)))
        session.commit()


def log_event(
    level: str,
    category: str,
    message: str,
    details: Any = None,
    *,
    session: Optional[Session] = None,
) -> None:
    """Persist one event. Never raises — logging must not break the caller."""
    print(f"[{level.upper()}] {category}: {message}")
    row = EventLog(
        level=level,
        category=category,
        message=message,
        details=_coerce_details(details),
    )
    try:
        if session is not None:
            session.add(row)
            session.commit()
        else:
            with Session(engine) as own:
                own.add(row)
                own.commit()
                _maybe_trim(own)
    except Exception as exc:  # pragma: no cover - logging must be best-effort
        print(f"[eventlog] failed to persist {category}/{level}: {exc}")


def log_info(category: str, message: str, details: Any = None, *, session=None) -> None:
    log_event("info", category, message, details, session=session)


def log_warning(category: str, message: str, details: Any = None, *, session=None) -> None:
    log_event("warning", category, message, details, session=session)


def log_error(category: str, message: str, details: Any = None, *, session=None) -> None:
    log_event("error", category, message, details, session=session)
