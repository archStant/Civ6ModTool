"""Editable leader text lines (diplomacy and Civilopedia)."""

import json
import re


# ---------------------------------------------------------------------------
# Editable localization lines (diplomacy + Civilopedia)
# ---------------------------------------------------------------------------
# Keys are tag templates; "{L}" is the leader type (which already starts
# with LEADER_). Moods: _ANY is used by the base game, _HAPPY/_UNHAPPY
# override it for that mood.

DIPLO_TEXT = [
    ("First meet", [
        ("LOC_DIPLO_FIRST_MEET_{L}_ANY", "First AI line"),
        ("LOC_DIPLO_FIRST_MEET_VISIT_RECIPIENT_{L}_ANY",
         "AI invites you to visit a nearby city"),
        ("LOC_DIPLO_FIRST_MEET_NEAR_INITIATOR_POSITIVE_{L}_ANY",
         "AI accepts your invitation"),
        ("LOC_DIPLO_FIRST_MEET_NO_MANS_INFO_EXCHANGE_{L}_ANY",
         "AI proposes exchanging capital information"),
    ]),
    ("Greetings", [
        ("LOC_DIPLO_GREETING_{L}_ANY", "Greeting (any mood)"),
        ("LOC_DIPLO_GREETING_{L}_HAPPY", "Greeting (happy)"),
        ("LOC_DIPLO_GREETING_{L}_UNHAPPY", "Greeting (unhappy)"),
    ]),
    ("Delegation", [
        ("LOC_DIPLO_ACCEPT_DELEGATION_FROM_HUMAN_{L}_ANY", "AI accepts"),
        ("LOC_DIPLO_REJECT_DELEGATION_FROM_HUMAN_{L}_ANY", "AI rejects"),
        ("LOC_DIPLO_DELEGATION_FROM_AI_{L}_ANY", "AI sends a delegation"),
    ]),
    ("Open borders", [
        ("LOC_DIPLO_ACCEPT_OPEN_BORDERS_FROM_HUMAN_{L}_ANY", "AI accepts"),
        ("LOC_DIPLO_REJECT_OPEN_BORDERS_FROM_HUMAN_{L}_ANY", "AI rejects"),
        ("LOC_DIPLO_OPEN_BORDERS_FROM_AI_{L}_ANY", "AI requests"),
    ]),
    ("Declare friendship", [
        ("LOC_DIPLO_ACCEPT_DECLARE_FRIEND_FROM_HUMAN_{L}_ANY", "AI accepts"),
        ("LOC_DIPLO_REJECT_DECLARE_FRIEND_FROM_HUMAN_{L}_ANY", "AI rejects"),
        ("LOC_DIPLO_DECLARE_FRIEND_FROM_AI_{L}_ANY", "AI requests"),
        ("LOC_DIPLO_ACCEPT_DECLARE_FRIEND_FROM_AI_{L}_ANY",
         "You accept the AI's request, AI responds"),
        ("LOC_DIPLO_REJECT_DECLARE_FRIEND_FROM_AI_{L}_ANY",
         "You reject the AI's request, AI responds"),
    ]),
    ("Alliance", [
        ("LOC_DIPLO_MAKE_ALLIANCE_FROM_AI_{L}_ANY", "AI requests an alliance"),
    ]),
    ("Kudos & warnings", [
        ("LOC_DIPLO_KUDO_EXIT_{L}_ANY", "AI kudos"),
        ("LOC_DIPLO_WARNING_EXIT_{L}_ANY", "AI warning"),
        ("LOC_DIPLO_KUDO_{L}_REASON_ANY", "Agenda: reason for liking you"),
        ("LOC_DIPLO_WARNING_{L}_REASON_ANY",
         "Agenda: reason for disliking you"),
    ]),
    ("Troops near border", [
        ("LOC_DIPLO_WARNING_TOO_MANY_TROOPS_NEAR_ME_{L}_HAPPY",
         "AI warns about your troops (happy)"),
        ("LOC_DIPLO_WARNING_TOO_MANY_TROOPS_NEAR_ME_{L}_UNHAPPY",
         "AI warns about your troops (unhappy)"),
        ("LOC_DIPLO_WARNING_TOO_MANY_TROOPS_NEAR_ME_AI_RESPONSE_POSITIVE"
         "_{L}_HAPPY", "AI accepts your warning (happy)"),
        ("LOC_DIPLO_WARNING_TOO_MANY_TROOPS_NEAR_ME_AI_RESPONSE_POSITIVE"
         "_{L}_UNHAPPY", "AI accepts your warning (unhappy)"),
        ("LOC_DIPLO_WARNING_TOO_MANY_TROOPS_NEAR_ME_AI_RESPONSE_NEGATIVE"
         "_{L}_ANY", "AI rejects your warning - declares war"),
    ]),
    ("Settling too close", [
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_{L}_HAPPY",
         "AI warns you (happy)"),
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_{L}_UNHAPPY",
         "AI warns you (unhappy)"),
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_RESPONSE_POSITIVE_{L}"
         "_HAPPY", "AI accepts your request (happy)"),
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_RESPONSE_POSITIVE_{L}"
         "_UNHAPPY", "AI accepts your request (unhappy)"),
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_RESPONSE_NEGATIVE_{L}"
         "_HAPPY", "AI rejects your request (happy)"),
        ("LOC_DIPLO_WARNING_DONT_SETTLE_NEAR_ME_AI_RESPONSE_NEGATIVE_{L}"
         "_UNHAPPY", "AI rejects your request (unhappy)"),
    ]),
    ("Trade", [
        ("LOC_DIPLO_ACCEPT_MAKE_DEAL_FROM_AI_{L}_HAPPY",
         "AI accepts a deal (happy)"),
        ("LOC_DIPLO_ACCEPT_MAKE_DEAL_FROM_AI_{L}_UNHAPPY",
         "AI accepts a deal (unhappy)"),
        ("LOC_DIPLO_REJECT_MAKE_DEAL_FROM_AI_{L}_HAPPY",
         "AI rejects a deal (happy)"),
        ("LOC_DIPLO_REJECT_MAKE_DEAL_FROM_AI_{L}_UNHAPPY",
         "AI rejects a deal (unhappy)"),
    ]),
    ("Denounce", [
        ("LOC_DIPLO_DENOUNCE_FROM_HUMAN_{L}_ANY",
         "You denounce, AI responds"),
        ("LOC_DIPLO_DENOUNCE_FROM_AI_{L}_ANY", "AI denounces you"),
    ]),
    ("Declarations of war", [
        ("LOC_DIPLO_DECLARE_WAR_FROM_HUMAN_{L}_ANY",
         "You declare war, AI responds"),
        ("LOC_DIPLO_DECLARE_WAR_FROM_AI_{L}_ANY", "AI declares war"),
    ]),
    ("Make peace", [
        ("LOC_DIPLO_MAKE_PEACE_AI_ACCEPT_DEAL_{L}_ANY", "AI accepts"),
        ("LOC_DIPLO_MAKE_PEACE_AI_REFUSE_DEAL_{L}_ANY", "AI refuses"),
        ("LOC_DIPLO_MAKE_PEACE_FROM_AI_{L}_ANY", "AI requests peace"),
    ]),
    ("Defeat", [
        ("LOC_DIPLO_DEFEAT_FROM_AI_{L}_ANY", "AI is defeated"),
        ("LOC_DIPLO_DEFEAT_FROM_HUMAN_{L}_ANY",
         "You are defeated (seen in hotseat)"),
    ]),
]

PEDIA_PREFIX = "LOC_PEDIA_LEADERS_PAGE_{L}_"
PEDIA_HISTORY = PEDIA_PREFIX + "CHAPTER_HISTORY"   # -> _PARA_1, _PARA_2, ...
# (key, label, text box height, inherit from the original leader if empty)
PEDIA_TEXT = [
    (PEDIA_PREFIX + "TITLE", "Title (empty = leader name)", 1, False),
    (PEDIA_PREFIX + "SUBTITLE", "Subtitle", 1, False),
    (PEDIA_PREFIX + "QUOTE", "Quote", 3, False),
    (PEDIA_PREFIX + "CHAPTER_CAPSULE_BODY", "Summary (capsule)", 4, True),
    (PEDIA_PREFIX + "CHAPTER_DETAILED_BODY", "Detailed approach", 7, True),
    (PEDIA_HISTORY, "History (separate paragraphs with a blank line)", 14,
     False),
]

# The generator used to have three greeting fields of its own.
LEGACY_GREETINGS = {"greet_happy": "LOC_DIPLO_GREETING_{L}_HAPPY",
                    "greet_neutral": "LOC_DIPLO_GREETING_{L}_ANY",
                    "greet_unhappy": "LOC_DIPLO_GREETING_{L}_UNHAPPY"}


def spec_texts(spec):
    """The spec's {tag template: text}, including legacy greeting fields."""
    texts = dict(spec.get("texts") or {})
    for old, key in LEGACY_GREETINGS.items():
        if (spec.get(old) or "").strip() and not texts.get(key):
            texts[key] = spec[old].strip()
    return texts


def inherit_candidates(key):
    """Tag templates of the original leader to copy an empty line from:
    the same mood first, then the mood-independent _ANY line - unless
    that _ANY line is editable itself (like the greeting), because the
    game already falls back to our own _ANY line then, and copying the
    original's would override it."""
    editable = {k for _, lines in DIPLO_TEXT for k, _ in lines}
    candidates = [key]
    for mood in ("_HAPPY", "_UNHAPPY"):
        any_key = key[:-len(mood)] + "_ANY"
        if key.endswith(mood) and any_key not in editable:
            candidates.append(any_key)
    return candidates


def editable_text_keys():
    return ([k for _, lines in DIPLO_TEXT for k, _ in lines] +
            [k for k, _, _, _ in PEDIA_TEXT])


def texts_to_json(texts):
    """All editable lines as JSON (empty ones too, so the result doubles
    as a template), keyed by tag template with {L} for the leader."""
    return json.dumps({k: texts.get(k, "") for k in editable_text_keys()},
                      ensure_ascii=False, indent=2)


def texts_from_json(data):
    """Parse clipboard JSON into {tag template: text}. Keys may be tag
    templates ("..._{L}_ANY") or real tags of any leader
    ("..._LEADER_RFVS_LEOPOLD_I_ANY"); history may also come as separate
    ..._CHAPTER_HISTORY_PARA_<n> entries. Returns (texts, unknown keys).
    Raises ValueError for anything that is not a JSON object of strings."""
    try:
        obj = json.loads(data)
    except ValueError as exc:
        raise ValueError("The clipboard does not contain valid JSON ({})."
                         .format(exc))
    if not isinstance(obj, dict):
        raise ValueError("Expected a JSON object of {\"tag\": \"text\"}.")
    patterns = []
    for key in editable_text_keys():
        head, tail = key.split("{L}")
        patterns.append((key, re.compile(
            re.escape(head) + r"LEADER_[A-Z0-9_]+?" + re.escape(tail) + "$")))
    head, tail = PEDIA_HISTORY.split("{L}")
    para = re.compile(re.escape(head) + r"(?:\{L\}|LEADER_[A-Z0-9_]+?)" +
                      re.escape(tail) + r"_PARA_(\d+)$")
    texts, unknown, paras = {}, [], {}
    for tag, text in obj.items():
        if not isinstance(text, str):
            raise ValueError("The value of {} is not text.".format(tag))
        m = para.match(tag)
        if m:
            paras[int(m.group(1))] = text.strip()
            continue
        key = tag if tag in editable_text_keys() else next(
            (k for k, p in patterns if p.match(tag)), None)
        if key:
            texts[key] = text.strip()
        else:
            unknown.append(tag)
    if paras and PEDIA_HISTORY not in texts:
        texts[PEDIA_HISTORY] = "\n\n".join(
            paras[n] for n in sorted(paras) if paras[n])
    return texts, unknown


def history_paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def loc_text(text):
    """Editor text -> game text (single newlines become [NEWLINE])."""
    return "[NEWLINE]".join(line.strip() for line in text.strip().split("\n"))
