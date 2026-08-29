"""ORCH-298 — audit: redaction that works, and a chain that detects edits. ==CLAUDE=="""

from __future__ import annotations

import json

import pytest

from app.jarvis.audit import GENESIS, REDACTED, AuditLog, redact, scrub_text


@pytest.fixture
def log(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


# ------------------------------------------------------------------ redaction

@pytest.mark.parametrize(
    "key",
    ["password", "passwd", "api_key", "apiKey", "API-KEY", "token",
     "access_token", "secret", "client_secret", "authorization", "cookie",
     "private_key", "pin", "cvv"],
)
def test_the_value_under_a_sensitive_key_is_removed(key):
    """The regression this module exists for: the previous implementation
    replaced the matched WORD, so {"password": "hunter2"} became
    {"[redacted]": "hunter2"} and the secret survived."""
    out = redact({key: "hunter2-SECRET"})
    assert out[key] == REDACTED
    assert "hunter2-SECRET" not in json.dumps(out)


def test_sensitive_values_nested_in_structures_are_removed():
    payload = {
        "outer": {"inner": {"api_key": "AKIA1234567890AB"}},
        "list": [{"token": "ghp_abcdefghijklmnopqrst"}, {"ok": True}],
    }
    text = json.dumps(redact(payload))
    assert "AKIA1234567890AB" not in text
    assert "ghp_abcdefghijklmnopqrst" not in text
    assert '"ok": true' in text.lower()


@pytest.mark.parametrize(
    "secret",
    [
        "sk-proj-abcdefghijklmnopqrstuv",
        "ghp_abcdefghijklmnopqrstuvwxyz01",
        "AKIA1234567890ABCDEF",
        "Bearer abcdefghijklmnop",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abcdefghij",
        "-----BEGIN RSA PRIVATE KEY-----",
        "postgres://user:hunter2@db.example.com/app",
        "4111111111111111",
    ],
)
def test_secret_shaped_strings_are_caught_in_ordinary_fields(secret):
    """A secret pasted into a shell command is still a secret."""
    out = redact({"command": f"curl -H 'x: {secret}' https://example.com"})
    assert secret not in json.dumps(out), f"leaked: {secret}"


def test_ordinary_content_survives_so_the_log_stays_useful():
    payload = {
        "path": r"C:\Users\XPS13\Documents\report.xlsx",
        "command": "Get-ChildItem -Path .",
        "description": "open the reset password page",   # the word, not a secret
        "rows": 42,
        "ok": True,
        "nothing": None,
    }
    out = redact(payload)
    assert out["path"] == payload["path"]
    assert out["command"] == payload["command"]
    assert "reset" in out["description"] and "page" in out["description"]
    assert out["rows"] == 42 and out["ok"] is True and out["nothing"] is None


def test_long_strings_are_truncated_not_dropped():
    out = redact({"body": "x" * 5000})
    assert len(out["body"]) < 500 and out["body"].endswith("…")


def test_redaction_terminates_on_deep_or_cyclic_shapes():
    deep: dict = {}
    node = deep
    for _ in range(50):
        node["next"] = {}
        node = node["next"]
    assert "[too deep]" in json.dumps(redact(deep))


def test_scrub_text_is_usable_on_its_own():
    assert "sk-proj-abcdefghijklmn" not in scrub_text("key sk-proj-abcdefghijklmn here")


# ---------------------------------------------------------------- the chain

def test_append_writes_one_line_per_record(log):
    log.append({"tool": "disk_space", "decision": "auto"})
    log.append({"tool": "write_file", "decision": "confirmed"})
    lines = log.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert all(json.loads(ln)["hash"] for ln in lines)


def test_first_record_links_to_genesis(log):
    rec = log.append({"tool": "system_info"})
    assert rec["prev"] == GENESIS


def test_each_record_links_to_the_previous(log):
    a = log.append({"tool": "a"})
    b = log.append({"tool": "b"})
    assert b["prev"] == a["hash"]


def test_an_intact_chain_verifies(log):
    for i in range(5):
        log.append({"tool": f"t{i}"})
    ok, index, reason = log.verify()
    assert ok is True and index == -1 and reason == ""


def test_editing_a_record_is_detected(log):
    log.append({"tool": "disk_space"})
    log.append({"tool": "run_powershell", "reason": "executed"})
    log.append({"tool": "system_info"})

    lines = log.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["tool"] = "something_innocent"          # rewrite history
    lines[1] = json.dumps(tampered, sort_keys=True)
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, index, reason = log.verify()
    assert ok is False and index == 1
    assert "altered" in reason


def test_deleting_a_record_is_detected(log):
    for i in range(4):
        log.append({"tool": f"t{i}"})
    lines = log.path.read_text(encoding="utf-8").splitlines()
    del lines[1]                                      # remove the evidence
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, index, reason = log.verify()
    assert ok is False
    assert "removed" in reason or "reordered" in reason


def test_secrets_never_reach_the_file(log):
    log.append({"tool": "run_powershell",
                "arguments": {"command": "login --password hunter2SECRET",
                              "api_key": "sk-proj-abcdefghijklmnop"}})
    on_disk = log.path.read_text(encoding="utf-8")
    assert "hunter2SECRET" not in on_disk, "a --password value reached the log"
    assert "sk-proj-abcdefghijklmnop" not in on_disk
    assert REDACTED in on_disk
    # The command is still identifiable, which is the point of keeping a log.
    assert "login" in on_disk and "--password" in on_disk


@pytest.mark.parametrize(
    "command,secret",
    [
        ("login --password hunter2SECRET", "hunter2SECRET"),
        ("tool --api-key ABCDEF123456 --verbose", "ABCDEF123456"),
        ("cmd --token=zzzTOPSECRETzzz", "zzzTOPSECRETzzz"),
        ('run --secret "quoted secret value"', "quoted secret value"),
        ("DB_PASSWORD=swordfish ./migrate", "swordfish"),
        ("export API_KEY=abc123xyz", "abc123xyz"),
    ],
)
def test_secrets_passed_positionally_on_a_command_line_are_removed(command, secret):
    """A command line carries secrets after a flag, where there is no key for
    the structural walker to see."""
    out = json.dumps(redact({"command": command}))
    assert secret not in out, f"leaked from {command!r}"
    assert REDACTED in out


def test_the_log_is_readable_without_the_app(log):
    log.append({"tool": "create_excel", "decision": "auto", "ok": True})
    line = log.path.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)                        # plain JSON, no tooling
    assert parsed["tool"] == "create_excel" and parsed["ok"] is True


def test_a_denied_call_is_distinguishable_from_one_that_ran_and_failed(log):
    log.append({"tool": "run_powershell", "allowed": False, "ok": None, "reason": "blocked"})
    log.append({"tool": "create_excel", "allowed": True, "ok": False, "reason": "executed"})
    denied, failed = list(log.read())
    assert denied["allowed"] is False and denied["ok"] is None
    assert failed["allowed"] is True and failed["ok"] is False


def test_concurrent_appends_do_not_break_the_chain(log):
    """The gateway serves voice and the bridge; both write here."""
    import threading

    def worker(n: int) -> None:
        for i in range(5):
            log.append({"tool": f"w{n}-{i}"})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok, index, reason = log.verify()
    assert ok is True, f"chain broken at {index}: {reason}"
    assert len(list(log.read())) == 20


def test_tail_returns_the_most_recent(log):
    for i in range(10):
        log.append({"tool": f"t{i}"})
    assert [r["tool"] for r in log.tail(3)] == ["t7", "t8", "t9"]


# ---------------------------------------------------------------- retention

def test_the_log_rotates_once_it_passes_the_cap(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", max_bytes=2000)
    for i in range(200):
        log.append({"tool": f"t{i}", "note": "x" * 100})
    assert log.rotated_path.is_file(), "nothing was rotated"
    assert log.path.stat().st_size < 2000 + 400   # the cap holds, plus one record


def test_rotation_keeps_exactly_one_older_file(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", max_bytes=1000)
    for i in range(400):
        log.append({"tool": f"t{i}", "note": "x" * 100})
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["audit.jsonl", "audit.jsonl.1"], files


def test_the_chain_survives_rotation(tmp_path):
    """Rotation is the one moment the chain could be quietly reset, so the new
    file carries the old file's last hash and the seam is checkable."""
    log = AuditLog(tmp_path / "audit.jsonl", max_bytes=1200)
    for i in range(100):
        log.append({"tool": f"t{i}", "note": "x" * 100})
    assert log.rotated_path.is_file()

    ok, reason = log.verify_across_rotation()
    assert ok is True, reason

    first = next(iter(log.read()))
    assert "_rotated_from" in first
    assert first["prev"] != GENESIS, "the chain restarted instead of carrying"


def test_editing_the_rotated_file_is_still_detected(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", max_bytes=1200)
    for i in range(100):
        log.append({"tool": f"t{i}", "note": "x" * 100})

    lines = log.rotated_path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["tool"] = "something_innocent"
    lines[1] = json.dumps(tampered, sort_keys=True)
    log.rotated_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, reason = log.verify_across_rotation()
    assert ok is False and "rotated file" in reason


def test_replacing_the_rotated_file_wholesale_breaks_the_seam(tmp_path):
    """The attack rotation invites: swap the old segment for a clean one whose
    own chain verifies. The carried hash must not match."""
    log = AuditLog(tmp_path / "audit.jsonl", max_bytes=1200)
    for i in range(100):
        log.append({"tool": f"t{i}", "note": "x" * 100})

    forged = AuditLog(tmp_path / "forged.jsonl", max_bytes=0)
    for i in range(5):
        forged.append({"tool": f"innocent{i}"})
    assert forged.verify()[0] is True                  # internally consistent
    log.rotated_path.write_text(
        forged.path.read_text(encoding="utf-8"), encoding="utf-8"
    )

    ok, reason = log.verify_across_rotation()
    assert ok is False and "seam" in reason


# ------------------------------------------------- red-team corpus (ORCH-303)
#
# Generated adversarially against this module's contract, then run against it.
# It found four real defects in *this* redactor, all now fixed and pinned here:
#   * {"name": "password", "value": X} — the sensitive word is a VALUE, so a
#     key walker writes X straight to disk
#   * a PEM header-only rule redacted the marker and logged the key body under it
#   * a 13-19 digit rule redacted this app's own run ids; now Luhn-checked
#   * a dictated secret ("my password is open sesame") has no key at all
# Plus four key-spelling leaks found earlier in the same pass: x-api-key,
# X-Auth-Token, my_password, db_password.
#
# Assertions are "the secret is absent, the context survives" rather than exact
# output equality — several cases have more than one acceptable granularity
# (redact the DSN password segment, or the whole DSN), and pinning a string
# would over-specify the contract.

REDACT_CORPUS = [
    # (name, payload, must_not_appear, must_still_appear)
    ("top-level password",
     {"tool": "write_env", "path": r"C:\Users\dev\.env", "password": "hunter2-Tr0ub4dor"},
     ["hunter2-Tr0ub4dor"], [".env"]),
    ("alias spelling keeps the connection identifiable",
     {"host": "db.internal", "port": 3306, "user": "svc_audit", "passwd": "PW-FIXTURE"},
     ["PW-FIXTURE"], ["db.internal", "svc_audit", "3306"]),
    ("camelCase and run-together spellings",
     {"apiKey": "CAMEL-FIXTURE", "apikey": "FLAT-FIXTURE"},
     ["CAMEL-FIXTURE", "FLAT-FIXTURE"], []),
    ("hyphenated header key, sibling header kept",
     {"headers": {"x-api-key": "HYPHEN-FIXTURE", "Accept": "application/json"}},
     ["HYPHEN-FIXTURE"], ["application/json"]),
    ("space-separated key from a form payload",
     {"fields": {"api key": "SPACED-FIXTURE", "display name": "Berk"}},
     ["SPACED-FIXTURE"], ["Berk"]),
    ("prefixed key variants",
     {"my_password": "MINE-FIXTURE", "db_password": "DB-FIXTURE",
      "X-Auth-Token": "AUTH-FIXTURE"},
     ["MINE-FIXTURE", "DB-FIXTURE", "AUTH-FIXTURE"], []),
    ("redact and keep inside one object",
     {"secret": "SHARED-FIXTURE", "client_id": "orch-desktop", "client_secret": "CS-FIXTURE"},
     ["SHARED-FIXTURE", "CS-FIXTURE"], ["orch-desktop"]),
    ("cookie value is wholly a credential",
     {"url": "https://portal.example.com/reports",
      "cookie": "session=abc123FIXTURE; csrf=def456FIXTURE"},
     ["abc123FIXTURE", "def456FIXTURE"], ["portal.example.com"]),
    ("refresh keeps the audit-useful fields",
     {"access_token": "AT-FIXTURE", "refresh_token": "RT-FIXTURE",
      "expires_in": 3600, "scope": "runs:read"},
     ["AT-FIXTURE", "RT-FIXTURE"], ["3600", "runs:read"]),
    ("short numeric secrets are still secrets",
     {"vault": "personal", "pin": "4417", "cvv": "019"},
     ["4417", "019"], ["personal"]),
    ("sensitive keys inside a list of dicts",
     {"accounts": [{"user": "alice", "token": "T1-FIXTURE"},
                   {"user": "bob", "token": "T2-FIXTURE"}]},
     ["T1-FIXTURE", "T2-FIXTURE"], ["alice", "bob"]),
    ("the sensitive word is a VALUE, not a key",
     {"vars": [{"name": "HOME", "value": r"C:\Users\dev"},
               {"name": "password", "value": "NAMEVALUE-FIXTURE"}]},
     ["NAMEVALUE-FIXTURE"], ["HOME"]),
    ("four levels deep through a list",
     {"stages": [{"name": "build",
                  "env": {"nested": {"secrets": {"DB_PASSWORD": "DEEP-FIXTURE"}}}}]},
     ["DEEP-FIXTURE"], ["build"]),
    ("real env names from app/config.py",
     {"env": {"XAI_API_KEY": "xai-FIXTUREabcdefghij0123",
              "TENCENTDB_PASSWORD": "TDB-FIXTURE",
              "DATABASE_PROVIDER": "sqlite", "PORT": "8787"}},
     ["xai-FIXTUREabcdefghij0123", "TDB-FIXTURE"], ["sqlite", "8787"]),
    ("secret-shaped value under an ordinary key",
     {"channel": "#orch", "body": "paste this in: sk-proj-FIXTUREaaaabbbbccccdddd"},
     ["sk-proj-FIXTUREaaaabbbbccccdddd"], ["#orch"]),
    ("PAT mid-sentence, sentence survives",
     {"issue": "ORCH-298", "comment": "CI broke on ghp_FIXTURE0123456789abcdefghij, rotating"},
     ["ghp_FIXTURE0123456789abcdefghij"], ["ORCH-298", "rotating"]),
    ("PEM body, not just the header",
     {"path": "id_ed25519",
      "content": "-----BEGIN OPENSSH PRIVATE KEY-----\n"
                 "b3BlbnNzaGtleXYxRklYVFVSRQ\n-----END OPENSSH PRIVATE KEY-----"},
     ["b3BlbnNzaGtleXYxRklYVFVSRQ"], ["id_ed25519"]),
    ("bearer token inside a captured shell command",
     {"message": "retrying: curl -H 'Authorization: Bearer FIXTUREabc.def-token' https://api.x/v1"},
     ["FIXTUREabc.def-token"], ["curl", "retrying"]),
    ("JWT, with the debugging value kept",
     {"stage": "auth",
      "last_response": "401 for eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.FIXTUREsig"},
     ["FIXTUREsig"], ["401", "auth"]),
    ("credentials embedded in a connection string",
     {"dsn": "postgresql://orch_admin:FIXTUREpw88@db.internal:5432/orch", "steps": 3},
     ["FIXTUREpw88"], ["3"]),
    ("card number by shape, in an ordinary text field",
     {"text": "charge it to 4111111111111111 expiry 04 29"},
     ["4111111111111111"], ["expiry"]),
    ("a secret dictated as prose has no key to walk",
     {"tool": "remember", "transcript": "my password is open sesame nine nine"},
     ["open sesame nine nine"], ["remember"]),
]

KEEP_CORPUS = [
    ("the canonical risky-action payload",
     {"source": r"C:\Users\dev\Downloads", "dest": r"D:\archive\2026-08",
      "count": 47, "dry_run": False},
     ["Downloads", "archive", "47"]),
    ("hyphenated PowerShell flags are not flag-with-value secrets",
     {"command": r"Get-ChildItem -Path C:\Users\dev\proj -Recurse -Filter *.log"},
     ["Get-ChildItem", "-Recurse", "*.log"]),
    ("'password' as ordinary prose",
     {"summary": "Password reset page 500s",
      "description": "Users who visit the reset the password page get a 500 after submit"},
     ["Password reset page 500s", "after submit"]),
    ("max_tokens is a parameter, not a token",
     {"model": "claude-opus-4", "max_tokens": 4096, "temperature": 0.2},
     ["claude-opus-4", "4096"]),
    ("token_provider whose value is literally 'api_key'",
     {"token_provider": "api_key", "llm_provider": "openrouter", "llm_model_mode": "auto"},
     ["api_key", "openrouter", "auto"]),
    ("pinned / pin_column / secretariat_owner all merely contain a sensitive word",
     {"card": "ORCH-301", "pinned": True, "pin_column": 2, "secretariat_owner": "ops"},
     ["ORCH-301", "ops", "2"]),
    ("a 16-digit run id that fails Luhn is the log's correlation key",
     {"run_id": "2026081200417739", "files_indexed": 1284, "errors": 0},
     ["2026081200417739", "1284"]),
    ("a path containing an auth/ directory",
     {"path": r"C:\proj\app\auth\provider.py", "lines": "1-40"},
     ["provider.py", "1-40"]),
]


@pytest.mark.parametrize(
    "name,payload,must_go,must_stay",
    REDACT_CORPUS,
    ids=[c[0] for c in REDACT_CORPUS],
)
def test_corpus_secrets_never_survive(name, payload, must_go, must_stay):
    out = json.dumps(redact(payload))
    for secret in must_go:
        assert secret not in out, f"[{name}] leaked {secret!r} -> {out}"
    for kept in must_stay:
        assert kept in out, f"[{name}] lost the context {kept!r} -> {out}"


@pytest.mark.parametrize(
    "name,payload,must_stay", KEEP_CORPUS, ids=[c[0] for c in KEEP_CORPUS]
)
def test_corpus_ordinary_content_is_never_redacted(name, payload, must_stay):
    """Over-redaction is its own failure: a log that cannot show what happened
    is not evidence, and the confirmation step it backs protects nothing."""
    out = json.dumps(redact(payload))
    for kept in must_stay:
        assert kept in out, f"[{name}] wrongly redacted {kept!r} -> {out}"
    assert REDACTED not in out, f"[{name}] should need no redaction at all -> {out}"


def test_the_corpus_runs_through_the_log_itself_not_just_the_redactor(log):
    """Redaction is only worth anything on the write path, so drive every
    corpus payload through append() and read the file back off disk."""
    for _, payload, _, _ in REDACT_CORPUS:
        log.append({"tool": "corpus", "arguments": payload})

    # Scan the content the log was asked to store, not the whole file. A short
    # secret such as the three-digit CVV occurs by chance inside a SHA-256
    # digest and inside a float timestamp; neither coincidence is a leak, and
    # treating them as one would push the test towards longer, less realistic
    # fixtures than the values this actually has to protect.
    machinery = ("hash", "prev", "ts")
    bodies = json.dumps(
        [{k: v for k, v in rec.items() if k not in machinery} for rec in log.read()]
    )
    for name, _, must_go, _ in REDACT_CORPUS:
        for secret in must_go:
            assert secret not in bodies, f"[{name}] {secret!r} reached the file"
    ok, index, reason = log.verify()
    assert ok is True, f"chain broken at {index}: {reason}"
