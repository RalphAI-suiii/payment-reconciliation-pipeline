import argparse
import sys
from datetime import date
from pathlib import Path

from .generator import generate_inputs
from .pipeline import reconcile_batch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a synthetic payment reconciliation batch.")
    parser.add_argument(
        "--batch-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Batch date in YYYY-MM-DD format (default: computer's local date).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Root folder for generated inputs and outputs (default: ./data).",
    )
    args = parser.parse_args(argv)

    raw_dir = args.data_dir / "raw" / args.batch_date.isoformat()
    output_dir = args.data_dir / "output" / args.batch_date.isoformat()
    try:
        generate_inputs(raw_dir, args.batch_date)
        report = reconcile_batch(raw_dir, output_dir, args.batch_date)
    except (OSError, ValueError) as error:
        print(f"Batch failed: {error}", file=sys.stderr)
        return 1

    print(
        f"Batch {report['batch_id']}: {report['matched_count']} matched, "
        f"{report['exception_count']} exceptions, {report['quarantined_count']} quarantined."
    )
    print(f"Report: {output_dir / 'report.json'}")
    return 0

