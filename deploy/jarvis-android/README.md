# Jarvis's Android computer (ORCH-461)

A second box Jarvis can use. **Linux stays the default.**

This is **not** the Play Store phone app in `android/`. It is Jarvis's
own computer: a phone-shaped Android in Docker. Same Jarvis, same memory,
different machine.

## Start

```bash
cd deploy/jarvis-android
docker compose up -d
```

Then pick **Android** in Settings. Open Jarvis's screen the usual way.
The watch address is localhost only: [http://127.0.0.1:6081](http://127.0.0.1:6081).

Switch back to **Linux** any time. That is still
`deploy/jarvis-computer` on port 6080.

```bash
docker compose stop
docker compose start
docker compose down          # keeps the named volume
```

`docker compose down -v` wipes the Android data volume. Do not do that
if you want apps and files to stay.

## What he can do

On this box Jarvis can:

- Open apps and websites
- Tap and swipe (the cursor on a phone)
- Type
- Let you watch the same screen

He talks to container `jarvis-android` only. He does **not** exec into
the Linux `jarvis-computer` container.

## Honest limits

The image is an Android-in-container (redroid-class). You can swap the
image with `JARVIS_ANDROID_IMAGE` if you have another box that speaks
the same `screencap` / `input` / `am` tools.

Play Store / Google apps are not shipped here. Sideload with `adb`
if you need an extra app.

This host needs Docker and a privileged container. Some machines cannot
run Android-in-container. If the box will not start, Settings still
shows Android as a real choice — the job says the computer is off,
same as Linux when that container is down.

## Tests

```bash
pytest -q tests/test_jarvis_android_computer.py
./scripts/smoke_jarvis_android.sh
```
