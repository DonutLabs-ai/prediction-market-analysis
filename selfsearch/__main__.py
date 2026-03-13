#!/usr/bin/env python3
"""Selfsearch package entry point.

Usage:
    python -m selfsearch              # Show help
    python -m selfsearch run          # Run full study
    python -m selfsearch prepare      # Prepare data splits
    python -m selfsearch model val    # Run model on validation set
"""

import sys
from pathlib import Path

# Add selfsearch to path for imports
selfsearch_dir = Path(__file__).parent
sys.path.insert(0, str(selfsearch_dir))


def main():
    """Entry point for python -m selfsearch."""
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nAvailable commands:")
        print("  run       - Run full LLM vs Market study")
        print("  prepare   - Prepare data splits (placeholder)")
        print("  model     - Run model commands (placeholder)")
        print("\nExamples:")
        print("  python -m selfsearch run --tickers COIN,MSTR")
        print("  python -m selfsearch run --events data/study/events.json")
        return

    command = sys.argv[1]

    if command == "run":
        # Run the full study
        from run_study import main as run_study_main
        run_study_main()

    elif command == "prepare":
        print("Prepare command - placeholder for data preparation")
        # TODO: Implement data preparation logic

    elif command == "model":
        if len(sys.argv) > 2 and sys.argv[2] == "val":
            print("Model validation command - placeholder")
            # TODO: Implement model validation logic
        else:
            print("Usage: python -m selfsearch model val")

    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
