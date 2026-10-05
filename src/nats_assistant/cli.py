import argparse
import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    tokens = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="nats-assistant")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("quick", help="Existing task/capture quick entry", add_help=False)
    calendar = commands.add_parser("calendar", help="Calendar provider setup")
    providers = calendar.add_subparsers(dest="provider", required=True)
    google = providers.add_parser("google", help="Google Calendar setup")
    actions = google.add_subparsers(dest="action", required=True)
    actions.add_parser("auth", help="Authorize read-only Calendar access in your browser")
    if not tokens or tokens[0] not in {"calendar", "--help", "-h"}:
        from nats_assistant.quick_entry import main as quick_entry_main

        return quick_entry_main(tokens)
    parser.parse_args(tokens)

    from nats_assistant.config import get_settings
    from nats_assistant.providers.google_calendar import GoogleAuthSetupError, authenticate_google_calendar

    try:
        path = authenticate_google_calendar(get_settings())
    except GoogleAuthSetupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Invalid calendar configuration; check Google auth file paths and NATS_ settings", file=sys.stderr)
        return 1
    print(f"Google Calendar authorized. Token stored at {path}")
    return 0
