from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .converter import convert_mod, prepare_mod


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and convert Transport Fever mod metadata safely.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("convert", "inspect"):
        sub = commands.add_parser(command, help=f"{command.capitalize()} a mod folder or metadata file")
        sub.add_argument("source", help="Mod directory or JSON/Lua metadata file")
        if command == "convert":
            sub.add_argument("destination", help="Separate output directory")
            sub.add_argument("--overwrite", action="store_true", help="Replace existing output, retaining it in a backup folder")
        sub.add_argument("--name", help="Display name override (32 characters maximum)")
        sub.add_argument("--author", help="Author override; omit to preserve all original authors")
        sub.add_argument("--mod-id", help="Mod id override (lowercase letters, digits, underscores)")
        sub.add_argument("--revision", type=int, help="Non-negative revision override")
        sub.add_argument("--summary", help="Summary override (100 characters maximum)")
    commands.add_parser("gui", help="Open the desktop app")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "gui":
        from .gui import main as open_gui
        open_gui()
        return 0
    overrides = {key: getattr(args, key) for key in ("name", "author", "mod_id", "revision", "summary")}
    try:
        if args.command == "inspect":
            descriptor = prepare_mod(args.source, **overrides)
            print(json.dumps(descriptor.as_inspection(), ensure_ascii=False, indent=4))
            return 2 if descriptor.blockers else 0
        result = convert_mod(args.source, args.destination, overwrite=args.overwrite, **overrides)
        print(json.dumps(result, ensure_ascii=False, indent=4))
        return 0
    except (OSError, ValueError, RecursionError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

