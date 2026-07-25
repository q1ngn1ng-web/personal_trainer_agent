from __future__ import annotations

import argparse
import logging

from src.db.sqlite import init_db

logger = logging.getLogger("src.db.cli")


def main() -> None:
    """Run the trainer command-line interface."""
    parser = argparse.ArgumentParser(prog="trainer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="Create SQLite database with all tables")
    args = parser.parse_args()
    if args.cmd == "init-db":
        init_db()
        print("✅ Database initialized")


if __name__ == "__main__":
    main()
