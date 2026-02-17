from __future__ import annotations

import argparse
import json

from app.ml_uplift.model import train_uplift_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Google traffic uplift model")
    parser.add_argument("--samples-path", type=str, default=None, help="Optional path to uplift samples CSV")
    parser.add_argument("--min-rows", type=int, default=120, help="Minimum rows required for training")
    args = parser.parse_args()

    result = train_uplift_model(samples_path=args.samples_path, min_rows=max(12, int(args.min_rows)))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

