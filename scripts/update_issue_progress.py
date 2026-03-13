from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.progress_tracker import build_progress_snapshot


def _read_issues(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return payload.get("issues", [])


def update_issue_progress(issues_path: Path | str, output_dir: Path | str, as_of_utc: str | None = None) -> dict[str, str]:
    if as_of_utc is None:
        as_of_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    issues = _read_issues(Path(issues_path))
    progress = build_progress_snapshot(issues, as_of_utc=as_of_utc)
    blockers = progress["blockers"]

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    issues_snapshot_path = out_dir / "issues_snapshot.json"
    progress_snapshot_path = out_dir / "progress_snapshot.json"
    blockers_snapshot_path = out_dir / "blockers_snapshot.json"

    issues_snapshot_path.write_text(
        json.dumps({"version": "v1", "as_of_utc": as_of_utc, "data": issues}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    progress_snapshot_path.write_text(json.dumps(progress, ensure_ascii=True, indent=2), encoding="utf-8")
    blockers_snapshot_path.write_text(
        json.dumps({"version": "v1", "as_of_utc": as_of_utc, "data": blockers}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    return {
        "issues_snapshot": str(issues_snapshot_path),
        "progress_snapshot": str(progress_snapshot_path),
        "blockers_snapshot": str(blockers_snapshot_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate issues/progress snapshots for dashboard.")
    parser.add_argument("--issues", default="output/dashboard/issues_input.json", help="Input issues JSON file")
    parser.add_argument("--output-dir", default="output/dashboard", help="Output directory")
    parser.add_argument("--as-of", dest="as_of_utc", default=None, help="As-of UTC timestamp")
    args = parser.parse_args()

    result = update_issue_progress(args.issues, args.output_dir, args.as_of_utc)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
