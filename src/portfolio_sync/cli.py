from __future__ import annotations

import argparse

from portfolio_sync.apply_changes import run_apply
from portfolio_sync.config import load_apply_config, load_reconcile_config, load_review_config
from portfolio_sync.reconcile import run_reconcile
from portfolio_sync.review import run_review


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portfolio-sync")
    top_level = parser.add_subparsers(dest="command", required=True)

    review_parser = top_level.add_parser("review", help="Review work Notion pages and write recommendations.")
    review_commands = review_parser.add_subparsers(dest="review_command", required=True)
    review_sync = review_commands.add_parser("sync", help="Run a review sync.")
    review_sync.add_argument("--mode", choices=["bootstrap", "incremental"], required=True)

    apply_parser = top_level.add_parser("apply", help="Apply approved Notion recommendations.")
    apply_commands = apply_parser.add_subparsers(dest="apply_command", required=True)
    apply_sync = apply_commands.add_parser("sync", help="Run the apply sync.")
    apply_sync.add_argument("--mode", choices=["approved"], required=True)

    reconcile_parser = top_level.add_parser(
        "reconcile", help="Review approved portfolio candidates against live portfolio pages."
    )
    reconcile_commands = reconcile_parser.add_subparsers(dest="reconcile_command", required=True)
    reconcile_sync = reconcile_commands.add_parser("sync", help="Run the reconciliation sync.")
    reconcile_sync.add_argument("--mode", choices=["approved"], required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "review" and args.review_command == "sync":
        run_review(args.mode, load_review_config())
        return 0

    if args.command == "apply" and args.apply_command == "sync":
        run_apply(args.mode, load_apply_config())
        return 0

    if args.command == "reconcile" and args.reconcile_command == "sync":
        run_reconcile(args.mode, load_reconcile_config())
        return 0

    parser.error("Unknown command")
    return 2
