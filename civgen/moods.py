"""Diplomacy portraits by mood (the 2D fallback leader).

A leader without a 3D scene shows a still image on the diplomacy screen,
looked up in FallbackLeaders.artdef under the name of the animation the
screen asks the leader to play (DiplomacyActionView / LeaderSupport.lua
pass the parts of LeaderAnimations sequences, picked by mood: HAPPY_IDLE,
NEUTRAL_POSITIVE, TO_UNHAPPY, ...). Names it does not find use DEFAULT, so
one image per mood or moment is a set of named entries pointing at its
texture. A leader spec holds them in mood_images: {slot key: image path};
the NEUTRAL slot is the loading portrait itself.
"""

# (key, group, label, explanation, slot used when empty, artdef animation
# names). Transitions show the mood they lead to: a 2D leader may never
# "finish" one, and the next part of the sequence only plays after that.
MOOD_SLOTS = [
    ("NEUTRAL", "Mood", "Neutral",
     "The leader's Portrait (General tab): its usual image, and the one "
     "every empty slot comes back to.", None,
     ("DEFAULT", "NEUTRAL", "NEUTRAL_IDLE", "TO_NEUTRAL", "HAPPY_TO_NEUTRAL",
      "UNHAPPY_TO_NEUTRAL")),
    ("HAPPY", "Mood", "Happy",
     "Friends and allies (declared friendship or an alliance).", "NEUTRAL",
     ("HAPPY", "HAPPY_IDLE", "TO_HAPPY", "NEUTRAL_TO_HAPPY")),
    ("UNHAPPY", "Mood", "Unhappy",
     "Denounced or at war.", "NEUTRAL",
     ("UNHAPPY", "UNHAPPY_IDLE", "TO_UNHAPPY", "NEUTRAL_TO_UNHAPPY")),
    ("NEUTRAL_POSITIVE", "Reaction", "Pleased (neutral)",
     "Greeting you, or accepting a proposal, while neutral.", "NEUTRAL",
     ("NEUTRAL_POSITIVE", "NEUTRAL_GREETING")),
    ("NEUTRAL_NEGATIVE", "Reaction", "Displeased (neutral)",
     "Rejecting a proposal or complaining while neutral.", "NEUTRAL",
     ("NEUTRAL_NEGATIVE",)),
    ("HAPPY_POSITIVE", "Reaction", "Pleased (happy)",
     "Accepting a proposal while happy.", "HAPPY",
     ("HAPPY_POSITIVE",)),
    ("HAPPY_NEGATIVE", "Reaction", "Displeased (happy)",
     "Rejecting a proposal or complaining while happy.", "HAPPY",
     ("HAPPY_NEGATIVE",)),
    ("UNHAPPY_POSITIVE", "Reaction", "Pleased (unhappy)",
     "Accepting a proposal while unhappy.", "UNHAPPY",
     ("UNHAPPY_POSITIVE",)),
    ("UNHAPPY_NEGATIVE", "Reaction", "Displeased (unhappy)",
     "Rejecting a proposal or complaining while unhappy.", "UNHAPPY",
     ("UNHAPPY_NEGATIVE",)),
    ("FIRST_MEET", "Moment", "First meeting",
     "Introducing themselves when you first meet.", "NEUTRAL",
     ("FIRST_MEET",)),
    ("KUDOS", "Moment", "Praises you",
     "Praising something you did (their agenda likes it).", "HAPPY",
     ("KUDOS",)),
    ("WARNING", "Moment", "Warns you",
     "Warning you about something you did (their agenda dislikes it).",
     "UNHAPPY", ("WARNING",)),
    ("ENRAGED", "Moment", "Enraged",
     "Furious with you.", "UNHAPPY",
     ("ENRAGED",)),
    ("DECLARES_WAR", "Moment", "Declares war on you",
     "Declaring war on you.", "ENRAGED",
     ("DECLARE_WAR_FROM_AI",)),
    ("WAR_DECLARED", "Moment", "You declare war",
     "Answering your declaration of war.", "ENRAGED",
     ("DECLARE_WAR_FROM_HUMAN",)),
    ("DEFEAT", "Moment", "Defeated",
     "Their last words when you defeat them.", "UNHAPPY",
     ("DEFEAT",)),
]
MOOD_GROUPS = [("Mood", "Moods"), ("Reaction", "Reactions"),
               ("Moment", "Moments")]
SLOT_KEYS = [slot[0] for slot in MOOD_SLOTS]
_SLOTS = {slot[0]: slot for slot in MOOD_SLOTS}


def slot_label(key):
    return _SLOTS[key][2]


def fallback_slot(key):
    """The slot whose image an empty slot shows (None for NEUTRAL)."""
    return _SLOTS[key][4]


def resolve_slot(key, filled):
    """The slot whose image key shows: key itself if in filled, otherwise
    the first filled one down its fallback chain (NEUTRAL at the end)."""
    while key not in filled and fallback_slot(key):
        key = fallback_slot(key)
    return key


def resolve(textures):
    """[(animation name, texture)] for a leader's fallback artdef.
    textures: {slot key: texture name}, NEUTRAL always present. A leader
    with nothing but the neutral image gets just DEFAULT, like the
    game's own leaders."""
    if set(textures) <= {"NEUTRAL"}:
        return [("DEFAULT", textures["NEUTRAL"])]
    return [(name, textures[resolve_slot(key, textures)])
            for key, _, _, _, _, names in MOOD_SLOTS for name in names]
