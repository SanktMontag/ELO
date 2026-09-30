
#!/usr/bin/env python3
"""
Standalone script to build a Goal Difference (GD) model from historical match data.

Reads a CSV with two columns:
    - GD        : Goal difference for each match
    - ELO Delta : Elo rating difference between the two teams

Outputs a JSON file mapping Elo-delta bins (50-point increments) to
the mean and standard deviation of goal differences observed in that bin.

Usage:
    python build_gd_model.py input.csv [--output gd_model.json] [--min-samples 3]
"""

import argparse
import json
import sys
from collections import defaultdict

import numpy as np
import pandas as pd


def build_gd_model(
    df: pd.DataFrame,
    min_samples_per_bin: int = 3,
) -> dict:
    """
    Bin historical results by Elo delta (50-point increments) and compute
    the mean / std of goal differences for each bin.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns 'GD' (int/float) and 'ELO Delta' (int/float).
    min_samples_per_bin : int
        Minimum matches in a bin to include it in the model.

    Returns
    -------
    dict
        {bin_key: {"mean": float, "std": float, "n": int}, ...}
    """
    gd_bins: dict[int, list[float]] = defaultdict(list)

    for _, row in df.iterrows():
        bin_key = round(row["ELO Delta"] / 50) * 50
        gd_bins[bin_key].append(row["GD"])

    gd_model = {}
    for bin_key, gd_values in sorted(gd_bins.items()):
        if len(gd_values) >= min_samples_per_bin:
            gd_model[int(bin_key)] = {
                "mean": float(np.mean(gd_values)),
                "std": float(max(np.std(gd_values), 0.5)),  # Floor at 0.5
                "n": len(gd_values),
            }

    return gd_model


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a GD model from a CSV of match results."
    )
    parser.add_argument(
        "input_csv",
        help="Path to the input CSV (columns: GD, ELO Delta)",
    )
    parser.add_argument(
        "--output", "-o",
        default="gd_model.json",
        help="Path for the output JSON file (default: gd_model.json)",
    )
    parser.add_argument(
        "--min-samples", "-m",
        type=int,
        default=3,
        help="Minimum samples per bin to include (default: 3)",
    )
    args = parser.parse_args()

    # --- Load CSV ---
    try:
        df = pd.read_csv(args.input_csv)
    except FileNotFoundError:
        sys.exit(f"Error: file '{args.input_csv}' not found.")

    required_cols = {"GD", "ELO Delta"}
    missing = required_cols - set(df.columns)
    if missing:
        sys.exit(
            f"Error: CSV is missing required column(s): {', '.join(missing)}. "
            f"Found columns: {list(df.columns)}"
        )

    if len(df) < 50:
        sys.exit(
            f"Error: only {len(df)} rows found. "
            "At least 50 matches are required to build a reliable model."
        )

    # --- Build model ---
    gd_model = build_gd_model(df, min_samples_per_bin=args.min_samples)

    if not gd_model:
        sys.exit("Error: no bins met the minimum-sample threshold.")

    # --- Write output ---
    with open(args.output, "w") as f:
        json.dump(gd_model, f, indent=2)

    # --- Summary ---
    print(f"Model built from {len(df):,} matches.")
    print(f"Bins retained: {len(gd_model)} (min {args.min_samples} samples each)")
    print(f"Elo delta range: [{min(gd_model):+d}, {max(gd_model):+d}]")
    print(f"Output written to: {args.output}")


if __name__ == "__main__":
    main()