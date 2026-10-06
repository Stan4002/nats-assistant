import argparse
import json
import sys
from typing import Sequence

from pydantic import ValidationError


def main(argv: Sequence[str] | None = None) -> int:
    tokens = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="nats-assistant")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("quick", help="Existing task/capture quick entry", add_help=False)
    commands.add_parser("serve", help="Run the local NATS API server")
    config = commands.add_parser("config", help="Persistent user settings")
    config_actions = config.add_subparsers(dest="action", required=True)
    config_actions.add_parser("show", help="Show effective non-secret settings")
    get = config_actions.add_parser("get", help="Read an effective setting")
    get.add_argument("key")
    set_value = config_actions.add_parser("set", help="Validate and persist a setting")
    set_value.add_argument("key")
    set_value.add_argument("value")
    service = commands.add_parser("service", help="Manage the systemd user service")
    from nats_assistant.service import SERVICE_ACTIONS

    service.add_argument("action", choices=sorted(SERVICE_ACTIONS))
    calendar = commands.add_parser("calendar", help="Calendar provider setup")
    providers = calendar.add_subparsers(dest="provider", required=True)
    google = providers.add_parser("google", help="Google Calendar setup")
    actions = google.add_subparsers(dest="action", required=True)
    actions.add_parser("auth", help="Authorize read-only Calendar access in your browser")
    if not tokens or tokens[0] not in {"calendar", "serve", "config", "service", "--help", "-h"}:
        from nats_assistant.quick_entry import main as quick_entry_main

        return quick_entry_main(tokens)
    args = parser.parse_args(tokens)

    from nats_assistant.config import CONFIG_KEYS, get_settings, set_config_value
    from nats_assistant.providers.google_calendar import GoogleAuthSetupError, authenticate_google_calendar
    from nats_assistant.service import ServiceError, manage_service

    try:
        if args.command == "serve":
            from nats_assistant.runtime import serve

            serve()
            return 0
        if args.command == "service":
            return manage_service(args.action)
        if args.command == "config":
            if args.action != "show" and args.key not in CONFIG_KEYS:
                print("Unsupported configuration key", file=sys.stderr)
                return 1
            if args.action == "set":
                path = set_config_value(args.key, args.value)
                print(f"Saved {args.key} in {path}. Restart NATS to apply changes to the running service.")
            else:
                values = get_settings().model_dump(mode="json")
                if args.action == "show":
                    print(json.dumps({key: values[key] for key in sorted(CONFIG_KEYS)}, indent=2))
                else:
                    value = values[args.key]
                    print(json.dumps(value) if isinstance(value, (bool, int, float)) else value)
            return 0
        path = authenticate_google_calendar(get_settings())
    except GoogleAuthSetupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except ServiceError as error:
        print(str(error), file=sys.stderr)
        return 1
    except ValidationError:
        print("Invalid NATS configuration; check known setting values in config.toml and NATS_ overrides", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Unable to use NATS configuration or service files; check settings, syntax and permissions", file=sys.stderr)
        return 1
    print(f"Google Calendar authorized. Token stored at {path}")
    return 0
