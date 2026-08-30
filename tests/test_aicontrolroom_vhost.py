"""aicontrolroom.nl serves Talk at / and keeps the old control room."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VHOST = ROOT / "deploy" / "nginx-aicontrolroom.nl.conf"
FRAGMENT = ROOT / "deploy" / "nginx-jarvis-public.fragment"


def test_vhost_makes_talk_the_home_page():
    text = VHOST.read_text(encoding="utf-8")
    assert "location = / {" in text
    assert "return 302 /jarvis/;" not in text
    assert "proxy_pass http://jarvis_talk/;" in text
    assert "location = /jarvis { return 301 $scheme://$host/; }" in text
    assert "location = /jarvis/ { return 301 $scheme://$host/; }" in text
    assert "rewrite ^/jarvis/(.*)$ /$1 permanent;" in text
    assert "location ^~ /api/jarvis/" in text
    assert "proxy_pass http://jarvis_talk;" in text
    assert "server 127.0.0.1:8895;" in text


def _proxy_pass_uri(block: str) -> str:
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("proxy_pass ") and stripped.endswith(";"):
            return stripped[len("proxy_pass ") : -1].strip()
    raise AssertionError(f"no proxy_pass in {block}")


def _nginx_upstream_path(location: str, proxy_pass: str, request_uri: str) -> str:
    """URI replacement nginx applies when proxy_pass includes a path."""
    from urllib.parse import urlsplit

    parsed = urlsplit(proxy_pass)
    if not parsed.path:
        return request_uri
    if location.startswith("= "):
        matched = location[2:]
    elif location.startswith("^~ "):
        matched = location[3:]
    else:
        matched = location
    assert request_uri.startswith(matched), (request_uri, matched)
    return parsed.path + request_uri[len(matched) :]


def _location_block(text: str, header: str) -> str:
    start = text.find(header)
    assert start != -1, header
    brace = text.find("{", start)
    assert brace != -1, header
    depth = 0
    for i, ch in enumerate(text[brace:], start=brace):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError(f"unclosed location {header}")


def test_vhost_serves_talk_assets_at_root():
    text = VHOST.read_text(encoding="utf-8")
    assert "location ^~ /download/" in text
    assert "alias /var/www/jarvis/download/;" in text
    assert "location ^~ /android/" in text
    assert "proxy_pass http://127.0.0.1:6081/;" in text
    assert "location ^~ /novnc/" in text
    assert "proxy_pass http://127.0.0.1:6080/;" in text
    assert "location = /voice-orb.js" in text
    assert "location = /screen" in text
    assert "location ^~ /hello/" in text
    assert 'proxy_set_header Upgrade $http_upgrade;' in text
    assert 'proxy_set_header Connection "upgrade";' in text
    assert "listen 0.0.0.0:6080" not in text
    assert "proxy_pass http://0.0.0.0:6080" not in text


def test_vhost_proxies_novnc_websocket_to_websockify_root():
    """/novnc/websockify must hit :6080/, not :6080/websockify (Python 404)."""
    text = VHOST.read_text(encoding="utf-8")
    ws = _location_block(text, "location = /novnc/websockify")
    assert "proxy_pass http://127.0.0.1:6080/;" in ws
    assert "proxy_pass http://127.0.0.1:6080/websockify" not in ws
    assert "proxy_http_version 1.1;" in ws
    assert "proxy_set_header Upgrade $http_upgrade;" in ws
    assert 'proxy_set_header Connection "upgrade";' in ws
    assert "proxy_read_timeout 3600s;" in ws
    assert "proxy_send_timeout 3600s;" in ws
    leftover = _location_block(text, "location = /jarvis/novnc/websockify")
    assert "proxy_pass http://127.0.0.1:6080/;" in leftover
    assert "proxy_set_header Upgrade $http_upgrade;" in leftover
    assert 'proxy_set_header Connection "upgrade";' in leftover
    assert "proxy_read_timeout 3600s;" in leftover
    prefix = _location_block(text, "location ^~ /novnc/")
    assert "location = /novnc/websockify" not in prefix
    assert "proxy_pass http://127.0.0.1:6080/;" in prefix
    # Prefix rewrite is why visitors 404 today; the exact location fixes it.
    assert (
        _nginx_upstream_path("^~ /novnc/", _proxy_pass_uri(prefix), "/novnc/websockify")
        == "/websockify"
    )
    assert (
        _nginx_upstream_path("= /novnc/websockify", _proxy_pass_uri(ws), "/novnc/websockify")
        == "/"
    )
    assert (
        _nginx_upstream_path("^~ /novnc/", _proxy_pass_uri(prefix), "/novnc/vnc.html")
        == "/vnc.html"
    )
    leftover_pass = _proxy_pass_uri(leftover)
    assert (
        _nginx_upstream_path(
            "= /jarvis/novnc/websockify", leftover_pass, "/jarvis/novnc/websockify"
        )
        == "/"
    )
    # Exact websocket locations must not swallow Talk or the old control room.
    assert "location = / {" in text
    assert "location ^~ /ceo" in text
    assert "location = /health" in text
    assert "location = /screen" in text


def test_vhost_keeps_old_control_room_on_8896():
    text = VHOST.read_text(encoding="utf-8")
    assert "location ^~ /ceo" in text
    assert "location = /health" in text
    assert "location /api/control-plane/v1/" in text
    assert text.count("proxy_pass http://ai_control_room;") == 3
    for needle in (
        "proxy_set_header X-Real-IP",
        "proxy_set_header X-Forwarded-Proto",
        "proxy_set_header X-Forwarded-Host",
    ):
        assert text.count(needle) >= 3
    https = text.split("server_name aicontrolroom.nl;", 2)[-1]
    ceo_at = https.find("location ^~ /ceo")
    talk_at = https.find("location = / {")
    assert ceo_at != -1 and talk_at != -1
    assert "location ^~ /api/jarvis/" in https
    assert https.find("location /api/control-plane/v1/") != -1


def test_vhost_does_not_send_all_of_slash_to_8896():
    text = VHOST.read_text(encoding="utf-8")
    assert "location / {\n        proxy_pass http://ai_control_room;" not in text
    https = text.split("server_name aicontrolroom.nl;", 2)[-1]
    assert "location / {" not in https


def test_www_apex_redirect_stays():
    text = VHOST.read_text(encoding="utf-8")
    assert "server_name www.aicontrolroom.nl;" in text
    assert "return 301 https://aicontrolroom.nl$request_uri;" in text


def test_berkkarabacak_fragment_stays_an_alias():
    text = FRAGMENT.read_text(encoding="utf-8")
    assert "https://berkkarabacak.com/jarvis/" in text
    assert "return 301 https://aicontrolroom.nl/;" in text
    assert "location ^~ /jarvis/download/" in text
    assert "location /jarvis/" in text
    assert "proxy_pass http://127.0.0.1:8895/jarvis/;" in text
    assert "location ^~ /jarvis/android/" in text
    assert "location ^~ /jarvis/novnc/" in text
    ws = _location_block(text, "location = /jarvis/novnc/websockify")
    assert "proxy_pass http://127.0.0.1:6080/;" in ws
    assert "proxy_pass http://127.0.0.1:6080/websockify" not in ws
    assert "proxy_set_header Upgrade $http_upgrade;" in ws
    assert 'proxy_set_header Connection "upgrade";' in ws
    assert "proxy_read_timeout 3600s;" in ws
    assert "proxy_send_timeout 3600s;" in ws


def test_docs_list_aicontrolroom_as_primary_public_url():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert readme.index("https://aicontrolroom.nl/") < readme.index(
        "https://berkkarabacak.com/jarvis/"
    )
    assert "**Live demo:** [https://aicontrolroom.nl/]" in readme
    assert "https://aicontrolroom.nl/" in contributing
    assert "https://aicontrolroom.nl/jarvis/" not in readme
    assert "https://aicontrolroom.nl/jarvis/" not in contributing
