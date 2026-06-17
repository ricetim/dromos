"""Read-only access to the persistent event log.

* ``GET /api/logs``       — JSON, newest first. Filter with ?level=&category=&limit=
* ``GET /api/logs/view``  — self-contained HTML table (no frontend build needed),
                            so it stays usable even if the SPA is broken.
"""
import html
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import EventLog

router = APIRouter(prefix="/api/logs", tags=["logs"])

# Severity ordering so ?level=warning returns warnings AND errors.
_LEVEL_RANK = {"debug": 10, "info": 20, "warning": 30, "error": 40}


def _query(session: Session, level: Optional[str], category: Optional[str], limit: int):
    stmt = select(EventLog).order_by(EventLog.id.desc())
    if level:
        min_rank = _LEVEL_RANK.get(level.lower(), 0)
        allowed = [name for name, rank in _LEVEL_RANK.items() if rank >= min_rank]
        stmt = stmt.where(EventLog.level.in_(allowed))
    if category:
        stmt = stmt.where(EventLog.category.like(f"%{category}%"))
    return session.exec(stmt.limit(limit)).all()


@router.get("")
def list_logs(
    level: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(200, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    rows = _query(session, level, category, limit)
    return [
        {
            "id": r.id,
            "ts": r.ts.isoformat() + "Z",
            "level": r.level,
            "category": r.category,
            "message": r.message,
            "details": r.details,
        }
        for r in rows
    ]


_LEVEL_COLOR = {
    "debug": "#9ca3af",
    "info": "#2563eb",
    "warning": "#d97706",
    "error": "#dc2626",
}

_VIEW_STYLE = """
  :root { color-scheme: light dark; }
  body { font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
         margin: 0; padding: 1.25rem; background: #0b0e14; color: #d7dde8; }
  h1 { font-size: 1.05rem; margin: 0 0 .25rem; }
  .meta { color: #8b95a7; margin-bottom: 1rem; }
  .filters a { color: #7aa2f7; text-decoration: none; margin-right: .6rem; }
  .filters a:hover { text-decoration: underline; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: .3rem .6rem; border-bottom: 1px solid #1c2230;
           vertical-align: top; }
  th { color: #8b95a7; font-weight: 600; position: sticky; top: 0; background: #0b0e14; }
  td.ts { white-space: nowrap; color: #8b95a7; }
  td.cat { white-space: nowrap; color: #b3c0d6; }
  td.lvl { white-space: nowrap; font-weight: 700; text-transform: uppercase; }
  td.details { color: #8b95a7; white-space: pre-wrap; word-break: break-word; }
  tr:hover { background: #11151f; }
  .empty { color: #8b95a7; padding: 1rem 0; }
"""


@router.get("/view", response_class=HTMLResponse)
def view_logs(
    level: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(300, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    rows = _query(session, level, category, limit)

    def esc(v) -> str:
        return html.escape("" if v is None else str(v))

    body_rows = "".join(
        f"<tr>"
        f"<td class='ts'>{esc(r.ts.isoformat(sep=' ', timespec='seconds'))}Z</td>"
        f"<td class='lvl' style='color:{_LEVEL_COLOR.get(r.level, '#d7dde8')}'>{esc(r.level)}</td>"
        f"<td class='cat'>{esc(r.category)}</td>"
        f"<td>{esc(r.message)}</td>"
        f"<td class='details'>{esc(r.details)}</td>"
        f"</tr>"
        for r in rows
    )
    if not body_rows:
        body_rows = "<tr><td colspan='5' class='empty'>No log entries match this filter.</td></tr>"

    active = []
    if level:
        active.append(f"level≥{esc(level)}")
    if category:
        active.append(f"category~{esc(category)}")
    active_txt = " · ".join(active) if active else "all events"

    quick = (
        "<span class='filters'>"
        "<a href='/api/logs/view'>all</a>"
        "<a href='/api/logs/view?level=warning'>warnings+</a>"
        "<a href='/api/logs/view?level=error'>errors</a>"
        "<a href='/api/logs/view?category=sync'>sync</a>"
        "<a href='/api/logs/view?category=delete'>delete</a>"
        "<a href='/api/logs?limit=2000'>raw json</a>"
        "</span>"
    )

    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>dromos logs</title><style>{_VIEW_STYLE}</style></head><body>"
        "<h1>δρόμος — system log</h1>"
        f"<div class='meta'>{len(rows)} most-recent events · {active_txt} · times UTC</div>"
        f"<div class='filters' style='margin-bottom:1rem'>{quick}</div>"
        "<table><thead><tr>"
        "<th>time</th><th>level</th><th>category</th><th>message</th><th>details</th>"
        "</tr></thead><tbody>"
        f"{body_rows}"
        "</tbody></table></body></html>"
    )
