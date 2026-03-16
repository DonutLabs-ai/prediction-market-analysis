#!/usr/bin/env python3
"""Selfsearch package entry point — LLM vs Market Efficiency Study.

Usage:
    python -m selfsearch              # Show help
    python -m selfsearch run          # Run full study
    python -m selfsearch source_events # Source events
"""

import sys


def main():
    """Entry point for python -m selfsearch."""
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nAvailable commands:")
        print("  run            - Run full LLM vs Market study")
        print("  source_events  - Source events")
        print("\nExamples:")
        print("  python -m selfsearch run --tickers COIN,MSTR")
        print("  python -m selfsearch run --events data/study/events.json")
        return

    command = sys.argv[1]

    if command == "run":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        from .run_study import main as run_study_main
        run_study_main()

    elif command == "source_events":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        from .source_events import main as source_events_main
        source_events_main()

    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
