#!/usr/bin/env python3
"""
Debug probe: dump the FULL Coros activity-detail JSON and hunt for the
rest-vs-run interval structure.

Background: Coros' downloaded FIT files carry no work/rest lap marker
(intensity/lap_trigger are empty, no workout_step messages), yet the Coros app
shows rest vs. run laps. That structure must come from their cloud API. This
script fetches the complete `/activity/detail/query` payload (which we normally
narrow to just RPE/notes) and reports where, if anywhere, interval data lives.

Usage (from backend/, with Coros creds in the environment):
    COROS_EMAIL=you@example.com COROS_PASSWORD=secret \
        python3 scripts/coros_dump_detail.py [LABEL_ID ...]

  - No args:      lists recent activities, then dumps the one with the most laps
                  (best guess for an interval workout).
  - LABEL_ID(s):  dump those specific activities (labelIds from the listing).
  - --all:        dump every activity on the first page.

For each target it writes coros_detail_<labelId>.json and prints a recursive
scan for keys matching lap/interval/rest/segment/step/phase/work.
"""
import json
import re
import sys
from pathlib import Path

# Make `app` importable when run as `python3 scripts/coros_dump_detail.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import COROS_EMAIL, COROS_PASSWORD
from app.services.coros import login, list_activities, get_activity_detail_raw

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "coros_debug"
KEY_RE = re.compile(r"lap|interval|rest|segment|step|phase|work|effort", re.I)


def _scan(obj, path="data", hits=None):
    """Recursively collect paths whose key looks interval/lap-related."""
    if hits is None:
        hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}"
            if KEY_RE.search(str(k)):
                hits.append((here, _describe(v)))
            _scan(v, here, hits)
    elif isinstance(obj, list):
        # Scan only the first element to keep output readable; note list length.
        if obj:
            _scan(obj[0], f"{path}[0]", hits)
    return hits


def _describe(v):
    if isinstance(v, list):
        sample = v[0] if v else None
        inner = sorted(sample.keys()) if isinstance(sample, dict) else type(sample).__name__
        return f"list[{len(v)}] of {inner}"
    if isinstance(v, dict):
        return f"dict keys={sorted(v.keys())}"
    s = repr(v)
    return s if len(s) <= 60 else s[:57] + "..."


def main(argv):
    if not COROS_EMAIL or not COROS_PASSWORD:
        sys.exit("COROS_EMAIL / COROS_PASSWORD not set in the environment.")

    token, user_id = login(COROS_EMAIL, COROS_PASSWORD)
    acts = list_activities(token, user_id)
    if not acts:
        sys.exit("No activities returned by Coros.")

    # Show the listing so labelIds are easy to grab.
    print(f"\n{len(acts)} activities on page 1:\n")
    print(f"{'#':>3}  {'labelId':<16} {'sportType':<10} {'laps':>4}  name")
    for i, a in enumerate(acts):
        nlaps = a.get("lapItemList") or a.get("lapList") or []
        nlaps = len(nlaps) if isinstance(nlaps, list) else "?"
        print(f"{i:>3}  {str(a.get('labelId','')):<16} "
              f"{str(a.get('sportType','')):<10} {str(nlaps):>4}  {a.get('name') or ''}")

    args = [x for x in argv if not x.startswith("-")]
    if "--all" in argv:
        targets = acts
    elif args:
        wanted = set(args)
        targets = [a for a in acts if str(a.get("labelId")) in wanted]
        if not targets:
            sys.exit(f"None of {args} matched a listed labelId.")
    else:
        # Auto-pick: the activity with the most laps (likeliest interval workout).
        def lapcount(a):
            v = a.get("lapItemList") or a.get("lapList") or []
            return len(v) if isinstance(v, list) else 0
        targets = [max(acts, key=lapcount)]
        print(f"\nNo labelId given → auto-picking most-lapped activity: "
              f"{targets[0].get('labelId')} ({lapcount(targets[0])} laps)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for a in targets:
        label_id = str(a.get("labelId"))
        sport_type = str(a.get("sportType", "100"))
        print(f"\n{'='*70}\nDUMP {label_id}  sportType={sport_type}  name={a.get('name')!r}")
        try:
            data = get_activity_detail_raw(token, user_id, label_id, sport_type)
        except Exception as e:
            print(f"  ERROR fetching detail: {e}")
            continue

        out = OUT_DIR / f"coros_detail_{label_id}.json"
        out.write_text(json.dumps(data, indent=2, default=str))
        print(f"  wrote {out}  ({out.stat().st_size} bytes)")
        print(f"  top-level data keys: {sorted(data.keys())}")

        hits = _scan(data)
        if hits:
            print("  interval/lap-related fields found:")
            for path, desc in hits:
                print(f"    {path}: {desc}")
        else:
            print("  >>> NO interval/lap/rest-related keys found in detail payload.")


if __name__ == "__main__":
    main(sys.argv[1:])
