#!/usr/bin/env python3
"""Build selfsearch dashboard data from study results.

Usage:
    python -m scripts.build_selfsearch_dashboard
"""

import sys
from pathlib import Path

# Add parent directory to path to import selfsearch module
sys.path.insert(0, str(Path(__file__).parent.parent))

from selfsearch.gen_report import ReportGenerator


def main():
    """Generate dashboard data for both HTML and Next.js app."""
    generator = ReportGenerator()
    results, metrics, noise_assessments = generator.load_study_data()

    # Generate HTML dashboard (to data/study/)
    html_path = generator.generate_html_dashboard(results, metrics, noise_assessments)

    # Generate Next.js JSON data (to dashboard/public/data/)
    json_path = generator.generate_nextjs_json(results, metrics, noise_assessments)

    print(f"\nGenerated dashboard files:")
    print(f"  - HTML: {html_path}")
    print(f"  - JSON: {json_path}")


if __name__ == "__main__":
    main()
