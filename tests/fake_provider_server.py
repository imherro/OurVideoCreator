"""Loopback-only OpenAI-compatible fake used by P1 process tests."""
from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    server_version = 'OVCTestProvider/1'

    def log_message(self, _format, *_args):
        return

    def do_POST(self):
        if self.path != '/v1/chat/completions':
            self.send_error(404)
            return
        length = int(self.headers.get('content-length', '0'))
        body = json.loads(self.rfile.read(length) or b'{}')
        if body.get('model') != 'p1-fake-model':
            self.send_error(400, 'unexpected model')
            return
        count_path: Path = self.server.count_path
        count = int(count_path.read_text(encoding='utf-8') or '0') if count_path.exists() else 0
        count_path.write_text(str(count + 1), encoding='utf-8')
        time.sleep(self.server.delay)
        content = (
            'data: '+json.dumps({'choices':[{'delta':{'content':'P1 fake response'}}]})+
            '\n\ndata: [DONE]\n\n'
        ).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--count-file', type=Path, required=True)
    parser.add_argument('--delay', type=float, default=1.0)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.count_path = args.count_file
    server.delay = args.delay
    server.serve_forever()


if __name__ == '__main__':
    main()
