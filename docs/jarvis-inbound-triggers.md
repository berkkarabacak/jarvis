# DESIGN: inbound triggers — `@jarvis` from Slack or GitHub (ORCH-326)

**Status:** design only — no implementation on this ticket.
**Epic:** ORCH-321 [A8] connector platform.
**Blocked by:** ORCH-325 (GitHub / Slack read-only connectors).
**Audience:** GRoK decision (same format as ORCH-296..301).

## Problem

The Codex model — `@Codex` in a Slack thread or on a GitHub issue — creates a
cloud sandbox task without opening a terminal. That is the feature that most
changes how a tool *feels*, and the one with the worst failure mode here.

Every other Jarvis path keeps one assumption: **the request originates from the
person at the machine.** Permission tiers (ORCH-245/247), spoken confirmation
nonces (ORCH-301), and taint tracking (ORCH-297) all rest on it. Inbound triggers
invert it: the request arrives from the network, from someone who may not be the
owner, aimed at a laptop that still has `run_powershell` on it.

Codex can do this comfortably because it runs in a **cloud sandbox with a cloned
repo**. Jarvis runs on the **user's actual machine**. Same UX pitch; different
proposition. **"We should not build this for local shell tools"** is an
acceptable outcome of this design pass.

This doc settles the five questions in ORCH-326 before any code, then gives one
honest product recommendation.

Related reading: `docs/jarvis-permissions.md`, `docs/jarvis-security.md`,
`docs/jarvis-bridge.md`, `app/jarvis/taint.py`, `app/jarvis/nonce.py`.

---

## Q1 — Who may trigger, and how is identity verified?

### Options

**Option 1 — Anyone in the channel / on the issue**
Any Slack member who can `@jarvis`, or any GitHub collaborator who can comment,
may start a turn.
_For:_ matches the social feel of `@Codex`; zero identity plumbing.
_Against:_ identity is **asserted by the chat UI**, not verified against the
laptop owner. A coworker, a compromised Slack session, or a public-fork PR
comment becomes a remote driver of the owner's PC. Fail-open by design.

**Option 2 — Owner allowlist by platform user id (recommended if anything ships)**
A durable settings list maps *this laptop* → Slack user id(s) and GitHub
login(s). The webhook rejects anyone else before the model runs. Verification
comes from the platform signature (Slack signing secret / GitHub webhook secret)
**plus** an allowlisted actor id — never from display name or free-text
self-identification in the message body.
_For:_ identity is checked, not hoped for; matches single-user desktop threat
model; auditable.
_Against:_ setup friction; shared family Slack workspaces need an explicit
allow entry; does not help if the owner's Slack/GitHub account itself is
compromised (see Q5).

**Option 3 — Owner + cryptographic challenge each session**
Allowlist as in Option 2, plus a one-time pairing code shown only on the local
CEO UI / spoken once, required to arm inbound for N hours.
_For:_ strongest; survives a stolen Slack cookie better than Option 2 alone.
_Against:_ kills the "never open a terminal / never touch the laptop" fantasy;
high UX cost for a v1 that may not be worth building at all.

### Recommendation

**Option 2** if inbound ships at all. Never Option 1. Option 3 is a later
hardening pass, not a prerequisite to *deciding* whether to build.

**Do not** treat Bridge token possession (`docs/jarvis-bridge.md`) as a
substitute for platform identity — Bridge is loopback + shared secret for local
agents, not a proof that Berk typed the Slack message.

---

## Q2 — What tier ceiling applies to a remotely-triggered turn?

### Options

**Option 1 — Inherit the local permission profile**
If the laptop is on `power` (auto L3), so is the inbound turn.
_For:_ one policy story.
_Against:_ the whole point of inbound is that the owner may be elsewhere; auto
shell from Slack is the blast radius we are trying not to create. Profile was
chosen by a person *at* the machine.

**Option 2 — L1 hard cap, no shell, no home writes (recommended)**
Inbound sessions get `max_tier = L1` regardless of local profile: workspace
read/write, facts, memory recall — **not** `run_powershell`, `run_app`,
`open_path`, `home_*`, L4 UI, or L5. MCP connectors stay read-only (ORCH-325).
_For:_ bounds the outcome even if identity or the model fails; aligns with
existing `BRIDGE_MAX_TIER_AUTO=L1` instinct; easy to enforce in ToolGateway with
a session flag.
_Against:_ cannot "fix CI from Slack" or "merge the PR by voice-adjacent
inbound"; those become explicit future tickets with their own confirm story.

**Option 3 — L0 only (read facts / recall)**
Inbound may answer questions about already-local state but cannot write the
workspace.
_For:_ smallest surface.
_Against:_ removes most of the useful "draft a reply / summarise this thread
into a note" value; probably too timid if we bother to build inbound at all.

### Recommendation

**Option 2 — L1 hard cap.** Document it as non-overridable from Slack/GitHub
text. Local profile and Bridge ceilings do not raise it. Unknown tools stay
fail-closed (ORCH-296).

---

## Q3 — Confirmation when the owner is not at the machine

The spoken nonce (ORCH-301) assumes the owner can hear the Realtime voice
channel and speak the code back. Inbound breaks that.

### Options

**Option 1 — Post the nonce into the originating Slack/GitHub thread**
Same confirm protocol, different transport.
_For:_ keeps L2+/confirm-gated work reachable remotely.
_Against:_ the nonce becomes readable by **everyone in the channel / on the
issue**. That is not a second factor; it is a group chat OTP. ORCH-319 already
exists because the model must not approve itself — publishing the code to a
shared medium is the same class of mistake.

**Option 2 — DM the nonce to the allowlisted owner only**
Slack DM (or GitHub only if a private side channel exists — it mostly does not).
_For:_ better than channel broadcast.
_Against:_ Slack DMs are still phishable and device-synced; GitHub has no clean
equivalent; still confirms a **remote** action against a **local** shell-capable
host. Complexity high for a feature we may reject.

**Option 3 — Refuse anything that needs confirmation; no spoken/thread nonce for inbound (recommended)**
If the gateway would return `needs_confirm`, or the tool is above the inbound
ceiling, **refuse** with a plain reply in-thread: _"I can only do that when
you're at the machine."_ No nonce is ever rendered into Slack or GitHub.
_For:_ preserves ORCH-301's threat model; zero shared-medium OTP; matches L1
hard cap (almost nothing inbound should need confirm anyway).
_Against:_ remote "approve this destructive thing" is impossible — which is the
point.

### Recommendation

**Option 3.** Explicitly: **no spoken nonce, and no nonce text, in Slack or
GitHub.** Confirm-gated and L2+ work stays a local-only path (CEO UI / voice at
the laptop / Bridge confirm from a local agent the owner already trusts).

---

## Q4 — Does a remote trigger start already tainted?

### Options

**Option 1 — Start clean**
Treat the inbound message like a local user utterance (`clear_taint`).
_For:_ symmetric with Bridge's current "new task clears taint" behaviour.
_Against:_ Bridge assumes a **local** caller holding a loopback token. An inbound
body is third-party text by definition (teammate, issue reporter, poisoned PR
comment). Starting clean invites the confused-deputy path ORCH-297 exists to
stop — except the "user asked to read the file" step is skipped entirely.

**Option 2 — Start tainted (recommended)**
Create the session with taint already set (`source=inbound:slack|github`). L3+
blocked (redundant with Q2 but defence in depth); L1–L2 confirm-downgrade
applies; inbound body and any fetched thread/issue content stay fenced.
Taint clears only on a **local** owner utterance (Realtime / CEO), never on
another inbound message.
_For:_ matches reality — the triggering text is untrusted input; composes with
ORCH-297/324 without special cases per connector.
_Against:_ slightly more friction for benign "summarise this thread" flows
(acceptable; still L1-auto under a hard cap if we choose not to confirm-downgrade
L1 for inbound — see decision note below).

**Option 3 — Separate "inbound quarantine" mode**
A third state stricter than taint (e.g. model may only call a fixed summarize
tool).
_For:_ clearest mental model.
_Against:_ new state machine beside taint; two systems to audit. Prefer
reusing taint unless experience shows it is insufficient.

### Recommendation

**Option 2 — start tainted.** Decision note for implementers (not for this
ticket): under an L1 hard cap, either keep the normal tainted L1
confirm-downgrade, or allow L1 auto while tainted *only* for inbound sessions
that also refuse L2+. Prefer the stricter reading first.

---

## Q5 — Rate limits and kill switch

### Options

**Option 1 — Rely on platform rate limits only**
Slack/GitHub will eventually 429 us.
_For:_ no code.
_Against:_ does not protect the **laptop** from a burst of accepted webhooks
while tokens are valid; no owner-controlled stop.

**Option 2 — Per-source limits + global kill switch (recommended)**
- Per allowlisted actor: low ceiling (e.g. 10 turns / hour).
- Per installation: slightly higher ceiling.
- Concurrent inbound turns: 1 (queue or 429).
- Goal / prompt max length enforced before the model runs.
- **Kill switch:** `JARVIS_INBOUND_ENABLED=false` (default **false**) plus a
  Settings toggle that flips the same durable bit; when off, webhooks verify
  signatures then ack with "inbound disabled" and run **no** tools.
- Optional: local hotkey / CEO button "disable inbound now" that does not depend
  on Slack being reachable.
_For:_ owner can shut the door without revoking OAuth; matches Bridge's
`BRIDGE_RATE_PER_HOUR` pattern; default-off means ORCH-325 can land without
accidentally arming inbound.
_Against:_ a little settings UI and env surface.

**Option 3 — Kill switch only, generous rates**
_For:_ simpler.
_Against:_ a compromised allowlisted account can still burn a workday of tool
calls and tokens before the owner notices.

### Recommendation

**Option 2.** Default **off**. Shipping connectors (ORCH-325) must not imply
inbound-on. Audit every accepted and every rejected trigger.

---

## Q6 — Honest product recommendation

### Options

**Option A — Build full Codex-style inbound against local tools**
`@jarvis fix this` from Slack may write the workspace, and eventually drive
shell, the way people expect from cloud agents.
_For:_ headline demo.
_Against:_ incompatible with person-at-machine security (ORCH-297/301/319).
Worst case is remote code execution on a real desktop mediated by a helpful
model. **Reject.**

**Option B — Build a narrow inbound path with Q1–Q5 controls**
Owner-only, L1 hard cap, start tainted, refuse confirm/L2+, rate limits, default
kill switch off. Replies in-thread; may read tainted Slack/GitHub context via
ORCH-325 connectors and write only inside the Jarvis workspace.
_For:_ some of the UX win; bounded blast radius; reuses ToolGateway.
_Against:_ still expands the attack surface (webhook receiver on a machine that
can reach local tools if a bug forgets the session flag). Ongoing cost for a
feature that is a strict subset of "ask Jarvis while at the laptop" plus
"read-only connectors".

**Option C — Do not build inbound triggers for local shell tools (recommended)**
Ship ORCH-325 read-only GitHub/Slack **pull** (owner asks at the machine: _"what
did I miss in #eng?"_). Do **not** add `@jarvis` / issue-comment **push** that
creates ToolGateway turns on the laptop. If a cloud-sandbox agent product is
desired later, that is a different runtime (Prime/cloud worker), not a remote
skin over local `run_powershell`.
_For:_ honest about the asymmetry with Codex; keeps A1/A3 security coherent;
avoids a forever-exception in the gateway; "not building" is cheaper than
building a safe-looking footgun.
_Against:_ no magical away-from-laptop agent. Users still need the laptop (or a
true remote desktop they already trust) for actions.

### Recommendation

**Option C for local shell / L2+ / confirm-gated tools — do not build.**

If product later insists on *some* `@jarvis` reply path, the only design that
does not trash ORCH-297/301 is **Option B** with every Q1–Q5 recommendation
above, still **never** raising the inbound ceiling to shell. That would be a
**new** ticket after ORCH-325 has been lived with — not sneak-scope on this one.

---

## Decision summary (for GRoK)

| # | Question | Recommendation |
|---|----------|----------------|
| 1 | Who may trigger + verification | Owner allowlist by platform user id; verify via signed webhooks — not channel-wide, not display names |
| 2 | Tier ceiling | **L1 hard cap**; no shell, no home writes, no L3+ |
| 3 | Confirm when away | **Refuse** confirm-gated / L2+; **never** put a nonce in Slack/GitHub |
| 4 | Starts tainted? | **Yes**; clear only on local owner utterance |
| 5 | Rate limits + kill switch | Per-actor + global limits; **default off** kill switch in env + Settings |
| 6 | Build it? | **Do not build inbound triggers for local shell tools.** Prefer ORCH-325 pull-only. Narrow L1 reply-path only under a later explicit ticket |

## Out of scope for ORCH-326

- Webhook handlers, Slack Bolt / GitHub App code, Settings UI, gateway flags.
- Widening ORCH-325 into write connectors.
- Changes to spoken nonce transport.
- Any path that lets inbound clear taint or raise tier.

## Acceptance criteria for *this* design ticket

- [x] Doc exists under `docs/` covering Q1–Q6 with options, trade-offs, and one
      recommendation each (ORCH-296..301 style).
- [x] Honest "do not build for local shell tools" recommendation is argued.
- [x] No inbound trigger implementation code in the same change.

## Dependencies

- **Blocked by ORCH-325** for any future implementation that mentions Slack/GitHub
  context.
- Depends in spirit on ORCH-296 (policy registry), ORCH-297 (taint), ORCH-301
  (nonce), ORCH-319 (model must not self-approve).
