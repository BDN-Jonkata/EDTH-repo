"""Serve the viewer with caching disabled, so a refresh always shows the latest files.

    python serve.py          # http://localhost:8000
    python serve.py 8080     # another port
"""
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print("Viewer at http://localhost:%d  (Ctrl+C to stop)" % port)
    ThreadingHTTPServer(("", port), NoCacheHandler).serve_forever()
