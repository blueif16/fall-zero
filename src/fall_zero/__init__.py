import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="fall-zero")
    sub = parser.add_subparsers(dest="cmd", required=True)
    smoke = sub.add_parser("smoke", help="call every configured service once")
    smoke.add_argument("checks", nargs="*", help="subset of checks to run (default: all)")
    analyze = sub.add_parser("analyze", help="photo or video -> tip-over verdicts, fixes and videos")
    analyze.add_argument("media", help="photo or video of the room")
    analyze.add_argument("--no-video", action="store_true", help="verdicts and fixes only")
    serve = sub.add_parser("serve", help="run the chat web app and its HTTP API")
    serve.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()

    if args.cmd == "smoke":
        from fall_zero.smoke import run

        sys.exit(run(args.checks))
    if args.cmd == "analyze":
        from pathlib import Path

        from fall_zero.analyze import analyze

        analyze(Path(args.media), video=not args.no_video)
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("fall_zero.server:app", port=args.port, reload=True)
