from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_FILES: dict[str, set[str]] = {
    "calibration_by_price.json": {"price", "mispricing_pp", "p_value", "is_significant", "total_positions"},
    "ev_by_outcome.json": {"price", "yes_excess_return", "no_excess_return", "ev_gap_no_minus_yes"},
    "category_efficiency.json": {"category", "flb_amplitude", "longshot_excess_return", "favorite_excess_return"},
}


def validate_dashboard_datasets(input_dir: Path | str) -> dict[str, Any]:
    directory = Path(input_dir)
    errors: list[str] = []
    checks: dict[str, str] = {}

    for filename, required_fields in REQUIRED_FILES.items():
        path = directory / filename
        if not path.exists():
            errors.append(f"missing file: {filename}")
            continue

        payload = json.loads(path.read_text(encoding="utf-8"))
        data = payload.get("data", [])
        if not isinstance(data, list) or not data:
            errors.append(f"empty data: {filename}")
            continue

        first_row = data[0]
        missing_fields = sorted(required_fields - set(first_row.keys()))
        if missing_fields:
            errors.append(f"{filename} missing fields: {', '.join(missing_fields)}")
            continue

        checks[filename] = "ok"

    return {"ok": not errors, "checks": checks, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate dashboard datasets and schemas.")
    parser.add_argument("--input", default="output/dashboard", help="Dashboard dataset directory")
    args = parser.parse_args()

    result = validate_dashboard_datasets(args.input)
    print(json.dumps(result, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
