"""Command line entry point: ``python -m hydro serve``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hydro.console.controller import Controller
from hydro.console.server import ControlServer


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hydro", description="Line control service")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="start the HTTP console")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--data", default="data")
    serve.add_argument("--no-seed", action="store_true")

    seed = sub.add_parser("seed", help="seed a data directory and exit")
    seed.add_argument("--data", default="data")

    routes = sub.add_parser("routes", help="print the route table")
    routes.add_argument("--data", default="data")
    return parser


def _controller(data: str) -> Controller:
    return Controller(Path(data))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command or "serve"

    if command == "routes":
        controller = _controller(getattr(args, "data", "data"))
        print(json.dumps(controller.router.routes(), ensure_ascii=False, indent=2))
        return 0

    if command == "seed":
        controller = _controller(args.data)
        print(json.dumps(controller.seed(), ensure_ascii=False))
        return 0

    controller = _controller(getattr(args, "data", "data"))
    if not args.no_seed:
        controller.seed()
    server = ControlServer(args.host, args.port, controller)
    host, port = server.address
    print("unit control console listening on http://{}:{}/api/health".format(host, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
