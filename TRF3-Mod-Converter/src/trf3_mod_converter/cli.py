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
    analyze = commands.add_parser("analyze", help="Analyze all vehicle/mod categories and their TF3 migration requirements without exporting")
    analyze.add_argument("source", help="Mod directory; metadata is not required")
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
    port = commands.add_parser("port-tf2", help="Port supported TF2 electric locomotives to a separate TF3 draft")
    port.add_argument("source")
    port.add_argument("destination")
    port.add_argument("--tf3-game", required=True, help="Installed TF3 folder; native assets are referenced, never copied")
    port.add_argument("--name", required=True)
    port.add_argument("--mod-id", required=True)
    port.add_argument("--author")
    port.add_argument("--revision", type=int)
    port.add_argument("--summary")
    port.add_argument("--repairs", help="JSON object mapping unresolved TF2 texture references to explicit source replacements")
    port.add_argument("--overwrite", action="store_true")
    commands.add_parser("gui", help="Open the desktop app")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "gui":
        from .gui import main as open_gui
        open_gui()
        return 0
    try:
        if args.command == "analyze":
            from .conversion_plan import analyze_mod
            result = analyze_mod(args.source)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2 if result["status"] == "needs_review" else 0
        if args.command == "port-tf2":
            from pathlib import Path
            from .tf2_vehicle_port import port_tf2_mod
            repairs = json.loads(Path(args.repairs).read_text(encoding="utf-8")) if args.repairs else None
            if repairs is not None and (not isinstance(repairs, dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in repairs.items())):
                raise ValueError("Repairs must be a JSON object of source texture references and replacement paths")
            result = port_tf2_mod(args.source,args.destination,tf3_game=args.tf3_game,name=args.name,mod_id=args.mod_id,
                                  repairs=repairs,overwrite=args.overwrite,author=args.author,
                                  revision=args.revision,summary=args.summary)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0
        overrides = {key: getattr(args, key) for key in ("name", "author", "mod_id", "revision", "summary")}
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

