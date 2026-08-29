# Public Jarvis page

Source for https://aicontrolroom.nl/ (alias: https://berkkarabacak.com/jarvis/)

Family page: **Jarvis**, a chat list, a box to type, a Talk control, and a small **Download**.

The page is served by the Jarvis app (FastAPI) at `/`. It calls `/api/jarvis/ask` and `/api/jarvis/speak`. It is not a dead file in `/var/www/jarvis`. Old `/jarvis/` bookmarks 301 to `/`.

Download stays `/download/Jarvis-Setup.exe` (`/jarvis/download/` 301s there). No API key. No zip or Advanced link. No Play Store. No iOS.

## Site (nginx)

If `/` is still only files from `/var/www/jarvis`, talk cannot work. On aicontrolroom.nl:

1. Keep `/download/` on disk (`/var/www/jarvis/download/`).
2. Proxy `/` and `/api/jarvis/` to the Jarvis app on `127.0.0.1:8895`. Do not send `/ceo`, `/health`, or `/api/control-plane/v1/` to Talk.
3. 301 `/jarvis` and `/jarvis/` to `/`. 301 other `/jarvis/...` paths to the same path without the prefix.

See `deploy/nginx-aicontrolroom.nl.conf`. The berkkarabacak.com alias is `deploy/nginx-jarvis-public.fragment`. Reload nginx after the edit.
