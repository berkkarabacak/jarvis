# Google Play Billing (ORCH-388)

Android only. Exactly three subscription products. This file is the product-ID
contract for Play Console. It is **not** a Play Store listing (that is ORCH-389).
Do not invent a `play.google.com/store` URL.

Code and tests in this repo do **not** wait for a Play Console developer
account. Sideloaded debug builds must still compile, show the three plans, and
say “Google Play is needed to subscribe” without crashing or faking a paid
purchase.

## Product IDs

Create these as **subscriptions** in Play Console (one subscription group).
Use these IDs exactly:

| Product ID | Plan | `monthly_budget_usd` |
| --- | --- | --- |
| `jarvis_free` | Free — try Jarvis, tiny spend cap | `1` |
| `jarvis_3` | $3 spend limit | `3` |
| `jarvis_8` | $8 spend limit | `8` |

Do not add a fourth product.

`jarvis_free` is the default when there is no paid purchase. Mom taps
**Subscribe** and picks `$3` or `$8`. Free is shown as the current plan until
Google Play reports `jarvis_3` or `jarvis_8`.

## What the app does

- Uses Google Play Billing Library 9.1.0 and the
  `com.android.vending.BILLING` permission. The Java artifact is used so the
  existing Kotlin 2.0.21 compiler can build it (the KTX module needs Kotlin 2.3).
- Queries only the three IDs above as `ProductType.SUBS`.
- Shows Play price strings when Play returns them. Otherwise shows Free / $3 / $8.
- Restores purchases on launch and when Settings opens.
- On a real purchase + acknowledge, PUT `/api/jarvis/settings` with
  `monthly_budget_usd` set to `1`, `3`, or `8`. Daily cap is left alone.
- Does not invent spend numbers. Does not send Windows aliases
  `model_preference` / `model_speed`.
- Does not use RevenueCat.

## Settings keys

Budget still goes through the existing persist API (ORCH-380):

- GET/PUT `/api/jarvis/settings`
- `monthly_budget_usd` / `daily_budget_usd`

There is no parallel billing schema on the phone.

## Out of scope

- Play Store listing and store URL (ORCH-389)
- iOS
- A fourth price
- Secrets, license keys, or Play Console credentials in this repo
