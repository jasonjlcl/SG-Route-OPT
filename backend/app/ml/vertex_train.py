from __future__ import annotations

import argparse
import json

from app.services.ml_ops import train_and_register_model
from app.utils.db import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and register route-time model with Vertex integration enabled")
    parser.add_argument("--input", required=False, help="Path to historical CSV (optional if using actual_travel_times table)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = train_and_register_model(
            db,
            dataset_path=args.input,
            force_vertex=True,
        )
    finally:
        db.close()

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
