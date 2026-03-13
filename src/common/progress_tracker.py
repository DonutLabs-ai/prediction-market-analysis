from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any


def build_progress_snapshot(issues: list[dict[str, Any]], as_of_utc: str | None = None) -> dict[str, Any]:
    counters = Counter(issue.get("status", "unknown") for issue in issues)
    total = len(issues)
    done = counters.get("done", 0)
    completion_pct = 0.0 if total == 0 else round(100.0 * done / total, 2)

    blockers = [i for i in issues if i.get("status") == "blocked"]
    owners = sorted({str(i.get("owner")) for i in issues if i.get("owner")})

    if as_of_utc is None:
        as_of_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "as_of_utc": as_of_utc,
        "totals": {
            "all": total,
            "done": done,
            "in_progress": counters.get("in_progress", 0),
            "blocked": counters.get("blocked", 0),
            "todo": counters.get("todo", 0),
            "unknown": counters.get("unknown", 0),
        },
        "completion_pct": completion_pct,
        "owners": owners,
        "blockers": blockers,
    }
