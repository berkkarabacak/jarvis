"""Public Android watch page uses the /android/ prefix, not site-root /stream.mjpeg."""

from __future__ import annotations

import importlib.util
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / "deploy" / "jarvis-android" / "watch" / "server.py"

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _load_watch():
    spec = importlib.util.spec_from_file_location("jarvis_android_watch", WATCH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def watch_mod():
    return _load_watch()


@pytest.fixture
def watch_http(watch_mod, monkeypatch):
    frames = {"png": b""}
    monkeypatch.setattr(watch_mod, "_screencap", lambda: frames["png"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), watch_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, frames
    finally:
        server.shutdown()
        server.server_close()


def _request(server: ThreadingHTTPServer, path: str, *, read: int | None = None):
    host, port = server.server_address
    conn = HTTPConnection(host, port, timeout=4)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read() if read is None else resp.read(read)
        return resp.status, resp.getheader("Content-Type") or "", body
    finally:
        conn.close()


def test_watch_html_uses_public_prefix_not_site_root(watch_mod):
    html = watch_mod.HTML
    assert watch_mod.PUBLIC_PREFIX == "/android"
    assert 'src="/android/stream.mjpeg"' in html
    assert 'src="/stream.mjpeg"' not in html
    assert 'src="/jarvis/android/stream.mjpeg"' not in html
    assert '<base href="/android/">' in html
    assert 'var STREAM_REL = "stream.mjpeg"' in html
    assert "The Android screen is not live yet." in html
    assert "/android/health" in html
    assert "http://127.0.0.1" not in html
    assert "http://localhost" not in html
    assert "127.0.0.1:6081" not in html


def test_page_is_fast_and_has_no_img_src_until_health_says_live(watch_http):
    server, frames = watch_http
    status, content_type, body = _request(server, "/")
    assert status == 200
    assert "text/html" in content_type
    html = body.decode("utf-8")
    assert 'id="still"' in html
    assert "The Android screen is not live yet." in html
    assert 'src="/android/stream.mjpeg"' in html
    assert "<img src=" not in html.split("<noscript>", 1)[0]
    prefixed = _request(server, "/android/")
    assert prefixed[0] == 200
    assert prefixed[2] == body
    frames["png"] = _PNG
    health_status, health_type, health_body = _request(server, "/android/health")
    assert health_status == 200
    assert "json" in health_type
    assert json.loads(health_body)["live"] is True


def test_health_reports_live_from_screencap(watch_http):
    server, frames = watch_http
    status, _, body = _request(server, "/health")
    assert status == 200
    assert json.loads(body) == {
        "ok": True,
        "kind": "android",
        "live": False,
        "play_store_client": False,
    }
    frames["png"] = _PNG
    again = json.loads(_request(server, "/status")[2])
    assert again["live"] is True


def test_stream_is_503_when_there_are_no_frames(watch_http):
    server, _frames = watch_http
    status, content_type, body = _request(server, "/android/stream.mjpeg")
    assert status == 503
    assert "text/plain" in content_type
    assert b"not live" in body
    root_status, _, root_body = _request(server, "/stream.mjpeg")
    assert root_status == 503
    assert root_body == body


def test_stream_starts_with_a_png_frame_when_live(watch_http):
    server, frames = watch_http
    frames["png"] = _PNG
    status, content_type, body = _request(server, "/android/stream.mjpeg", read=len(_PNG) + 80)
    assert status == 200
    assert "multipart/x-mixed-replace" in content_type
    assert b"--frame" in body
    assert b"Content-Type: image/png" in body
    assert _PNG in body
