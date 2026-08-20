"""Minimaler API-Stub fuer tests/test_resume.sh.

Nimmt PATCH /games/<id> an, antwortet 200 und schreibt alle Aufrufe als JSON in
die als zweites Argument uebergebene Datei, damit der Test sie pruefen kann.

@example
python3 tests/fake_api.py 8977 /tmp/calls.json
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

CALLS = []


class Handler(BaseHTTPRequestHandler):
    def do_PATCH(self):
        length = int(self.headers.get("Content-Length") or 0)
        CALLS.append({"path": self.path,
                      "body": json.loads(self.rfile.read(length) or "{}")})
        with open(sys.argv[2], "w") as f:
            json.dump(CALLS, f)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"code":200,"data":{}}')

    def log_message(self, *_args):
        pass          # kein Request-Logging im Test


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
