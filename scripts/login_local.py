#!/usr/bin/env python3
"""One-time local PKCE login for SuperGrok OAuth.

Borrowed client only allows http://127.0.0.1:56121/callback.
Run this on a machine with a browser, then import tokens to the server:

  python scripts/login_local.py
  python scripts/login_local.py --import-url https://your-host --api-secret SECRET
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Allow running from repo root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx

from app.auth.constants import XAI_OAUTH_REDIRECT_HOST, XAI_OAUTH_REDIRECT_PORT
from app.auth.oauth import (
    build_authorize_url,
    create_oauth_nonce,
    create_oauth_state,
    discover_xai_oauth,
    exchange_code_for_tokens,
    generate_pkce,
)


class _Handler(BaseHTTPRequestHandler):
    result: dict | None = None

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = parse_qs(parsed.query)
        if qs.get("error"):
            _Handler.result = {
                "error": qs.get("error_description", qs.get("error", ["unknown"]))[0]
            }
        else:
            _Handler.result = {
                "code": (qs.get("code") or [""])[0],
                "state": (qs.get("state") or [""])[0],
            }
        body = b"<html><body><h1>Login complete</h1><p>You can close this window.</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # noqa: A003
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Local SuperGrok OAuth PKCE login")
    parser.add_argument("--host", default=XAI_OAUTH_REDIRECT_HOST)
    parser.add_argument("--port", type=int, default=XAI_OAUTH_REDIRECT_PORT)
    parser.add_argument("--out", default="./.tokens/oauth_tokens.json")
    parser.add_argument("--import-url", default="", help="Server base URL to POST /oauth/import")
    parser.add_argument("--api-secret", default="", help="API secret for import")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    redirect_uri = f"http://{args.host}:{args.port}/callback"
    pkce = generate_pkce()
    state = create_oauth_state()
    nonce = create_oauth_nonce()
    url = build_authorize_url(
        redirect_uri=redirect_uri,
        code_challenge=pkce.challenge,
        state=state,
        nonce=nonce,
    )

    server = HTTPServer((args.host, args.port), _Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print("Open this URL to authorize:\n")
    print(url)
    print()
    if not args.no_browser:
        webbrowser.open(url)

    deadline = time.time() + 180
    while _Handler.result is None and time.time() < deadline:
        time.sleep(0.2)
    server.server_close()

    if _Handler.result is None:
        print("Timed out waiting for callback", file=sys.stderr)
        return 1
    if _Handler.result.get("error"):
        print(f"OAuth error: {_Handler.result['error']}", file=sys.stderr)
        return 1
    if _Handler.result.get("state") != state:
        print("State mismatch", file=sys.stderr)
        return 1

    import asyncio

    async def _exchange():
        d = await discover_xai_oauth()
        t = await exchange_code_for_tokens(
            token_endpoint=d.token_endpoint,
            code=_Handler.result["code"],
            redirect_uri=redirect_uri,
            code_verifier=pkce.verifier,
            code_challenge=pkce.challenge,
        )
        return d, t

    discovery, tokens = asyncio.run(_exchange())

    payload = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "expires_at": tokens.expires_at,
        "token_endpoint": discovery.token_endpoint,
        "redirect_uri": redirect_uri,
        "token_type": tokens.token_type,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Saved tokens to {out}")

    if args.import_url:
        if not args.api_secret:
            print("--api-secret required with --import-url", file=sys.stderr)
            return 1
        base = args.import_url.rstrip("/")
        r = httpx.post(
            f"{base}/oauth/import",
            headers={"X-Api-Key": args.api_secret, "Content-Type": "application/json"},
            json=payload,
            timeout=30.0,
        )
        print(f"Import HTTP {r.status_code}: {r.text}")
        if r.status_code >= 400:
            return 1

    print("Done. Do not commit token files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
