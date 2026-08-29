# Public Jarvis page

Source for https://berkkarabacak.com/jarvis/

Family page: **Jarvis**, a chat list, a box to type, a Talk control, and a small **Download**.

The page is served by the Jarvis app (FastAPI) at `/jarvis/`. It calls `/jarvis/api/jarvis/ask` and `/jarvis/api/jarvis/speak`. It is not a dead file in `/var/www/jarvis`.

Download stays `/jarvis/download/Jarvis-Setup.exe`. No API key. No zip or Advanced link. No Play Store. No iOS.

## Site (nginx)

If `/jarvis/` is still only files from `/var/www/jarvis`, talk cannot work. One change:

1. Keep `/jarvis/download/` on disk (`/var/www/jarvis/download/`).
2. Proxy the rest of `/jarvis/` to the Jarvis app (same process that already has `/api/jarvis/ask`). Do not strip the `/jarvis` prefix.

See `deploy/nginx-jarvis-public.fragment`. Reload nginx after the edit.
