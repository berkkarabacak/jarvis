"""Render the 72px Talk orb on teal and reject a white disc or dark stain."""

from __future__ import annotations

import http.server
import shutil
import socketserver
import subprocess
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "scripts" / "proof_talk_orb.html"
CHROME = shutil.which("google-chrome") or shutil.which("google-chrome-stable")


def test_proof_page_pins_canvas2d_on_teal():
    html = PROOF.read_text(encoding="utf-8")
    assert "background: #008080" in html
    assert "width: 72px" in html
    assert "height: 72px" in html
    assert "background: transparent" in html
    assert "box-shadow: none" in html
    assert 'renderer: "canvas2d"' in html
    assert 'id="more"' in html
    assert 'id="top"' not in html


@pytest.mark.skipif(not CHROME, reason="headless Chrome not installed")
def test_72px_talk_orb_is_cloudy_sphere_not_white_disc(tmp_path):
    from PIL import Image

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def log_message(self, format, *args):
            return

    httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    shot = tmp_path / "talk_orb_72px_teal.png"
    data_dir = tmp_path / "chrome"
    proc = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--user-data-dir=" + str(data_dir),
            "--window-size=720,420",
            "--virtual-time-budget=2000",
            "--screenshot=" + str(shot),
            f"http://127.0.0.1:{port}/scripts/proof_talk_orb.html",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(80):
            if shot.is_file() and shot.stat().st_size > 2000:
                break
            if proc.poll() is not None:
                break
            time.sleep(0.25)
        else:
            proc.kill()
            pytest.fail("Chrome did not write the 72px orb screenshot")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
        httpd.shutdown()
        httpd.server_close()

    assert shot.is_file()
    im = Image.open(shot).convert("RGB")
    orb = im.crop((300, 300, 372, 372))
    center = orb.getpixel((36, 36))
    assert max(center) < 250
    assert not (center[0] > 245 and center[1] > 245 and center[2] > 245)
    assert center[2] > center[1]  # lavender/cyan, not grey-white
    n = white = dark = pink = cyan = 0
    colors = set()
    r = g = b = 0
    for y in range(72):
        for x in range(72):
            dx, dy = x - 36, y - 36
            if dx * dx + dy * dy > 30 * 30:
                continue
            p = orb.getpixel((x, y))
            colors.add(p)
            n += 1
            r += p[0]
            g += p[1]
            b += p[2]
            if p[0] > 245 and p[1] > 245 and p[2] > 245:
                white += 1
            if p[0] < 28 and p[1] < 28 and p[2] < 28:
                dark += 1
            if p[0] > 160 and p[2] > 160 and p[1] < 210:
                pink += 1
            if p[1] > 140 and p[2] > 160 and p[0] < 150:
                cyan += 1
    assert n > 2000
    assert white == 0
    assert dark == 0
    assert pink > 80
    assert cyan > 80
    assert len(colors) > 400
    mean = (r / n, g / n, b / n)
    assert mean[2] > 160
    assert mean[0] < 200
    teal = im.getpixel((40, 40))
    assert teal == (0, 128, 128)
