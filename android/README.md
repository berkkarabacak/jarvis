# Jarvis for Android (ORCH-387 / ORCH-388)

First phone app: talk to Jarvis and open Settings. Target device is a Galaxy S25.
This is a **debug / internal** build. It is not a Play Store listing (ORCH-389).
Google Play Billing for Free / $3 / $8 is wired here (ORCH-388). Product IDs
live in [play-billing.md](play-billing.md). Do not invent a Play Store URL.

The public site refers to Jarvis at [aicontrolroom.nl](https://aicontrolroom.nl/) ([berkkarabacak.com/jarvis](https://berkkarabacak.com/jarvis/) is an alias).
Package id: `com.berkkarabacak.jarvis` (debug builds use `.debug`).

## What this app talks to

Reuse the existing Control Room / Jarvis HTTP contract. Do not invent a second protocol.

| Action | Method | Path | Auth |
| --- | --- | --- | --- |
| Health | GET | `/api/jarvis/health` | `X-Api-Key` when set |
| Read Settings | GET | `/api/jarvis/settings` | `X-Api-Key` when set |
| Save Settings | PUT | `/api/jarvis/settings` | `X-Api-Key` (required off-loopback) |
| Start a talk | POST | `/api/executive/runtime/missions` | `X-Api-Key` |
| Send a message | POST | `/api/executive/runtime/sessions/{session_id}/messages` | `X-Api-Key` |

Settings fields this build **reads and writes** are the ORCH-380 persist keys
from `app/jarvis/settings_store.py` (`config_version` 2):

- `look_speed` — `off` | `30s` | `10s` | `1s`
- `quality_vs_price` — `fast` | `balanced` | `smart` (unset GET view defaults to `balanced`)

Windows aliases `model_preference` and `model_speed` may appear in the same
JSON. This app ignores them: it does not map them and does not PUT them.
- `monthly_budget_usd` / `daily_budget_usd` — `0` or `null` = no limit
- `permission_profile`

GET also reads `budget`: `{ monthly_cap_usd, monthly_spent_usd, monthly_remaining_usd, daily_cap_usd, daily_spent_usd, daily_remaining_usd, hit, near_cap, action }` where `action` is `ok` | `cheaper` | `stop`. Spend numbers are shown only when the server sends them.

Subscribe (ORCH-388) writes only `monthly_budget_usd` after a real Play
purchase or a confirmed restore:

| Product ID | Plan | `monthly_budget_usd` |
| --- | --- | --- |
| `jarvis_free` | Free — try Jarvis, tiny cap (default, no purchase) | `1` |
| `jarvis_3` | $3 spend limit | `3` |
| `jarvis_8` | $8 spend limit | `8` |

Exactly three products. If Google Play is missing (debug sideload / no
developer account) the Subscribe block still shows Free / $3 / $8 and
“Google Play is needed to subscribe”. It does not crash and does not fake a
paid purchase.

The PIN hash is never requested or shown. `model_lock_pin` / `unlock_pin` are write-only and unused in this mom-simple screen.

The phone does **not** keep a private copy of the Settings JSON. After Save, a
restart reloads GET `/api/jarvis/settings` from the same server the web page uses.
Only the server address and API key are stored on the phone (so the app can find
Jarvis again).

## Point the app at a Jarvis server

1. Run the orchestrator (same as the Windows / web path):

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8787
   ```

   `0.0.0.0` is required if the phone is not the same machine.

2. In the app: **Settings → Where Jarvis lives**
   - Galaxy S25 on the same Wi-Fi: `http://<your-pc-lan-ip>:8787`
   - Android emulator: `http://10.0.2.2:8787`
   - Hosted path (if Jarvis is enabled there): the site origin, including any
     reverse-proxy prefix such as `/agent-orchestrator`
3. Paste the same `API_SECRET` the server uses (`X-Api-Key`).
4. Tap **Test connection**, then **Save**.

Cloud public hosts often keep `JARVIS_ENABLED=false`. Point at a machine that
actually runs Jarvis.

## Build a debug APK

Needs JDK 17+ and the Android SDK (compile/target SDK 35).

```bash
export ANDROID_HOME="$HOME/android-sdk"   # or your SDK path
export ANDROID_SDK_ROOT="$ANDROID_HOME"
cd android
./gradlew assembleDebug test
```

APK:

```
android/app/build/outputs/apk/debug/app-debug.apk
```

`applicationId` for this APK is `com.berkkarabacak.jarvis.debug`.

## Build a release AAB (prep)

`bundleRelease` writes an Android App Bundle so an AAB is ready the moment a
Play developer account exists. There is no Play Store URL. Do not invent one.

Optional upload-key signing (never commit the keystore or passwords):

- env or `local.properties`: `STORE_FILE`, `STORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`

If those are unset, the release AAB is signed with the Android debug keystore
so this command succeeds on a clean machine. That debug-signed AAB is prep
only. Play App Signing and a real upload key happen after the Play developer
account exists.

```bash
export ANDROID_HOME="$HOME/android-sdk"   # or your SDK path
export ANDROID_SDK_ROOT="$ANDROID_HOME"
cd android
./gradlew :app:bundleRelease
```

AAB:

```
android/app/build/outputs/bundle/release/app-release.aab
```

## Sideload onto a Galaxy S25

1. On the phone: **Settings → Security** (or **Auto Blocker** / developer options)
   and allow installing unknown apps for Files or for your computer.
2. Copy `app-debug.apk` to the phone (USB, Drive, or `adb`).
3. Open the APK and install.
4. Or with USB debugging:

   ```bash
   adb install -r android/app/build/outputs/apk/debug/app-debug.apk
   ```

5. Open **Jarvis**, go to Settings, set the server, Save, then send a message.

There is no Play Store URL for this ticket. Do not invent one.

## Tests

```bash
cd android && ./gradlew test
```

- Settings GET/PUT against a fake server (save, new client, value still there)
- Talk: open mission + send message on the real executive paths
- Contract: PUT body never includes unpublished budget / quality keys
- Play Billing: fake BillingClient covers Free / $3 / $8 mapping, no fourth
  product, and PUT uses only `monthly_budget_usd`. Tests do not need Play Console.

## Later tickets

- Play Store listing copy is drafted in [play-store-listing.md](play-store-listing.md).
  ORCH-388 / ORCH-389 stay open until a real Play developer account and store
  URL exist. Do not invent a `play.google.com/store` link.
