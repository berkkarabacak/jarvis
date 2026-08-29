# Play Store listing draft (ORCH-389)

Draft only. Ticket stays To Do until Google publishes a real
`play.google.com/store/apps/details` link. Do not invent that link.

Package: `com.berkkarabacak.jarvis` (debug: `.debug`)
Target device: Galaxy S25

## Store text

**Name** (30): Jarvis

**Short description** (80): Talk to Jarvis. Set a budget. Subscribe for $3 or $8.

**Full description:**

Jarvis is an AI colleague on your phone.

Talk to it in plain language. Open Settings to set how much it may spend, and whether it should work Fast, Balanced, or Smart.

Three plans only:

- Free — try Jarvis, tiny spend cap
- $3 — spend limit
- $8 — spend limit

Tap Subscribe and pick $3 or $8. You can do this without help.

Android only. No iOS in this listing.

## Graphics

These files are listing mockups, not real Galaxy S25 captures. Replace them
with real S25 captures after the debug APK is installed. Ticket stays To Do.

Phone screenshots (Galaxy S25, portrait):

- `android/store-listing/jarvis-s25-talk.png`
- `android/store-listing/jarvis-s25-settings.png`
- `android/store-listing/jarvis-s25-subscribe.png` — Free / $3 / $8 only. No iOS. No fourth price.

Feature graphic: “Jarvis — Talk. Set a budget. Subscribe.”

- `android/store-listing/jarvis-feature-graphic.png`

Crop the feature graphic to 1024×500 before Play Console upload.

Do not invent a `play.google.com/store` URL. There is no privacy-policy URL
(none published).

## AAB prep

From `android/`:

```bash
./gradlew :app:bundleRelease
```

Output: `android/app/build/outputs/bundle/release/app-release.aab`.

Without `STORE_FILE` / `STORE_PASSWORD` / `KEY_ALIAS` / `KEY_PASSWORD` (env or
`local.properties`) that AAB is signed with the Android debug keystore. Prep
only — not a Play upload key. Play App Signing and a real upload key happen
after the Play developer account exists. There is no Play Store URL. Do not
invent one.

## Not ready

- Privacy policy URL — none published yet. Do not invent one.
- Play App Signing, content rating, data safety — need a Play Console developer account.
- Closed testing / production — same.
- Install link — post the real Play Store URL on ORCH-389 when Google publishes it. Never invent it.

## Prices

Product IDs from ORCH-388: `jarvis_free`, `jarvis_3`, `jarvis_8`.
No fourth price.
