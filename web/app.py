"""havefun 网页刷题本地服务（标准库实现，无第三方依赖）。

启动：  python3 web/app.py  [--port 8000]
访问：  http://localhost:8000/

提供：做题（解析题库->网页作答->自动判分->回写文档）、监控（统计与薄弱点）。
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import lib
from ai_grader import grade as ai_grade

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
INDEX_PATH = WEB_DIR / "templates" / "index.html"


def _send_json(handler, obj, status=200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_file(handler, path: Path, ctype: str):
    if not path.exists():
        handler.send_error(404)
        return
    body = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 静默日志，避免刷屏

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            _send_file(self, INDEX_PATH, CTYPES[".html"])
            return
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            _send_file(self, STATIC_DIR / rel, CTYPES.get(Path(rel).suffix, "application/octet-stream"))
            return
        if path == "/api/subjects":
            _send_json(self, {"sets": lib.discover_sets()})
            return
        if path == "/api/quiz":
            q = urllib.parse.parse_qs(parsed.query)
            subject = q.get("subject", [""])[0]
            sett = q.get("set", [""])[0]
            s = lib.load_set(subject, sett)
            # 不下发答案键，判分在服务端进行
            questions = [
                {
                    "id": qd["id"],
                    "index": qd["index"],
                    "type": qd["type"],
                    "difficulty": qd["difficulty"],
                    "stem": qd["stem"],
                    "options": qd["options"],
                }
                for qd in s["questions"]
            ]
            _send_json(self, {"subject": subject, "set": sett, "questions": questions})
            return
        if path == "/api/dashboard":
            _send_json(self, lib.compute_dashboard())
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/submit":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {}
        subject = payload.get("subject", "")
        sett = payload.get("set", "")
        answers = payload.get("answers", {})

        s = lib.load_set(subject, sett)
        if not s["questions"]:
            _send_json(self, {"error": "未找到该套题或题目为空"}, status=400)
            return

        graded = lib.grade_submission(s, answers, ai=ai_grade)
        lib.write_back(s, graded)

        # 记录到 results.json 供监控
        summary = graded["summary"]
        lib.append_attempt(
            {
                "ts": summary["ts"],
                "subject": subject,
                "set": sett,
                "total": summary["total"],
                "correct": summary["correct"],
                "pending": summary["pending"],
                "wrong_ids": summary["wrong_ids"],
            }
        )

        _send_json(self, graded)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(__import__("os").environ.get("PORT", "8000")))
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"havefun 网页刷题已启动： http://localhost:{args.port}/")
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
