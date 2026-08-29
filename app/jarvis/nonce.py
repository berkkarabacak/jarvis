"""Single-use spoken confirmation nonce (ORCH-301). ==CLAUDE==

Implements the ruling: a risky action is authorised by speaking a one-time code
back, not by saying "yes".

Why the code exists. The screen shows a circle, so confirmation is spoken, and
"yes" is the single most likely word to arrive from a television, a colleague,
or the user answering something else. A confirmation any nearby human or
speaker can supply is not a control. A two-digit code the assistant just read
out is not something ambient speech produces, and hearing it back is evidence
the user actually listened to the readback.

Why it tolerates bad transcription. The Windows recogniser turned "turn on dark
mode" into "turn on dark road" on this project. Digits are worse: "four" comes
back as "for", "two" as "to" or "too", "eight" as "ate". A confirmation step
that mishears is worse than none, because it manufactures consent — so the
parser accepts the homophones a recogniser actually produces, while still
requiring the *right* digits in the *right* order.

**Why the utterance is parsed structurally rather than scanned for digits.**
A red-team corpus (ORCH-303) broke the first version of this module with

    "and we can confirm the final score was four seven"

— a plausible sentence off a television that contains the verb *and* the code
in order, and which a scan-for-intent-then-scan-for-digits matcher approves.
So an utterance is now required to have the shape

    [filler]*  confirm  [filler | digit]+

with *filler* a small closed allowlist. Anything outside that vocabulary
between the verb and the digits ("the final score was", "and delete the
backups", "sorry") means the digits are not being offered as a confirmation,
and the utterance is refused. That also closes the rider-command case, where a
correct code is spoken with a second instruction stapled to it.

Two tokens are both filler and digit — "oh" is either zero or an interjection,
"too" is either two or a modifier — so both readings are generated and the code
approves if either matches. Ambiguity is resolved in favour of the user, never
in favour of a wider accept surface: every reading must still equal the code.

The module is pure policy and holds no I/O, so the gateway can own storage.
"""

from __future__ import annotations

import itertools
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

# How long a challenge stays answerable. Long enough to hear the readback and
# reply, short enough that a stray later utterance cannot land on it.
DEFAULT_TTL_SECONDS = 25.0

# Below this, the recogniser is guessing. A security gate must not act on a
# guess, so a low-confidence utterance re-prompts instead of resolving — and
# critically, does not burn the challenge's single use.
MIN_CONFIDENCE = 0.6

_DIGIT_WORDS: dict[str, str] = {
    "zero": "0", "oh": "0", "o": "0", "nought": "0",
    "one": "1", "won": "1", "wun": "1",
    "two": "2", "to": "2", "too": "2",
    "three": "3", "tree": "3", "free": "3",
    "four": "4", "for": "4", "fore": "4",
    "five": "5", "fife": "5",
    "six": "6", "sicks": "6",
    "seven": "7",
    "eight": "8", "ate": "8",
    "nine": "9", "niner": "9",
}

# "forty seven" -> 47. Only the tens that can precede a unit.
_TENS: dict[str, int] = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_TEENS: dict[str, int] = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}

# The closed vocabulary permitted around the code. Deliberately small: every
# word added here widens what counts as a confirmation. Notably absent is "say",
# so the assistant's own prompt played back through room speakers
# ("to confirm, say: confirm four seven") is not itself a confirmation.
_FILLER = frozenset({
    "a", "alright", "code", "eh", "er", "erm", "hmm", "is", "it", "its", "jarvis",
    "iris", "mm", "my", "number", "oh", "ok", "okay", "okey", "please", "right",
    "sure", "thanks", "thank", "that", "the", "then", "to", "too", "um", "uh",
    "well", "yeah", "yep", "yes", "you",
})

# Tokens that are both filler and a digit. Each one doubles the readings, so
# the set is kept tiny and the count is capped.
_AMBIGUOUS = frozenset(t for t in _FILLER if t in _DIGIT_WORDS)
_MAX_AMBIGUOUS = 4

# The user must express intent as well as the digits, so a number overheard in
# unrelated speech ("flight forty seven now boarding") cannot authorise
# anything on its own.
_INTENT_WORDS = frozenset({"confirm", "approve", "proceed", "authorise", "authorize"})
_INTENT = re.compile(r"\b(confirm|approve|proceed|authorise|authorize)\b", re.IGNORECASE)
_CANCEL = re.compile(
    r"\b(cancel|deny|abort|stop|no|nope|don'?t|do not|never ?mind|forget it)\b",
    re.IGNORECASE,
)

# Placeholders a recogniser emits for audio it could not transcribe. Treating
# these as text to match against would let silence resolve a challenge.
_NON_SPEECH = frozenset({"inaudible", "unintelligible", "silence", "noise", "blank"})


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", str(text or "").lower())


def _read_digits(toks: list[str]) -> str:
    """Digit sequence from an already-tokenised utterance."""
    out: list[str] = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok.isdigit():
            out.append(tok)
            i += 1
            continue
        if tok in _TENS:
            value = _TENS[tok]
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            unit = _DIGIT_WORDS.get(nxt)
            # "forty seven" is 47; a bare "forty" is 40.
            if unit and unit != "0":
                out.append(str(value + int(unit)))
                i += 2
                continue
            out.append(str(value))
            i += 1
            continue
        if tok in _TEENS:
            out.append(str(_TEENS[tok]))
            i += 1
            continue
        if tok in _DIGIT_WORDS:
            out.append(_DIGIT_WORDS[tok])
            i += 1
            continue
        i += 1
    return "".join(out)


def spoken_digits(text: str) -> str:
    """Extract the digit sequence a person actually said.

    Handles bare digits ("47"), digit-by-digit ("four seven"), the natural
    reading ("forty seven"), and the homophones a recogniser produces. This is
    the raw greedy reading; ``code_readings`` is what the gate uses.
    """
    return _read_digits(_tokens(text))


def is_non_speech(text: str) -> bool:
    """Whether a transcript is a placeholder rather than words.

    ``""``, whitespace, and ``[inaudible]`` all mean *no input was heard*. They
    must never be matched against a code, and must not consume the challenge.
    """
    toks = _tokens(text)
    return not toks or all(t in _NON_SPEECH for t in toks)


def code_readings(text: str) -> list[str]:
    """Every code the utterance could be offering, best reading first.

    Empty when the utterance is not shaped like a confirmation at all — no
    intent word, or vocabulary outside the closed filler set surrounding the
    digits. An empty list is a refusal, not "no digits found".
    """
    toks = _tokens(text)
    intent_at = next((i for i, t in enumerate(toks) if t in _INTENT_WORDS), None)
    if intent_at is None:
        return []

    lead, tail = toks[:intent_at], toks[intent_at + 1:]

    # Anything before the verb must be filler. "and we can confirm ..." fails
    # here, which is the broadcast-sentence case.
    if any(t not in _FILLER for t in lead):
        return []
    # Anything after it must be filler or a number. "the final score was ..."
    # and "... and delete the backups" both fail here.
    if any(
        t not in _FILLER and not t.isdigit() and t not in _DIGIT_WORDS
        and t not in _TENS and t not in _TEENS
        for t in tail
    ):
        return []

    ambiguous = [i for i, t in enumerate(tail) if t in _AMBIGUOUS]
    readings: list[str] = [_read_digits(tail)]
    if 0 < len(ambiguous) <= _MAX_AMBIGUOUS:
        # Re-read with each combination of ambiguous tokens treated as filler,
        # so "confirm four seven too" also reads as 47 and "confirm oh six"
        # still reads as 06.
        for drop_count in range(1, len(ambiguous) + 1):
            for drop in itertools.combinations(ambiguous, drop_count):
                kept = [t for i, t in enumerate(tail) if i not in drop]
                readings.append(_read_digits(kept))

    seen: set[str] = set()
    return [r for r in readings if r and not (r in seen or seen.add(r))]


def say_code(code: str) -> str:
    """Render a code as the assistant should speak it: 47 -> 'four seven'."""
    names = {
        "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
        "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    }
    return " ".join(names.get(ch, ch) for ch in str(code))


# Outcomes of answering a challenge.
APPROVED = "approved"
DENIED = "denied"      # the user explicitly cancelled
MISMATCH = "mismatch"  # intent present, wrong or missing code
EXPIRED = "expired"
SPENT = "spent"        # already used; a replay
IGNORED = "ignored"    # unrelated speech — leaves the challenge alive
UNCLEAR = "unclear"    # heard, but not well enough to act on


@dataclass
class Challenge:
    """One pending confirmation."""

    code: str
    action_summary: str
    tool: str = ""
    tier: str = ""
    created_at: float = field(default_factory=time.time)
    ttl: float = DEFAULT_TTL_SECONDS
    used: bool = False
    arguments: dict[str, Any] = field(default_factory=dict)
    reversible: bool | None = None

    def expired(self, *, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) - self.created_at > self.ttl

    def prompt(self) -> str:
        """What the assistant says. Names the action, then the code.

        The readback carries object and magnitude so the user knows the scale
        of what they are agreeing to before they agree to it, and says whether
        it can be undone — which is usually the thing that decides the answer.
        ``reversible=None`` says nothing rather than guessing: claiming an
        action is undoable when nobody checked is worse than staying quiet.
        """
        undo = {True: " This can be undone.", False: " This cannot be undone."}
        return (
            f"{self.action_summary}."
            f"{undo.get(self.reversible, '')}"
            f" To confirm, say: confirm {say_code(self.code)}."
        )


def hesitate(alternates: list[str], resolve: Any) -> tuple[bool, str]:
    """Whether the n-best transcriptions disagree about what was asked.

    ORCH-301: if the top two alternates resolve to *different tools*, never
    guess — ask. The recorded case on this project is "turn on dark mode"
    coming back as "turn on dark road"; the dangerous pairs are "shut down" /
    "shut up" and "delete" / "the leads", where the second-best reading is a
    different action rather than a different phrasing of the same one.

    ``resolve`` maps a transcript to a tool name (or "" / None when it maps to
    nothing). Returns (should_ask, what_to_say). Deliberately compares tools
    rather than text: two transcripts that read differently but drive the same
    tool are not a hazard, and asking about those is how confirmation fatigue
    starts.
    """
    tools: list[str] = []
    for text in list(alternates)[:2]:
        try:
            name = resolve(text)
        except Exception:
            name = None
        if name:
            tools.append(str(name))
    if len(tools) < 2 or tools[0] == tools[1]:
        return False, ""
    return True, (
        f"I heard that two ways — {alternates[0]!r} or {alternates[1]!r}. "
        "Which did you mean?"
    )


def mint(
    action_summary: str,
    *,
    tool: str = "",
    tier: str = "",
    arguments: dict[str, Any] | None = None,
    ttl: float = DEFAULT_TTL_SECONDS,
    digits: int = 2,
    reversible: bool | None = None,
) -> Challenge:
    """Create a challenge with a fresh random code.

    Two digits is 100 possibilities — ample against ambient speech, which is the
    threat, and short enough to say back without irritation. Uses ``secrets``
    rather than ``random`` so the code is not predictable from earlier ones.
    """
    code = "".join(str(secrets.randbelow(10)) for _ in range(max(1, digits)))
    return Challenge(
        code=code,
        action_summary=action_summary,
        tool=tool,
        tier=tier,
        arguments=dict(arguments or {}),
        ttl=ttl,
        reversible=reversible,
    )


def answer(
    challenge: Challenge,
    utterance: str,
    *,
    now: float | None = None,
    confidence: float | None = None,
) -> tuple[str, str]:
    """Judge an utterance against a challenge. Returns (outcome, spoken reply).

    Ordering matters. Expiry and replay are checked before anything is parsed,
    so a late or repeated correct code still fails. Non-speech and
    low-confidence audio return before the code check and leave the challenge
    answerable, because a cough must not consume the user's one attempt.
    Cancellation is honoured before the code check, because "no, cancel" must
    never be mined for digits.
    """
    if challenge.used:
        return SPENT, "That confirmation was already used. Ask me again if you still want it."
    if challenge.expired(now=now):
        return EXPIRED, "That took too long, so I cancelled it. Ask me again if you still want it."

    text = str(utterance or "")
    if is_non_speech(text):
        return IGNORED, ""
    if confidence is not None and confidence < MIN_CONFIDENCE:
        return UNCLEAR, f"I did not catch that. Say: confirm {say_code(challenge.code)}."

    if _CANCEL.search(text):
        challenge.used = True
        return DENIED, "Cancelled. I did not do it."

    if not _INTENT.search(text):
        # Unrelated speech. Deliberately NOT a mismatch: the user may simply be
        # talking about something else, and burning the challenge on that would
        # be its own small failure.
        return IGNORED, ""

    readings = code_readings(text)
    if not readings:
        return MISMATCH, f"I need the code on its own. Say: confirm {say_code(challenge.code)}."
    if challenge.code not in readings:
        return MISMATCH, f"That code did not match. Say: confirm {say_code(challenge.code)}."

    challenge.used = True                  # single use, enforced here
    return APPROVED, ""


@dataclass
class ConfirmBook:
    """The pending challenges for one session.

    There is deliberately no "confirm the most recent thing" helper. A bare
    "confirm" must not resolve anything, so an utterance is matched by its code
    against every live challenge — which also means the user never has to
    remember which action they are answering, and a code issued for one action
    can never approve a different one queued behind it.
    """

    ttl: float = DEFAULT_TTL_SECONDS
    _items: dict[str, Challenge] = field(default_factory=dict)

    def open(
        self,
        action_summary: str,
        *,
        tool: str = "",
        tier: str = "",
        arguments: dict[str, Any] | None = None,
        reversible: bool | None = None,
    ) -> Challenge:
        self.purge()
        kw = dict(
            tool=tool, tier=tier, arguments=arguments, ttl=self.ttl, reversible=reversible
        )
        challenge = mint(action_summary, **kw)
        # Codes must be distinguishable while both are live.
        while challenge.code in self._items:
            challenge = mint(action_summary, **kw)
        self._items[challenge.code] = challenge
        return challenge

    def purge(self, *, now: float | None = None) -> int:
        dead = [c for c, ch in self._items.items() if ch.expired(now=now) or ch.used]
        for code in dead:
            self._items.pop(code, None)
        return len(dead)

    def discard(self, code: str) -> bool:
        """Retire a challenge that was resolved by another route.

        The on-screen Allow button settles the same action the code was issued
        for, so the code must stop being answerable the moment it does —
        otherwise it stays live for the rest of its TTL against an action that
        has already run.
        """
        return self._items.pop(str(code), None) is not None

    def resolve(
        self,
        utterance: str,
        *,
        now: float | None = None,
        confidence: float | None = None,
    ) -> tuple[str, Challenge | None, str]:
        """Match an utterance to a live challenge by its code.

        Returns (outcome, challenge, spoken reply). A correct code approves
        exactly the action it was issued for.
        """
        self.purge(now=now)
        if not self._items:
            return IGNORED, None, ""

        text = str(utterance or "")
        if is_non_speech(text):
            return IGNORED, None, ""
        if not _INTENT.search(text) and not _CANCEL.search(text):
            return IGNORED, None, ""
        if confidence is not None and confidence < MIN_CONFIDENCE:
            return UNCLEAR, None, "I did not catch that. Say the code again."

        for said in code_readings(text):
            if said in self._items:
                challenge = self._items[said]
                outcome, reply = answer(challenge, text, now=now)
                if outcome in (APPROVED, DENIED, SPENT, EXPIRED):
                    self._items.pop(said, None)
                return outcome, challenge, reply

        if _CANCEL.search(text):
            # Cancel with no code clears everything pending: refusing is always
            # safe, so it does not need the same proof as approving.
            cancelled = list(self._items.values())
            self._items.clear()
            return DENIED, (cancelled[0] if cancelled else None), "Cancelled."

        # Intent but no matching code — the ambient-"yes" case, and the
        # transposed-code case. Neither approves anything.
        example = next(iter(self._items.values()))
        return (
            MISMATCH,
            None,
            f"That code did not match. Say: confirm {say_code(example.code)}.",
        )

    def pending(self) -> list[Challenge]:
        self.purge()
        return list(self._items.values())
