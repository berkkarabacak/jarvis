"""aicontrolroom.nl serves Talk at /jarvis/ and keeps the old control room."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VHOST = ROOT / "deploy" / "nginx-aicontrolroom.nl.conf"
FRAGMENT = ROOT / "deploy" / "nginx-jarvis-public.fragment"


def test_vhost_makes_talk_the_home_page():
    text = VHOST.read_text(encoding="utf-8")
    assert "location = / {" in text
    assert "return 302 /jarvis/;" in text
    assert "location = /jarvis { return 301 $scheme://$host/jarvis/; }" in text
    assert "location /jarvis/" in text
    assert "proxy_pass http://127.0.0.1:8895/jarvis/;" in text


def test_vhost_copies_jarvis_locations_from_fragment():
    text = VHOST.read_text(encoding="utf-8")
    assert "location ^~ /jarvis/download/" in text
    assert "alias /var/www/jarvis/download/;" in text
    assert "location ^~ /jarvis/android/" in text
    assert "proxy_pass http://127.0.0.1:6081/;" in text
    assert "location ^~ /jarvis/novnc/" in text
    assert "proxy_pass http://127.0.0.1:6080/;" in text
    assert 'proxy_set_header Upgrade $http_upgrade;' in text
    assert 'proxy_set_header Connection "upgrade";' in text
    assert "listen 0.0.0.0:6080" not in text
    assert "proxy_pass http://0.0.0.0:6080" not in text


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


def test_vhost_does_not_send_all_of_slash_to_8896():
    text = VHOST.read_text(encoding="utf-8")
    assert "location / {\n        proxy_pass http://ai_control_room;" not in text
    https = text.split("server_name aicontrolroom.nl;", 2)[-1]
    assert "location / {" not in https


def test_www_apex_redirect_stays():
    text = VHOST.read_text(encoding="utf-8")
    assert "server_name www.aicontrolroom.nl;" in text
    assert "return 301 https://aicontrolroom.nl$request_uri;" in text


def test_berkkarabacak_fragment_still_serves_jarvis():
    text = FRAGMENT.read_text(encoding="utf-8")
    assert "https://berkkarabacak.com/jarvis/" in text
    assert "location ^~ /jarvis/download/" in text
    assert "location /jarvis/" in text
    assert "proxy_pass http://127.0.0.1:8895/jarvis/;" in text


def test_docs_list_aicontrolroom_as_primary_public_url():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert readme.index("https://aicontrolroom.nl/jarvis/") < readme.index(
        "https://berkkarabacak.com/jarvis/"
    )
    assert "**Live demo:** [https://aicontrolroom.nl/jarvis/]" in readme
    assert "https://aicontrolroom.nl/jarvis/" in contributing
