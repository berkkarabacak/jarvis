"""Local watch page for Jarvis's Android box (ORCH-461).

Equivalent of Linux noVNC: Berk can watch the live screen.
Binds localhost inside the sidecar; compose publishes 127.0.0.1:6081.
No keys. No Play Store client.

Public HTML must use /android/stream.mjpeg — never /stream.mjpeg
(site root) and never http://127.0.0.1. nginx strips the prefix when it
proxies here, so this process still serves /stream.mjpeg internally.
"""

from __future__ import annotations

import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ADB = os.environ.get("ANDROID_ADB") or "jarvis-android:5555"
PUBLIC_PREFIX = "/android"
LEGACY_PREFIX = "/jarvis/android"
STREAM_PUBLIC = PUBLIC_PREFIX + "/stream.mjpeg"
HEALTH_PUBLIC = PUBLIC_PREFIX + "/health"
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <base href="/android/">
  <title>Jarvis's screen</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { height: 100%; background: #0d0f12; color: #f4f6f8; }
    body { font: 15px/1.4 system-ui, sans-serif; }
    img { width: 100%; height: 100%; object-fit: contain; background: #000; }
    img.is-hidden { display: none; }
    .lead { position: absolute; inset: 0; display: none; align-items: center;
            justify-content: center; padding: 28px; text-align: center; }
    .lead.is-open { display: flex; }
  </style>
</head>
<body>
  <p id="still" class="lead is-open">The Android screen is not live yet.</p>
  <img id="screen" alt="Jarvis's Android screen" class="is-hidden">
  <noscript>
    <img src="/android/stream.mjpeg" alt="Jarvis's Android screen">
  </noscript>
  <script>
    (function () {
      var still = document.getElementById("still");
      var screen = document.getElementById("screen");
      var STREAM = "/android/stream.mjpeg";
      var STREAM_REL = "stream.mjpeg";
      var HEALTH = "/android/health";
      var usedRelative = false;
      var timer = null;
      function arm() {
        if (timer) clearTimeout(timer);
        timer = setTimeout(tick, 4000);
      }
      function showStill() {
        screen.removeAttribute("src");
        screen.classList.add("is-hidden");
        still.classList.add("is-open");
        arm();
      }
      function showLive(src) {
        if (timer) clearTimeout(timer);
        still.classList.remove("is-open");
        screen.classList.remove("is-hidden");
        if (screen.getAttribute("src") !== src) screen.setAttribute("src", src);
      }
      function tick() {
        fetch(HEALTH, { cache: "no-store", credentials: "same-origin" })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data && data.live) showLive(STREAM);
            else showStill();
          })
          .catch(function () { showStill(); });
      }
      screen.addEventListener("error", function () {
        if (!usedRelative) {
          usedRelative = true;
          showLive(STREAM_REL);
          return;
        }
        showStill();
      });
      tick();
    })();
  </script>
</body>
</html>
"""

PAGE_PATHS = {
    "/",
    "/index.html",
    "/vnc.html",
    PUBLIC_PREFIX,
    PUBLIC_PREFIX + "/",
    PUBLIC_PREFIX + "/index.html",
    PUBLIC_PREFIX + "/vnc.html",
    LEGACY_PREFIX,
    LEGACY_PREFIX + "/",
    LEGACY_PREFIX + "/index.html",
    LEGACY_PREFIX + "/vnc.html",
}
HEALTH_PATHS = {
    "/health",
    "/status",
    HEALTH_PUBLIC,
    PUBLIC_PREFIX + "/status",
    LEGACY_PREFIX + "/health",
    LEGACY_PREFIX + "/status",
}
STREAM_PATHS = {
    "/stream.mjpeg",
    STREAM_PUBLIC,
    LEGACY_PREFIX + "/stream.mjpeg",
}


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


def _health_payload(live: bool) -> bytes:
    return (
        b'{"ok":true,"kind":"android","live":'
        + (b"true" if live else b"false")
        + b',"play_store_client":false}'
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in PAGE_PATHS:
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path in HEALTH_PATHS:
            png = _screencap()
            payload = _health_payload(bool(png))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        if path in STREAM_PATHS:
            png = _screencap()
            if not png:
                payload = b"Android screen is not live"
                self.send_response(503)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    if png:
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/png\r\nContent-Length: "
                            + str(len(png)).encode("ascii")
                            + b"\r\n\r\n"
                            + png
                            + b"\r\n"
                        )
                    png = _screencap()
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
