#!/usr/bin/env python3
"""CLI utility to generate reproducible synthetic retail datasets."""

import argparse
import csv
import os
import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, backend_path)

from app.data.synthetic.generator import RetailDataGenerator


def write_csv(filepath: Path, records: list) -> None:
    """Write list of dictionaries to a CSV file."""
    if not records:
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(records[0].keys())
    with open(filepath, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate deterministic synthetic retail dataset for NEXUS.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--seed", type=int, default=42, help="Random number generator seed")
    parser.add_argument("--customers", type=int, default=800, help="Number of customer entities to generate")
    parser.add_argument("--products", type=int, default=150, help="Number of product SKUs to generate")
    parser.add_argument("--sales", type=int, default=3500, help="Number of sale transactions to generate")
    parser.add_argument("--months", type=int, default=18, help="Months of historical transaction depth")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/sample",
        help="Target folder for generated CSV exports",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("NEXUS -- Synthetic Retail Data Generator")
    print("=" * 60)
    print(f"Seed: {args.seed} | Months: {args.months}")
    print(f"Targeting: {args.customers} customers, {args.products} products, {args.sales} sales")

    generator = RetailDataGenerator(seed=args.seed)
    data = generator.generate(
        num_customers=args.customers,
        num_products=args.products,
        num_sales=args.sales,
        months_history=args.months,
    )

    out_dir = Path(args.output_dir)
    print(f"\n[INFO] Writing CSV outputs to {out_dir.resolve()}...")

    for name, records in data.items():
        file_path = out_dir / f"{name}.csv"
        write_csv(file_path, records)
        print(f"  -> Generated {len(records):>6} rows: {file_path.name}")

    print("\n[OK] Synthetic generation complete.")


if __name__ == "__main__":
    main()
