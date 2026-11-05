import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

from .trace import CaptureError, analyze, compare


ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Explain QNX 8.0 deadline captures")
    sub = parser.add_subparsers(dest="command")
    single = sub.add_parser("analyze", help="Read one traceprinter export")
    single.add_argument("trace", type=Path)
    single.add_argument("-o", "--output", type=Path, required=True)
    pair = sub.add_parser("compare", help="Export a reproducible comparison")
    pair.add_argument("fault", type=Path)
    pair.add_argument("fixed", type=Path)
    pair.add_argument("-o", "--output", type=Path, required=True)
    server = sub.add_parser("serve", help="Open the local browser timeline")
    server.add_argument("--fault", type=Path, default=ROOT / "captures/fault.trace")
    server.add_argument("--fixed", type=Path, default=ROOT / "captures/fixed.trace")
    server.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command is None:
        args = parser.parse_args(["serve"])
    try:
        if args.command == "analyze":
            report = analyze(args.trace)
        else:
            report = compare(analyze(args.fault), analyze(args.fixed))
        if args.command != "serve":
            args.output.write_text(json.dumps(report, indent=2) + "\n")
            print(f"Saved {args.output}")
            return
    except (CaptureError, OSError, UnicodeError, KeyError, TypeError) as error:
        parser.exit(1, f"Capture could not be read: {error}\n")
    payload = json.dumps(report, separators=(",", ":")).encode()
    assets = {"/": (ROOT / "web/index.html", "text/html; charset=utf-8"),
              "/app.js": (ROOT / "web/app.js", "text/javascript; charset=utf-8"),
              "/style.css": (ROOT / "web/style.css", "text/css; charset=utf-8")}
    for mode in ("fault", "fixed"):
        trace = getattr(args, mode).resolve()
        assets[f"/sources/{mode}.trace"] = (trace, "text/plain; charset=utf-8")
        if trace.with_suffix(".kev").is_file():
            assets[f"/sources/{mode}.kev"] = (trace.with_suffix(".kev"), "application/octet-stream")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/report.json":
                data, mime = payload, "application/json"
            elif path in assets:
                source, mime = assets[path]
                data = source.read_bytes()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    print(f"Timeline: http://127.0.0.1:{args.port}", flush=True)
    print("QEMU guest timings. Press Ctrl+C to stop.", flush=True)
    try:
        with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    except OSError as error:
        print(f"Server could not start: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
