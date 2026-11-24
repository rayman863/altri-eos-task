"""Seed loader: `python -m app.seed [--reset]`.

Phase 0 stub. Phase 2 loads seed/seed.json idempotently (ON CONFLICT DO NOTHING by
seed id); --reset truncates first (tests only).
"""

import argparse
import logging

from app.config import get_settings
from app.logging import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Load seed/seed.json into the database.")
    parser.add_argument("--reset", action="store_true", help="truncate app tables first")
    args = parser.parse_args()
    setup_logging(get_settings().log_level)
    logging.getLogger("eos.seed").info(
        "seed: nothing to load yet (schema arrives in Phase 2)", extra={"reset": args.reset}
    )


if __name__ == "__main__":
    main()
