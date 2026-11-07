"""CLI: analyze on-disk Python sources without executing them."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .scanner import ScanError, analyze_directory, as_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dependency-atlas", description="Visualize Python import architecture without running the project")
    cmd = parser.add_subparsers(dest="command", required=True)
    analyze = cmd.add_parser("analyze", help="Scan a directory and print/export a JSON report")
    analyze.add_argument("directory", help="Local Python project directory")
    analyze.add_argument("--output", "-o", type=Path, help="Write new JSON report file (never overwrites)")
    analyze.add_argument("--fail-on-cycles", action="store_true", help="Exit with code 2 if cycles exist")
    check = cmd.add_parser("check", help="CI-friendly check for dependency cycles and parse errors")
    check.add_argument("directory")
    serve = cmd.add_parser("serve", help="Launch the local browser dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn
        uvicorn.run("dependency_atlas.api:app", host=args.host, port=args.port)
        return 0
    try:
        report = analyze_directory(args.directory)
        if args.command == "analyze":
            if args.output:
                # Exclusive create avoids overwriting existing user data and follows Python file safety conventions.
                with args.output.open("x", encoding="utf-8") as file:
                    file.write(as_json(report))
                print(f"Report saved: {args.output}")
            else:
                print(as_json(report), end="")
            return 2 if args.fail_on_cycles and report["summary"]["cycles_found"] else 0
        print(f"Modules: {report['summary']['total_modules']} | Edges: {report['summary']['total_edges']} | Cycles: {report['summary']['cycles_found']} | Parse errors: {report['summary']['parse_errors']}")
        return 2 if report["summary"]["cycles_found"] or report["summary"]["parse_errors"] else 0
    except (ScanError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
