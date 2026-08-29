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
