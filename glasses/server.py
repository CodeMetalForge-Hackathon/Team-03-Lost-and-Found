"""
Tiny bridge: serves the glasses web app and relays sensor results to it.

  GET  /          -> index.html (the glasses UI)
  GET  /target    -> latest target JSON (the glasses poll this)
  POST /update    -> sensor code posts the latest target JSON here

Run:   python3 server.py
Then:  ngrok http 8000    (gives a public https URL for the Meta AI app)

Example update from a terminal or your sensor script:
  curl -X POST localhost:8000/update -H "Content-Type: application/json" \
       -d '{"bearing": 75, "distance": 42, "label": "Person A", "confidence": 0.8}'
"""
import json
import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

PORT = int(os.environ.get("PORT", 8000))
ROOT = os.path.dirname(os.path.abspath(__file__))
latest = {}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def end_headers(self):
        self._cors()
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/target":
            body = json.dumps(latest).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def do_POST(self):
        global latest
        if self.path.split("?")[0] != "/update":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", 0))
        try:
            latest = json.loads(self.rfile.read(n) or b"{}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            print("target ->", latest)
        except json.JSONDecodeError:
            self.send_error(400, "bad json")

    def log_message(self, *args):
        pass  # keep the console quiet


if __name__ == "__main__":
    print(f"Serving on http://localhost:{PORT}  (glasses UI at /, data at /target)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
