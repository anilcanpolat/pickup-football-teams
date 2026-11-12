"""Tiny storage API for anilcanpolat.com/football.

GET /football/api/data/<name>  -> saved JSON for that name (404 if none)
PUT /football/api/data/<name>  -> save JSON for that name
GET /football/api/health       -> {"ok": true}

One JSON file per name in DATA_DIR. Before each overwrite the previous file is
kept in DATA_DIR/versions/<name>/ (at most one copy per 10 minutes, last 50 kept),
so an accidental overwrite can be restored by hand.
Only the Python standard library is used.
"""
import json
import os
import re
import shutil
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

DATA = os.environ.get("DATA_DIR", "/data")
MAX_BODY = 256 * 1024          # bytes per save
MAX_NAMES = 200                # total distinct names
KEEP_VERSIONS = 50
VERSION_EVERY = 600            # seconds between kept versions
TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
PATH_RE = re.compile(r"/football/api/data/([^/?#]+)")


def slug(name):
    name = unicodedata.normalize("NFKD", name.translate(TR)).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return name if 2 <= len(name) <= 32 else None


class Handler(BaseHTTPRequestHandler):
    server_version = "football-api"
    sys_version = ""

    def send(self, code, body=b"{}"):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def name(self):
        m = PATH_RE.fullmatch(self.path.split("?")[0])
        return slug(unquote(m.group(1))) if m else None

    def do_GET(self):
        if self.path.split("?")[0] == "/football/api/health":
            return self.send(200, b'{"ok":true}')
        s = self.name()
        if not s:
            return self.send(400, b'{"error":"bad name"}')
        path = os.path.join(DATA, s + ".json")
        if not os.path.isfile(path):
            return self.send(404, b'{"error":"not found"}')
        with open(path, "rb") as f:
            self.send(200, f.read())

    def do_PUT(self):
        s = self.name()
        if not s:
            return self.send(400, b'{"error":"bad name"}')
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            return self.send(413, b'{"error":"too large"}')
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            if not isinstance(data, dict) or not isinstance(data.get("players"), list):
                raise ValueError
        except ValueError:
            return self.send(400, b'{"error":"bad json"}')

        path = os.path.join(DATA, s + ".json")
        if not os.path.isfile(path):
            existing = [f for f in os.listdir(DATA) if f.endswith(".json")]
            if len(existing) >= MAX_NAMES:
                return self.send(507, b'{"error":"storage full"}')
        else:
            keep_version(s, path)

        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        os.replace(tmp, path)
        self.send(200, b'{"ok":true}')

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args), flush=True)


def keep_version(s, path):
    vdir = os.path.join(DATA, "versions", s)
    os.makedirs(vdir, exist_ok=True)
    versions = sorted(os.listdir(vdir))
    if versions and time.time() - os.path.getmtime(os.path.join(vdir, versions[-1])) < VERSION_EVERY:
        return
    shutil.copy2(path, os.path.join(vdir, time.strftime("%Y%m%d-%H%M%S") + ".json"))
    for old in sorted(os.listdir(vdir))[:-KEEP_VERSIONS]:
        os.remove(os.path.join(vdir, old))


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    print("football-api listening on :8000, data in", DATA, flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
