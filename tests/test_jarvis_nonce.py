"""ORCH-301 — spoken single-use confirmation nonce. ==CLAUDE=="""

from __future__ import annotations

import time

import pytest

from app.jarvis.nonce import (
    APPROVED,
    DENIED,
    EXPIRED,
    IGNORED,
    MISMATCH,
    SPENT,
    UNCLEAR,
    Challenge,
    ConfirmBook,
    answer,
    code_readings,
    hesitate,
    is_non_speech,
    mint,
    say_code,
    spoken_digits,
)


def challenge(code: str = "47", **kw) -> Challenge:
    return Challenge(code=code, action_summary=kw.pop("summary", "Move 47 files"), **kw)


# ------------------------------------------------------------ digit parsing

@pytest.mark.parametrize(
    "said,expected",
    [
        ("confirm 47", "47"),
        ("confirm four seven", "47"),
        ("confirm forty seven", "47"),
        ("okay, confirm four seven please", "47"),
        ("CONFIRM FOUR SEVEN", "47"),
        ("confirm: 4 7", "47"),
    ],
)
def test_the_natural_ways_to_say_a_code(said, expected):
    assert spoken_digits(said) == expected


@pytest.mark.parametrize(
    "said,expected",
    [
        ("confirm for seven", "47"),      # "four" heard as "for"
        ("confirm to one", "21"),         # "two" heard as "to"
        ("confirm too ate", "28"),        # "two"->"too", "eight"->"ate"
        ("confirm won nine", "19"),       # "one" heard as "won"
        ("confirm tree five", "35"),      # "three" heard as "tree"
        ("confirm oh six", "06"),         # "zero" said as "oh"
        ("confirm niner four", "94"),
    ],
)
def test_digits_the_recogniser_actually_mangles(said, expected):
    """"turn on dark mode" came back as "turn on dark road" on this project.
    Digits fare worse; the parser has to survive it or confirmation is
    unusable by voice."""
    assert spoken_digits(said) == expected


def test_say_code_renders_what_the_assistant_speaks():
    assert say_code("47") == "four seven"
    assert say_code("06") == "zero six"


def test_prompt_names_the_action_and_the_code():
    prompt = challenge("47", summary="Delete 412 files").prompt()
    assert "Delete 412 files" in prompt          # object and magnitude
    assert "confirm four seven" in prompt


def test_the_readback_says_whether_it_can_be_undone():
    """Usually the thing that decides the answer."""
    hard = challenge("47", summary="Delete 412 files", reversible=False)
    assert "cannot be undone" in hard.prompt()

    soft = challenge("47", summary="Move 47 files", reversible=True)
    assert "can be undone" in soft.prompt()


def test_an_unknown_reversibility_claims_nothing():
    """Saying an action is undoable when nobody checked is worse than silence."""
    prompt = challenge("47", summary="Run a script").prompt()
    assert "undone" not in prompt


# -------------------------------------------- ambiguous transcription (A3.2)

def _resolve(text):
    """Stand-in dispatcher: maps a transcript to the tool it would drive."""
    table = {
        "turn on dark mode": "set_theme",
        "turn on dark road": None,          # resolves to nothing
        "shut down": "power_off",
        "shut up": "stop_speaking",
        "delete the leads": "delete_files",
        "delete the leeds": "delete_files",
    }
    return table.get(text)


def test_alternates_driving_different_tools_ask_instead_of_acting():
    """The recorded hazard: the second-best reading is a different ACTION."""
    ask, reply = hesitate(["shut down", "shut up"], _resolve)
    assert ask is True
    assert "shut down" in reply and "shut up" in reply


def test_alternates_driving_the_same_tool_do_not_ask():
    """Two spellings of one action are not a hazard, and asking about them is
    how confirmation fatigue starts."""
    ask, _ = hesitate(["delete the leads", "delete the leeds"], _resolve)
    assert ask is False


def test_the_recorded_dark_road_case_does_not_ask():
    """"turn on dark mode" came back as "turn on dark road" on this project.
    The alternate resolves to no tool at all, so there is nothing to disambiguate
    — the misheard reading simply cannot act."""
    ask, _ = hesitate(["turn on dark mode", "turn on dark road"], _resolve)
    assert ask is False


def test_a_single_alternate_never_asks():
    assert hesitate(["shut down"], _resolve)[0] is False
    assert hesitate([], _resolve)[0] is False


def test_a_resolver_that_raises_does_not_take_the_gate_down():
    def broken(_text):
        raise RuntimeError("dispatcher exploded")

    assert hesitate(["shut down", "shut up"], broken)[0] is False


# --------------------------------------------------- the attack that matters

@pytest.mark.parametrize(
    "said",
    ["yes", "yeah", "yep", "ok", "okay", "sure", "do it", "go ahead",
     "yes please", "alright", "fine"],
)
def test_a_bare_yes_authorises_nothing(said):
    """The whole reason the code exists: "yes" is the likeliest word to arrive
    from a television or a bystander."""
    ch = challenge("47")
    outcome, _ = answer(ch, said)
    assert outcome != APPROVED
    assert ch.used is False                      # and it stays answerable


def test_the_word_confirm_alone_authorises_nothing():
    ch = challenge("47")
    outcome, reply = answer(ch, "confirm")
    assert outcome == MISMATCH
    assert "four seven" in reply                 # re-reads the code
    assert ch.used is False


@pytest.mark.parametrize("said", ["confirm four eight", "confirm seventy four",
                                  "confirm 48", "confirm four six"])
def test_the_wrong_code_is_refused(said):
    ch = challenge("47")
    outcome, _ = answer(ch, said)
    assert outcome == MISMATCH
    assert ch.used is False


def test_a_number_overheard_in_unrelated_speech_does_not_approve():
    """A TV saying "flight forty seven is now boarding" contains the code but
    no intent to confirm."""
    ch = challenge("47")
    outcome, _ = answer(ch, "flight forty seven is now boarding at gate three")
    assert outcome == IGNORED
    assert ch.used is False


def test_the_correct_code_approves():
    ch = challenge("47")
    outcome, _ = answer(ch, "confirm four seven")
    assert outcome == APPROVED
    assert ch.used is True


# ------------------------------------------------------ single use & expiry

def test_a_code_cannot_be_replayed():
    ch = challenge("47")
    assert answer(ch, "confirm four seven")[0] == APPROVED
    outcome, reply = answer(ch, "confirm four seven")
    assert outcome == SPENT
    assert "already used" in reply


def test_an_expired_code_is_refused_even_when_correct():
    ch = challenge("47", ttl=10.0)
    ch.created_at = time.time() - 60
    outcome, reply = answer(ch, "confirm four seven")
    assert outcome == EXPIRED
    assert "too long" in reply


def test_expiry_is_checked_before_the_code_so_a_late_correct_answer_fails():
    ch = challenge("47", ttl=1.0)
    ch.created_at = time.time() - 5
    assert answer(ch, "confirm four seven")[0] == EXPIRED


def test_cancelling_is_honoured_and_burns_the_challenge():
    for word in ("cancel", "no", "stop", "never mind", "abort", "don't"):
        ch = challenge("47")
        outcome, reply = answer(ch, word)
        assert outcome == DENIED, word
        assert ch.used is True
        assert "did not" in reply


def test_cancel_is_not_mined_for_digits():
    """"no, not forty seven" must cancel, never approve."""
    ch = challenge("47")
    outcome, _ = answer(ch, "no, not forty seven")
    assert outcome == DENIED


# ------------------------------------------------------------------- minting

def test_minted_codes_are_the_requested_length_and_numeric():
    for _ in range(50):
        ch = mint("do a thing")
        assert len(ch.code) == 2 and ch.code.isdigit()


def test_minted_codes_vary():
    codes = {mint("x").code for _ in range(60)}
    assert len(codes) > 5, "codes look predictable"


# ------------------------------------------------------------------ the book

def test_a_bare_confirm_resolves_nothing_even_with_one_pending():
    """There is deliberately no confirm-the-latest shortcut."""
    book = ConfirmBook()
    book.open("Move 47 files", tool="organize_folder")
    outcome, ch, _ = book.resolve("confirm")
    assert outcome == MISMATCH and ch is None
    assert len(book.pending()) == 1               # still waiting


def test_the_code_selects_which_action_is_approved():
    book = ConfirmBook()
    a = book.open("Delete the archive", tool="run_powershell")
    b = book.open("Move 12 files", tool="organize_folder")
    outcome, ch, _ = book.resolve(f"confirm {say_code(b.code)}")
    assert outcome == APPROVED
    assert ch is b                                 # the one the code belongs to
    assert [c.code for c in book.pending()] == [a.code]


def test_two_live_challenges_never_share_a_code():
    book = ConfirmBook()
    codes = {book.open(f"action {i}").code for i in range(40)}
    assert len(codes) == 40


def test_expired_challenges_are_purged():
    book = ConfirmBook(ttl=1.0)
    ch = book.open("something")
    ch.created_at = time.time() - 30
    assert book.pending() == []


def test_cancel_without_a_code_clears_everything_pending():
    """Refusing is always safe, so it does not need the same proof."""
    book = ConfirmBook()
    book.open("a")
    book.open("b")
    outcome, _, _ = book.resolve("cancel")
    assert outcome == DENIED
    assert book.pending() == []


def test_unrelated_chatter_leaves_pending_actions_alone():
    book = ConfirmBook()
    book.open("Move files")
    for said in ("what's the weather", "open chrome", "that's interesting"):
        assert book.resolve(said)[0] == IGNORED
    assert len(book.pending()) == 1


def test_resolving_with_nothing_pending_is_harmless():
    book = ConfirmBook()
    assert book.resolve("confirm four seven")[0] == IGNORED


# ------------------------------------------------------- low-confidence audio

def test_a_badly_heard_utterance_does_not_resolve_or_burn_the_challenge():
    """A security gate must not act on a guess. Below the confidence floor the
    assistant re-prompts, and the user keeps their one attempt."""
    ch = challenge("47")
    outcome, reply = answer(ch, "confirm four seven", confidence=0.31)
    assert outcome == UNCLEAR
    assert ch.used is False
    assert "four seven" in reply
    # And the same words, heard properly, still work.
    assert answer(ch, "confirm four seven", confidence=0.94)[0] == APPROVED


@pytest.mark.parametrize("said", ["", "   ", "\n\t ", "[inaudible]", "[unintelligible]"])
def test_non_speech_is_never_matched_against_a_code(said):
    """An empty transcript must not satisfy an empty-string comparison, and a
    clipped segment must not consume the single use."""
    assert is_non_speech(said) is True
    ch = challenge("47")
    outcome, _ = answer(ch, said)
    assert outcome == IGNORED
    assert ch.used is False


# ------------------------------------------------- red-team corpus (ORCH-303)
#
# Generated adversarially against this module's contract, then run against it.
# It found three real defects, all now fixed and pinned below:
#   * a leading "oh" was folded to digit 0, so "oh confirm four seven" read 047
#   * a trailing "too" was folded to digit 2, so it read 472
#   * "and we can confirm the final score was four seven" APPROVED — a plausible
#     broadcast sentence carrying the verb and the code in order
# The third is the reason confirmation is now parsed structurally rather than
# scanned. Each case carries why it exists, and that text is the failure message.

CORPUS_ACCEPT = [
    ("confirm four seven", "canonical form; if this fails nothing else matters"),
    ("CONFIRM FOUR SEVEN", "all-caps from the SAPI grammar path"),
    ("confirm four Seven", "the LM tags a mid-utterance digit word as a proper noun"),
    ("Confirm four seven.", "sentence case plus the terminal stop of end-of-speech"),
    ("confirm forty seven", "humans read 4 7 aloud as the number"),
    ("confirm forty-seven", "English compounds arrive hyphenated"),
    ("confirm 47", "inverse text normalisation; the likeliest real transcript"),
    ("confirm 4 7", "ITN fired per digit after a pause — must concatenate, not sum"),
    ("confirm 4 seven", "ITN fired on the first digit only"),
    ("confirm four 7", "and on the second only; a whole-word parser fails one of these"),
    ("confirm: 47", "the prompt says 'say: confirm...' and transcribers keep the colon"),
    ("confirm, four seven", "comma from the prosodic pause after the imperative"),
    ("confirm four seven\n", "trailing newline when a partial transcript is flushed"),
    ("confirm  four   seven", "irregular whitespace from token-by-token assembly"),
    ("ok, confirm 47", "filler, punctuation and ITN stacked, as real transcripts are"),
    ("um confirm forty seven", "disfluency; both recognisers transcribe it rather than drop it"),
    ("yes confirm four seven", "bare yes must fail, but yes before a correct code must not"),
    ("oh confirm four seven", "leading 'oh' is an interjection, not the digit 0"),
    ("confirm four seven please", "filler tolerance has to work on the suffix side too"),
    ("confirm four seven too", "trailing 'too' is a modifier, not the digit 2"),
    ("confirm for seven", "THE critical homophone; the LM prefers the commoner 'for'"),
    ("okay confirm for seven", "homophone and filler must compose, not be exclusive"),
    ("confirm fore seven", "third spelling of the same phoneme, seen in n-best output"),
    ("confirm fourty seven", "common misspelling from text-normalising recognisers"),
    ("confirm number four seven", "carrier word between the verb and the digits"),
    ("confirm code 47", "the user echoes the assistant's own framing"),
]

CORPUS_REJECT = [
    ("yes", "the attack the mechanism exists to stop: zero challenge entropy"),
    ("okay sure", "two affirmatives still sum to zero entropy"),
    ("go ahead", "decisive to an intent classifier; intent must not substitute for the code"),
    ("mhm", "backchannel grunt emitted for a throat-clear"),
    ("confirm", "the verb alone; a bystander who overheard the prompt can replay it"),
    ("confirm four eight", "off-by-one final digit — exactly what the recogniser confuses"),
    ("confirm seventy four", "transposition via the tens form; order must be preserved"),
    ("confirm seven four", "same transposition in bare digits; no set comparison"),
    ("confirm four", "a prefix is a full bypass on a two-digit code"),
    ("confirm seven", "and so is a suffix"),
    ("confirm four seven eight", "containment must not count as a match"),
    ("confirm four severn", "mangle to a real non-digit word; fail closed, do not guess"),
    ("flight forty seven departs from gate twelve", "announcement audio, no confirm intent"),
    ("and we can confirm the final score was four seven",
     "broadcast sentence carrying the verb AND the code in order"),
    ("to confirm, say: confirm four seven",
     "the assistant's own prompt echoed back through room speakers"),
    ("she told me to say confirm four seven", "reported speech is narration, not assertion"),
    ("confirm the meeting at four", "confirm intent bound to an unrelated task"),
    ("confirm delete all the log files", "the verb attached to a different, worse action"),
    ("confirm four seven and delete the backups too",
     "correct code plus a rider command smuggles in an unconfirmed second action"),
    ("confirm four seven or four eight", "two candidates in one breath makes guessing free"),
    ("confirm four eight, sorry, four seven",
     "last-match-wins would reopen the multi-guess and TV-audio holes"),
    ("four seven", "bare digits, e.g. read off the screen, are not consent"),
    ("did you say four seven?", "an interrogative is clarifying, not confirming"),
]


@pytest.mark.parametrize("said,why", CORPUS_ACCEPT)
def test_corpus_accepts(said, why):
    ch = challenge("47")
    outcome, _ = answer(ch, said)
    assert outcome == APPROVED, f"{said!r} should approve — {why}"


@pytest.mark.parametrize("said,why", CORPUS_REJECT)
def test_corpus_refuses(said, why):
    ch = challenge("47")
    outcome, _ = answer(ch, said)
    assert outcome != APPROVED, f"{said!r} must not approve — {why}"


@pytest.mark.parametrize("said,why", CORPUS_REJECT)
def test_nothing_the_corpus_refuses_can_approve_through_the_book(said, why):
    """The same guarantee via ConfirmBook, which is what the gateway calls."""
    book = ConfirmBook()
    book.open("Move 47 files", tool="organize_folder")
    # Force the pending code to the corpus code so the digits genuinely collide.
    ch = book.pending()[0]
    book._items.clear()
    ch.code = "47"
    book._items["47"] = ch
    outcome, _, _ = book.resolve(said)
    assert outcome != APPROVED, f"{said!r} must not approve — {why}"


def test_a_rider_command_is_refused_rather_than_partly_obeyed():
    """The corpus case worth stating on its own: a correct code with a second
    instruction stapled to it authorises nothing, because approving it would
    run an action the user never had read back to them."""
    ch = challenge("47")
    outcome, _ = answer(ch, "confirm four seven and delete the backups too")
    assert outcome == MISMATCH
    assert ch.used is False


@pytest.mark.parametrize(
    "said,expected",
    [
        ("confirm four seven", ["47"]),
        ("confirm four seven too", ["472", "47"]),   # greedy first, then filler
        ("confirm oh six", ["06", "6"]),
        ("and we can confirm the final score was four seven", []),
        ("confirm four severn", []),
    ],
)
def test_readings_are_bounded_and_ordered(said, expected):
    """Ambiguity is resolved by offering both readings, not by loosening the
    match: every reading still has to equal the code."""
    assert code_readings(said) == expected
