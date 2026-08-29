"""Local watch page for Jarvis's Android box (ORCH-461).

Equivalent of Linux noVNC: Berk can watch the live screen.
Binds localhost inside the sidecar; compose publishes 127.0.0.1:6081.
No keys. No Play Store client.
"""

from __future__ import annotations

import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ADB = os.environ.get("ANDROID_ADB") or "jarvis-android:5555"
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis's screen</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { height: 100%; background: #0d0f12; color: #f4f6f8; }
    body { font: 15px/1.4 system-ui, sans-serif; }
    img { width: 100%; height: 100%; object-fit: contain; background: #000; }
    .lead { position: absolute; inset: 0; display: flex; align-items: center;
            justify-content: center; padding: 28px; text-align: center; }
  </style>
</head>
<body>
  <img src="stream.mjpeg" alt="Jarvis's Android screen">
</body>
</html>
"""


def _adb(args: list[str], *, timeout: float = 8) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["adb", "connect", ADB] if args[:1] == ["connect"] else ["adb", "-s", ADB, *args],
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _screencap() -> bytes:
    try:
        _adb(["connect"], timeout=4)
    except Exception:
        pass
    try:
        completed = subprocess.run(
            ["adb", "-s", ADB, "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return b""
    raw = completed.stdout or b""
    return raw if raw.startswith(b"\x89PNG") else b""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {"/", "/index.html", "/vnc.html"}:
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path in {"/health", "/status"}:
            png = _screencap()
            payload = (
                b'{"ok":true,"kind":"android","live":'
                + (b"true" if png else b"false")
                + b',"play_store_client":false}'
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        if path in {"/stream.mjpeg", "/jarvis/android/stream.mjpeg"}:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    png = _screencap()
                    if png:
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/png\r\nContent-Length: "
                            + str(len(png)).encode("ascii")
                            + b"\r\n\r\n"
                            + png
                            + b"\r\n"
                        )
                    time.sleep(0.4)
            except BrokenPipeError:
                return
            return
        self.send_error(404)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 6081), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
