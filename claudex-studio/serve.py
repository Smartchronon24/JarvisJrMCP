#!/usr/bin/env python3
"""Small static file server for the Claudex Studio frontend shell.

This is intentionally minimal and separate from the runtime server in
app/runtime/server.py. B8 remains responsible for the WebSocket runtime
service; this helper only serves the browser shell for local debugging.
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format, *args):
        return


def main() -> None:
    parser = argparse.ArgumentParser(description='Serve Claudex Studio locally')
    parser.add_argument('--host', default='127.0.0.1', help='Host interface to bind to')
    parser.add_argument('--port', type=int, default=8000, help='Port to bind to')
    args = parser.parse_args()

    with socketserver.TCPServer((args.host, args.port), QuietHandler) as httpd:
        print(f'Serving Claudex Studio at http://{args.host}:{args.port}')
        httpd.serve_forever()


if __name__ == '__main__':
    main()
