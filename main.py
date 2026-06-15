"""End-to-end experimental pipeline for the LRP-PS paper."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from comparison.compare import run_all_comparisons
from data.generate_data import generate_benchmarks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LRP-PS B&P and Branch-and-Cut+MCI experiments")
    parser.add_argument("--time-limit", type=float, default=60.0, help="Seconds per method and instance")
    parser.add_argument("--skip-data", action="store_true", help="Reuse existing generated benchmark files")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    if not args.skip_data:
        logging.info("Stage 1/5: generating reproducible instances and data plots")
        generate_benchmarks()
    elif not Path("data/generated_instances").exists():
        raise FileNotFoundError("data/generated_instances does not exist; remove --skip-data")

    logging.info("Solving with paper B&P and Branch-and-Cut strengthened by MCI")
    frame = run_all_comparisons(
        instance_dir="data/generated_instances",
        time_limit=args.time_limit,
    )
    print("\n" + frame.to_string(index=False))
    logging.info("All outputs are available under results/")


if __name__ == "__main__":
    main()
