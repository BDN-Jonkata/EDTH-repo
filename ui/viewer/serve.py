"""Serve the viewer with caching disabled, plus a small scenario API backed by the seeder.

    python serve.py          # http://localhost:8000
    python serve.py 8080     # another port

API (JSON):
    GET /api/presets                         the presets in scenarios/ with their default seeds
    GET /api/scenario?preset=hard&seed=7     a freshly generated scenario (no ground truth)
"""
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "seeder"))

import scenario as sc  # noqa: E402


def presets():
    out = []
    for path in sorted((ROOT / "scenarios").glob("*.json")):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        out.append({"id": path.stem, "name": cfg.get("name", path.stem), "description": cfg.get("description", ""), "seed": cfg.get("seed", 1)})
    return out


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/presets":
            return self.send_json(200, presets())
        if url.path == "/api/scenario":
            q = parse_qs(url.query)
            name = (q.get("preset") or ["challenge"])[0]
            path = ROOT / "scenarios" / (Path(name).name + ".json")  # no path tricks: just a file name
            if not path.exists():
                return self.send_json(404, {"error": "unknown preset '%s'" % name})
            cfg = json.loads(path.read_text(encoding="utf-8"))
            if q.get("seed"):
                try:
                    cfg["seed"] = int(q["seed"][0])
                except ValueError:
                    return self.send_json(400, {"error": "seed must be an integer"})
                cfg["seed_set"] = None  # a hand-picked seed is not part of the tuning/test sets
            try:
                scenario, _ = sc.generate(cfg, truth_dt=1.0)
            except ValueError as e:
                return self.send_json(400, {"error": str(e)})
            return self.send_json(200, scenario)
        return super().do_GET()

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/"):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print("Viewer at http://localhost:%d  (Ctrl+C to stop)" % port)
    ThreadingHTTPServer(("", port), Handler).serve_forever()
