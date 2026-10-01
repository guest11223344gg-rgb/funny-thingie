#!/usr/bin/env python3
"""Local dev server for the browser target.

Sets the cross-origin isolation headers that SharedArrayBuffer requires,
and serves .wasm with the correct MIME type. Localhost only — this
deliberately has no bind option, because the served content includes
locally built binaries and, in later milestones, licensed assets.

Usage: python tools/serve.py [port] [root]
"""
import http.server
import socketserver
import sys
from functools import partial

DEFAULT_PORT = 8080
DEFAULT_ROOT = "build/web"


class DevServer(socketserver.TCPServer):
    # http.server.HTTPServer sets this, but bare socketserver.TCPServer leaves
    # it False. Without it a restart fails with "address already in use" while
    # the previous socket lingers in TIME_WAIT, which bites anyone running the
    # test suite repeatedly. Bind stays loopback-only in main().
    allow_reuse_address = True


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
    }

    def end_headers(self):
        # Cross-origin isolation: required for SharedArrayBuffer, which
        # pthreads depend on. Removing these breaks threading at runtime.
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        # Never cache during development; stale wasm is a confusing failure.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    root = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ROOT
    handler = partial(Handler, directory=root)
    with DevServer(("127.0.0.1", port), handler) as httpd:
        print(f"serving {root} at http://localhost:{port}/ (COOP/COEP on)")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
