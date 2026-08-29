"""Tamper-evident audit trail with structural redaction (ORCH-298). ==CLAUDE==

Implements the ruling: **both** JSONL and SQLite, **hash chain**, **redact args**.

Three properties, in the order they matter:

1. **Secrets never reach the log.** Redaction walks the structure and replaces
   the VALUE under a sensitive key. The previous regex approach replaced the
   matched *word*, which redacted the key name and left the secret intact —
   ``{"password": "hunter2"}`` became ``{"[redacted]": "hunter2"}``. Redaction
   has to understand structure, not just text.

2. **The record is readable without the app.** JSONL in the workspace, one
   object per line, greppable in Notepad. A corrupt or locked SQLite file must
   never take the audit with it — that is exactly when it is wanted.

3. **Edits are detectable.** Each line carries the SHA-256 of the previous
   line, so removing or altering an entry breaks the chain from that point on.
   This is evidence rather than a diary; it costs about ten lines.

The SQLite side stays the queryable index and is Grok's existing ``tool_audit``
table — this module does not touch it. It writes the durable JSONL record and
provides the redactor the gateway can use for both.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

REDACTED = "[redacted]"
_MAX_STR = 400
_MAX_DEPTH = 6

# Keys whose VALUE is a secret, however the key is spelled. Compared against a
# normalised key (lowercased, separators stripped) so apiKey / API_KEY /
# "api key" / api-key all collapse to the same thing.
_SENSITIVE_KEYS = frozenset(
    {
        "password", "passwd", "pwd", "passphrase",
        "apikey", "apisecret", "secret", "clientsecret",
        "token", "accesstoken", "refreshtoken", "idtoken", "authtoken",
        "authorization", "auth", "cookie", "setcookie",
        "privatekey", "secretkey", "sessionkey",
        "pin", "cvv", "cvc", "ssn", "creditcard", "cardnumber",
    }
)

# Secret-SHAPED strings, which must be caught even in an innocent field such as
# a shell command. Ordered most-specific first.
#
# The PEM rule spans from BEGIN to END rather than matching the header alone.
# A header-only pattern redacts the marker and writes the base64 body to disk
# underneath it, which is the entire key.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE KEY|CERTIFICATE)-----"
               r"[\s\S]*?(?:-----END [A-Z ]*(?:PRIVATE KEY|CERTIFICATE)-----|\Z)"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),              # OpenAI-style
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}"),  # GitHub
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),                   # AWS access key id
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),       # Slack
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+"),  # JWT
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s:/@]+@"),  # user:pass@host
)

# Card numbers need Luhn, not just a length. A run of 13-19 digits also matches
# the run ids this app generates (``2026081200417739``), and redacting those
# costs the log its primary correlation key for no security gain.
_DIGIT_RUN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _mask_cards(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        bare = re.sub(r"[ -]", "", match.group(0))
        return REDACTED if 13 <= len(bare) <= 19 and _luhn_ok(bare) else match.group(0)

    return _DIGIT_RUN.sub(replace, text)


def _normalise_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _is_sensitive_key(key: str) -> bool:
    """Whether a key's VALUE is a secret, across the spellings keys really use.

    Matching the whole normalised key is not enough: real payloads carry
    ``x-api-key`` (an HTTP header), ``db_password`` and ``my_password``. So the
    key is split into segments and every contiguous *suffix* is tested —
    ``x-api-key`` yields xapikey / apikey / key, and ``apikey`` hits.

    Suffixes rather than substrings, deliberately. A substring test would redact
    ``tokenize`` because it contains "token", and ``authorized_by`` because it
    contains "auth", losing information for no safety gain.
    """
    raw = str(key)
    if _normalise_key(raw) in _SENSITIVE_KEYS:
        return True
    segments = [s for s in re.split(r"[^A-Za-z0-9]+", raw) if s]
    # Split camelCase too, so apiKey -> [api, Key].
    parts: list[str] = []
    for seg in segments:
        parts.extend(p for p in re.split(r"(?<=[a-z0-9])(?=[A-Z])", seg) if p)
    for i in range(len(parts)):
        if "".join(parts[i:]).lower() in _SENSITIVE_KEYS:
            return True
    return False


# Command lines carry secrets positionally, not structurally: `--password X`
# has no key for the walker to see, so the flag has to be recognised and the
# value after it dropped. Keeps the flag itself so the log still shows what
# kind of command ran.
_FLAG_SECRET = re.compile(
    r"(?i)(-{1,2}(?:password|passwd|pwd|pass|token|api[-_]?key|apikey|secret|"
    r"client[-_]?secret|auth|bearer)\s*[=: ]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
)
# The same idea for `KEY=value` environment-style assignments.
_ENV_SECRET = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|TOKEN|API_?KEY|SECRET|CREDENTIAL)[A-Z0-9_]*\s*=\s*)"
    r"(\"[^\"]*\"|'[^']*'|\S+)"
)


# A dictated secret has no key at all: the user says "my password is open
# sesame" and the whole phrase lands in one transcript field. Scoped to
# transcript-like keys on purpose — applied everywhere it would gut ordinary
# prose such as a ticket titled "Password reset page 500s".
_SPOKEN_KEYS = frozenset({"transcript", "utterance", "said", "speech", "dictation", "heard"})
_SPOKEN_SECRET = re.compile(
    r"(?i)\b(?:my\s+|the\s+)?(password|passcode|passphrase|pin|api\s*key|secret)\s+"
    r"(?:is|was|equals)\s+(?P<value>.+)$"
)


def scrub_text(text: str) -> str:
    """Mask secret-shaped substrings inside a free-text value."""
    out = str(text)
    out = _FLAG_SECRET.sub(lambda m: m.group(1) + REDACTED, out)
    out = _ENV_SECRET.sub(lambda m: m.group(1) + REDACTED, out)
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(REDACTED, out)
    return _mask_cards(out)


def scrub_speech(text: str) -> str:
    """Scrub a spoken transcript, where a secret arrives as prose."""
    out = _SPOKEN_SECRET.sub(
        lambda m: f"{m.group(1)} is {REDACTED}", str(text), count=1
    )
    return scrub_text(out)


# The name/value shape: ``{"name": "password", "value": "hunter2"}``. The
# sensitive word is the *value* of a neutral key, so walking keys alone writes
# the secret out. Environment and form payloads arrive in exactly this shape.
_NAME_KEYS = frozenset({"name", "key", "field", "var", "variable", "setting"})
_VALUE_KEYS = frozenset({"value", "val", "data", "content", "contents"})


def _names_a_secret(mapping: dict[Any, Any]) -> bool:
    return any(
        _normalise_key(k) in _NAME_KEYS
        and isinstance(v, str)
        and _is_sensitive_key(v)
        for k, v in mapping.items()
    )


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return a copy safe to write to disk.

    Values under a sensitive key are replaced wholesale; every other string is
    scrubbed for secret-shaped content and truncated. Structure is preserved so
    the log stays useful for answering "what did you just do".
    """
    if _depth > _MAX_DEPTH:
        return "[too deep]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        named_secret = _names_a_secret(value)
        for key, val in value.items():
            norm = _normalise_key(key)
            if _is_sensitive_key(key):
                out[str(key)] = REDACTED          # the VALUE goes, key stays readable
            elif named_secret and norm in _VALUE_KEYS:
                out[str(key)] = REDACTED          # {"name": "password", "value": ...}
            elif norm in _SPOKEN_KEYS and isinstance(val, str):
                out[str(key)] = scrub_speech(val)[:_MAX_STR]
            else:
                out[str(key)] = redact(val, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth=_depth + 1) for v in value[:50]]
    if isinstance(value, str):
        scrubbed = scrub_text(value)
        return scrubbed if len(scrubbed) <= _MAX_STR else scrubbed[:_MAX_STR] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return scrub_text(str(value))[:_MAX_STR]


GENESIS = "0" * 64


def _digest(prev_hash: str, payload: str) -> str:
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()


@dataclass
class AuditLog:
    """Append-only, hash-chained JSONL.

    Deliberately independent of SQLite: this is the copy that survives a locked
    or corrupt database, and that a person can read with no tooling.
    """

    path: Path
    # Retention: cap by size, not by age. A laptop assistant can be quiet for a
    # week and then run a thousand tools in an hour, so age is a poor proxy for
    # how much disk this costs. One rotation is kept, so the worst case is
    # bounded at twice the cap and the recent past is always available.
    max_bytes: int = 8_000_000
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def rotated_path(self) -> Path:
        return self.path.with_name(self.path.name + ".1")

    # -- writing ---------------------------------------------------------

    def _last_hash(self) -> str:
        last = None
        for record in self.read():
            last = record
        return str(last.get("hash")) if last else GENESIS

    def _rotate_if_full(self) -> None:
        """Roll the file over once it exceeds the cap, carrying the chain.

        The new file opens with a marker record holding the previous file's
        final hash, so the two segments still link and a deletion at the seam
        is as detectable as one in the middle. Without the carry, rotation
        would silently reset the chain to genesis — which is exactly the gap an
        attacker would aim for.
        """
        if self.max_bytes <= 0 or not self.path.is_file():
            return
        if self.path.stat().st_size < self.max_bytes:
            return
        carried = self._last_hash()
        self.rotated_path.unlink(missing_ok=True)
        self.path.rename(self.rotated_path)
        marker = {"_rotated_from": self.rotated_path.name, "ts": time.time()}
        payload = json.dumps(marker, sort_keys=True, default=str, ensure_ascii=False)
        record = dict(marker)
        record["prev"] = carried
        record["hash"] = _digest(carried, payload)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Write one record. Returns the stored record, including its hash."""
        with self._lock:
            self._rotate_if_full()
            prev = self._last_hash()
            body = redact(dict(entry))
            body.setdefault("ts", time.time())
            # The hash covers the body and the previous hash, with sorted keys
            # so the digest is reproducible from the file alone.
            payload = json.dumps(body, sort_keys=True, default=str, ensure_ascii=False)
            record = dict(body)
            record["prev"] = prev
            record["hash"] = _digest(prev, payload)
            line = json.dumps(record, sort_keys=True, default=str, ensure_ascii=False)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())      # survive a crash mid-action
            return record

    # -- reading ---------------------------------------------------------

    def read(self) -> Iterator[dict[str, Any]]:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    yield {"_unparseable": line[:200]}

    def verify(self) -> tuple[bool, int, str]:
        """Check the chain. Returns (ok, index_of_first_bad_record, reason).

        index is -1 when the chain is intact. A rotated file's first record is
        a carry marker, so the chain starts from the hash it carries rather
        than from genesis; ``verify_across_rotation`` checks the seam itself.
        """
        records = list(self.read())
        prev = GENESIS
        if records and "_rotated_from" in records[0]:
            prev = str(records[0].get("prev", GENESIS))
        for i, record in enumerate(records):
            if "_unparseable" in record:
                return False, i, "record is not valid JSON"
            stored_hash = record.get("hash")
            stored_prev = record.get("prev")
            if stored_prev != prev:
                return False, i, "broken link: a record was removed or reordered"
            body = {k: v for k, v in record.items() if k not in ("hash", "prev")}
            payload = json.dumps(body, sort_keys=True, default=str, ensure_ascii=False)
            if _digest(prev, payload) != stored_hash:
                return False, i, "record was altered after it was written"
            prev = str(stored_hash)
        return True, -1, ""

    def verify_across_rotation(self) -> tuple[bool, str]:
        """Check the seam as well as each file, when a rotation has happened.

        Rotation is the one moment the chain could be quietly reset, so the
        carried hash is compared against the rotated file's real last hash
        rather than taken on trust.
        """
        ok, index, reason = self.verify()
        if not ok:
            return False, f"current file: {reason} (record {index})"
        if not self.rotated_path.is_file():
            return True, ""

        older = AuditLog(self.rotated_path, max_bytes=0)
        ok, index, reason = older.verify()
        if not ok:
            return False, f"rotated file: {reason} (record {index})"

        records = list(self.read())
        if not records or "_rotated_from" not in records[0]:
            return False, "a rotated file exists but the current one has no carry marker"
        if records[0].get("prev") != older._last_hash():
            return False, "the seam does not link: records were lost at rotation"
        return True, ""

    def tail(self, n: int = 10) -> list[dict[str, Any]]:
        return list(self.read())[-n:]
