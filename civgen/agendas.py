"""An AI agenda of a leader's own (advanced mode): its likes and dislikes
of other civilizations.

The leader spec's own_agenda is {"name", "desc", "reactions": [...]}; a
reaction (one like or dislike) is

    {"value": "6",            # the change in its opinion of the other
                              # civilization: positive likes, negative
                              # dislikes (the game's are -12 to +15)
     "reqs": [...],           # conditions on the other civilization, all
                              # needed: raw requirements (see modifiers.py)
     "text": "...",           # what the diplomacy screen shows
     "reason": "...",         # the reason the AI gives when it praises or
                              # warns you (empty: the text)
     "fade_turns": "10"}      # an event's: the opinion fades by 1 every
                              # that many turns (empty: FADE_TURNS)

Each is written like the game's own agendas: a
MODIFIER_PLAYER_DIPLOMACY_SIMPLE_MODIFIER of the agenda's trait. Most
conditions are states ("has the same government"): the opinion holds for
the major civilizations met at least MET_TURNS turns ago that meet them.
A condition in EVENT_CONDITIONS ("declared a surprise war") is an event:
the opinion changes when it happens to a civilization met, then fades.
"""

from .modifiers import arg_display, check_effect, effects_sql, readable_type
from .util import sql_str, type_display_name

SIMPLE_MODIFIER = "MODIFIER_PLAYER_DIPLOMACY_SIMPLE_MODIFIER"
MET_TURNS = 10
# what every one of the game's likes and dislikes needs first
STANDARD_REQS = [
    {"type": "REQUIREMENT_CIVILIZATION_LEVEL",
     "args": {"OpponentCivLevel": "CIVILIZATION_LEVEL_FULL_CIV"},
     "not": False, "target": "subject"},
    {"type": "REQUIREMENT_PLAYER_MET_X_TURNS_AGO",
     "args": {"TurnsAgo": str(MET_TURNS)}, "not": False,
     "target": "subject"},
]
# ... and what those on an event need (as the game's: met at all)
EVENT_STANDARD_REQS = [
    STANDARD_REQS[0],
    {"type": "REQUIREMENT_PLAYER_HAS_MET", "args": {}, "not": False,
     "target": "subject"},
]
# Conditions that are events: the game marks them Triggered (checked when
# the event happens - never true as a lasting state) and lets the opinion
# fade (ReductionTurns / ReductionValue), as in Tomyris' dislike of
# surprise wars
EVENT_CONDITIONS = {
    "REQUIREMENT_PLAYER_DECLARED_WAR", "REQUIREMENT_DENOUNCED_FRIEND",
    "REQUIREMENT_CITY_LIBERATED", "REQUIREMENT_DENOUNCED",
    "REQUIREMENT_CITY_RAZED", "REQUIREMENT_CULTURE_BOMBED",
    "REQUIREMENT_DEMAND_RECEIVED", "REQUIREMENT_ESPIONAGE_DETECTED",
    "REQUIREMENT_PLAYER_DEAL_ENACTED",
}
FADE_TURNS = 10             # the game's agendas' events: by 1 every 10

# The conditions the game's agendas use (on the other civilization, "this
# leader" being the agenda's) -> what they mean. Most "lead" conditions
# compare the two: a ratio of how many times this leader's it has (a
# negative one: this leader has that many times its) and a minimum
# difference; see the game's own uses (GameData.agenda_examples).
CONDITIONS = {
    "REQUIREMENT_PLAYER_YIELD_LEAD": "Has more of a yield",
    "REQUIREMENT_PLAYER_MILITARY_STRENGTH_LEAD": "Has a stronger military",
    "REQUIREMENT_PLAYER_POPULATION_LEAD": "Has more citizens",
    "REQUIREMENT_PLAYER_HAPPINESS_LEAD": "Has happier citizens",
    "REQUIREMENT_PLAYER_INCOME_LEAD": "Has more income",
    "REQUIREMENT_PLAYER_TOURISM_LEAD": "Has more tourism",
    "REQUIREMENT_PLAYER_EXPLORATION_LEAD": "Has explored more",
    "REQUIREMENT_PLAYER_FAVOR_LEAD": "Has more diplomatic favor",
    "REQUIREMENT_PLAYER_DIPLO_VP_LEAD": "Has more diplomatic victory points",
    "REQUIREMENT_PLAYER_PILLAGE_LEAD": "Pillages more",
    "REQUIREMENT_PLAYER_GOT_GREAT_PERSON": "Earns more great people",
    "REQUIREMENT_PLAYER_BUILT_WONDER": "Builds more wonders",
    "REQUIREMENT_PLAYER_FINISHED_RESEARCH":
        "Is ahead in technologies and civics",
    "REQUIREMENT_PLAYER_DISTRICT_THRESHOLD": "Builds many districts",
    "REQUIREMENT_PLAYER_HAS_TECHNOLOGY": "Has a technology",
    "REQUIREMENT_PLAYER_HAS_SAME_GOVERNMENT": "Has the same government",
    "REQUIREMENT_PLAYER_IS_SAME_RELIGION": "Follows the same religion",
    "REQUIREMENT_PLAYER_RELIGION_RECEIVED":
        "Brought its religion to this leader",
    "REQUIREMENT_PLAYER_RELIGION_NOT_RECEIVED":
        "Has not brought its religion to this leader",
    "REQUIREMENT_CITY_CONVERTED": "Converted this leader's cities",
    "REQUIREMENT_PLAYER_HAS_GOLDEN_AGE": "Is in a golden age",
    "REQUIREMENT_PLAYER_HAS_DARK_AGE": "Is in a dark age",
    "REQUIREMENT_PLAYER_IS_NEIGHBOR": "Is a neighbor",
    "REQUIREMENT_PLAYER_SHARES_HOME_CONTINENT":
        "Shares this leader's home continent",
    "REQUIREMENT_PLAYER_ON_NON_HOME_CONTINENT":
        "Has cities on a continent this leader wants",
    "REQUIREMENT_PLAYER_IS_AT_PEACE": "Is at peace with this leader",
    "REQUIREMENT_DECLARED_FRIEND": "Is a declared friend",
    "REQUIREMENT_DENOUNCED_FRIEND": "Denounced this leader's friends",
    "REQUIREMENT_PLAYER_DECLARED_WAR": "Declared war",
    "REQUIREMENT_PLAYER_IS_NOT_WARMONGER": "Keeps the peace",
    "REQUIREMENT_PLAYER_AT_WAR_WITH_NEIGHBOR": "Is at war with a neighbor",
    "REQUIREMENT_PLAYER_ATTACKED_CONTINENT":
        "Attacked civilizations on this leader's continent",
    "REQUIREMENT_PLAYER_PEACEFUL_ON_CONTINENT":
        "Is peaceful on this leader's continent",
    "REQUIREMENT_PLAYER_NUKE_LOVER": "Builds or uses nuclear weapons",
    "REQUIREMENT_PLAYER_CITY_STATE_PROTECTOR":
        "Is suzerain of city-states",
    "REQUIREMENT_PLAYER_COMPETING_MINORS":
        "Competes for this leader's city-states",
    "REQUIREMENT_PLAYER_NOT_COMPETING_MINORS":
        "Does not compete for this leader's city-states",
    "REQUIREMENT_PLAYER_CONQUERING_ALLYING_MINORS":
        "Conquers or allies with city-states",
    "REQUIREMENT_PLAYER_NOT_INVOLVED_MINORS": "Stays away from city-states",
    "REQUIREMENT_PLAYER_HAS_MANY_ALLIANCES": "Has many alliances",
    "REQUIREMENT_PLAYER_IS_SHARING_INFO": "Shares information",
    "REQUIREMENT_PLAYER_HAS_DESIRED_LUXURY":
        "Has luxuries this leader lacks",
    "REQUIREMENT_PLAYER_CIVILIZED": "Clears barbarian camps",
    "REQUIREMENT_PLAYER_COASTAL_CITIES": "Has many coastal cities",
    "REQUIREMENT_PLAYER_MOUNTAIN_CITIES": "Has many cities by mountains",
    "REQUIREMENT_PLAYER_AVERAGE_WALL_LEVEL_THRESHOLD":
        "Has strong city walls",
    "REQUIREMENT_CITY_LIBERATED": "Liberated cities",
}


def new_reaction():
    return {"value": "6", "reqs": [], "text": "", "reason": ""}


def condition_label(requirement_type):
    """A condition in words: CONDITIONS', else its type made readable."""
    return CONDITIONS.get(requirement_type) or readable_type(
        requirement_type, ("REQUIREMENT_", "PLAYER_"))


def is_event(reaction):
    """Whether a reaction is to an event (see EVENT_CONDITIONS)."""
    return any((r.get("type") or "") in EVENT_CONDITIONS
               for r in reaction.get("reqs") or [])


def fade_turns(reaction):
    """Every how many turns an event's opinion fades by 1 (as typed; empty:
    FADE_TURNS)."""
    return str(reaction.get("fade_turns") or "").strip() or str(FADE_TURNS)


def reaction_summary(reaction,
                     name_of=lambda kind, t: type_display_name(t)):
    """One line for a reaction, e.g. '+6 if: Has more of a yield (YieldType
    Culture...) - "They like cultured civilizations"', or for an event
    '+12 when: Declared war (...), fading by 1 every 10 turns - "..."'."""
    conditions = []
    for req in reaction.get("reqs") or []:
        label = condition_label(req.get("type") or "")
        args = ", ".join("{} {}".format(n, arg_display(n, v, name_of))
                         for n, v in sorted((req.get("args") or {}).items()))
        conditions.append("{}{}{}".format(
            "not: " if req.get("not") else "", label,
            " ({})".format(args) if args else ""))
    value = str(reaction.get("value") or "").strip()
    if value and value[0] not in "+-":
        value = "+" + value
    if not conditions:
        what = "(every civilization met)"
    elif is_event(reaction):
        what = "when: {}, fading by 1 every {} turns".format(
            "; ".join(conditions), fade_turns(reaction))
    else:
        what = "if: " + "; ".join(conditions)
    return "{} {} - \"{}\"".format(value or "?", what,
                                   reaction.get("text") or "")


def _number(value):
    """A whole number as the game writes it: "+12" -> "12"."""
    try:
        return str(int(str(value).strip()))
    except ValueError:
        return str(value).strip()       # (check_reaction reports it)


def reaction_effect(reaction, text_tag, reason_tag):
    """The raw effect (see modifiers.py) a reaction is written as; its text
    is at text_tag, its reason at reason_tag. One to an event is written
    like the game's: its event conditions Triggered, the civilization met
    at all, and the opinion fading."""
    reqs = []
    for r in reaction.get("reqs") or []:
        r = dict(r, target="subject")
        if r.get("type") in EVENT_CONDITIONS and "columns" not in r:
            r["columns"] = {"Triggered": 1}
        reqs.append(r)
    args = {"InitialValue": _number(reaction.get("value")),
            "SimpleModifierDescription": text_tag,
            "StatementKey": reason_tag}
    standard = STANDARD_REQS
    if is_event(reaction):
        standard = EVENT_STANDARD_REQS
        args.update(ReductionTurns=_number(fade_turns(reaction)),
                    ReductionValue="-1")
    return {"modifier_type": SIMPLE_MODIFIER, "args": args,
            "reqs": [dict(r) for r in standard] + reqs,
            "run_once": False, "permanent": False}


def check_reaction(reaction, data=None):
    """Raise ValueError if a reaction is unusable (see check_effect for
    what the game data checks)."""
    try:
        value = int(str(reaction.get("value")).strip())
    except ValueError:
        raise ValueError("the change in opinion must be a whole number "
                         "(positive: likes, negative: dislikes)")
    if not value:
        raise ValueError("the change in opinion cannot be 0")
    if not (reaction.get("text") or "").strip():
        raise ValueError("it needs the text the diplomacy screen shows")
    if is_event(reaction):
        try:
            turns = int(fade_turns(reaction))
        except ValueError:
            turns = 0
        if turns < 1:
            raise ValueError("the opinion fades by 1 every so many turns: "
                             "a whole number of at least 1")
    for req in reaction.get("reqs") or []:
        if "type" not in req:
            raise ValueError("its conditions are the game's requirement "
                             "types")
    check_effect(reaction_effect(reaction, "LOC_X", "LOC_X"), "trait", data)


def normalize_own_agenda(spec, leader_name, short, data):
    """The context of a leader's own agenda (spec: the leader spec's
    own_agenda), short: the leader type without LEADER_. Raises ValueError
    naming the leader."""
    name = (spec.get("name") or "").strip()
    if not name:
        raise ValueError("{}: give the agenda of its own a name (Agenda "
                         "tab).".format(leader_name))
    reactions = list(spec.get("reactions") or [])
    if not reactions:
        raise ValueError("{}: the agenda of its own needs at least one like "
                         "or dislike.".format(leader_name))
    for n, reaction in enumerate(reactions, 1):
        try:
            check_reaction(reaction, data)
        except ValueError as exc:
            raise ValueError("{}: like / dislike {} of its agenda - {}."
                             .format(leader_name, n, exc))
    agenda = "AGENDA_" + short
    trait = "TRAIT_AGENDA_" + short
    texts, effects = [], []
    for n, reaction in enumerate(reactions, 1):
        tag = "LOC_{}_REACTION_{}".format(agenda, n)
        text = reaction["text"].strip()
        texts += [(tag + "_TEXT", text),
                  (tag + "_REASON",
                   (reaction.get("reason") or "").strip() or text)]
        effects.append(reaction_effect(reaction, tag + "_TEXT",
                                       tag + "_REASON"))
    desc = (spec.get("desc") or "").strip() or "\n".join(
        r["text"].strip() for r in reactions)
    sql, more = effects_sql("trait", trait, effects, name, data.type_name)
    return {"type": agenda, "trait": trait, "name": name, "desc": desc,
            "name_tag": "LOC_{}_NAME".format(agenda),
            "desc_tag": "LOC_{}_DESCRIPTION".format(agenda),
            "effects_sql": sql, "texts": texts + more,
            "count": len(reactions)}


def own_agenda_sql(slug, agenda):
    """The SQL of a leader's (slug) own agenda (normalize_own_agenda)."""
    return """-- AI agenda of its own: {count} likes / dislikes
INSERT INTO Agendas (AgendaType, Name, Description)
VALUES ({type}, {name}, {desc});
INSERT INTO Types (Type, Kind) VALUES ({trait}, 'KIND_TRAIT');
INSERT INTO Traits (TraitType, Name, Description)
VALUES ({trait}, {name}, {desc});
INSERT INTO AgendaTraits (AgendaType, TraitType) VALUES ({type}, {trait});
INSERT INTO HistoricalAgendas (LeaderType, AgendaType)
VALUES ({slug}, {type});
{effects}""".format(count=agenda["count"], type=sql_str(agenda["type"]),
                    trait=sql_str(agenda["trait"]),
                    name=sql_str(agenda["name_tag"]),
                    desc=sql_str(agenda["desc_tag"]), slug=sql_str(slug),
                    effects=agenda["effects_sql"])
