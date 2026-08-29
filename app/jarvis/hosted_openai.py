"""Hosted OpenAI key for public free Realtime.

The hosted credential is **injected via the HOSTED_OPENAI_KEY environment
variable** on the server that needs it. It is never hardcoded in source: a
previous revision shipped a live key here in a public repository (issue #144).

Resolution order for ``openai_api_key()``:

1. ``OPENAI_API_KEY`` from the process environment
2. ``HOSTED_OPENAI_KEY`` from the process environment (server-side deploys only)
3. empty string - callers fall back to the hosted-talk URL routing
   (``app.jarvis.talk_auth.should_use_hosted_talk``)

Never put a real key, ``sk-or-`` placeholder, or ``sk-`` placeholder in this file.
"""

from __future__ import annotations

import os


def openai_api_key() -> str:
    return (
        (os.environ.get("OPENAI_API_KEY") or "").strip()
        or (os.environ.get("HOSTED_OPENAI_KEY") or "").strip()
    )
