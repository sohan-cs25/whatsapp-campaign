"""
Stand-in for the 360dialog API during local end-to-end tests.

Every POST is saved as JSON in the outbox folder and answered the way 360dialog answers a
successful send, so orders move to 'sent' without a real WhatsApp message going out.

    python -m e2e.fake_whatsapp --port 8999 --outbox e2e/.data/whatsapp_outbox
"""

import argparse
import itertools
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_server(host: str, port: int, outbox: Path) -> ThreadingHTTPServer:
    outbox.mkdir(parents=True, exist_ok=True)
    counter = itertools.count(len(list(outbox.glob("*.json"))) + 1)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                payload = json.loads(body or b"{}")
            except ValueError:
                return self._reply(400, {"error": "body is not JSON"})
            n = next(counter)
            to = str(payload.get("to", "unknown"))
            (outbox / f"{n:04d}-{to}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
            print(f"[fake-whatsapp] #{n} {self.path} to {to}", flush=True)
            self._reply(200, {"messaging_product": "whatsapp", "contacts": [{"input": to, "wa_id": to}],
                              "messages": [{"id": f"wamid.e2e-{n:04d}"}]})

        def _reply(self, code, data):
            raw = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8999)
    ap.add_argument("--outbox", type=Path, default=Path("e2e/.data/whatsapp_outbox"))
    a = ap.parse_args()
    print(f"[fake-whatsapp] listening on http://{a.host}:{a.port}, saving to {a.outbox}", flush=True)
    make_server(a.host, a.port, a.outbox).serve_forever()
