"""Classes of unique units: what kind of unit it is (land, naval or air;
melee, ranged, siege, cavalry...).

A unit's class is spread over the game's tables: its Units columns
(domain, formation, promotion class - its promotion tree - and flags such
as an aircraft's stacking), its class tags (TypeTags: the game's combat
bonuses and abilities apply by them, e.g. the anti-cavalry bonus against
CLASS_LIGHT_CAVALRY) and its AI types (UnitAiInfos: how the AI uses it).
A preset sets all of them as one of the game's own units has them (its
"unit"), so a unique unit can be any class - a new unit, or a copy of a
unit of another class. The copied unit's own tags (its unique ability's,
e.g. CLASS_MAMLUK) are kept.
"""

# The class columns of Units every preset gives (so a copied unit of
# another class loses its own), with the values of a land combat unit;
# the presets change them.
LAND_COLUMNS = {
    "Domain": "DOMAIN_LAND", "FormationClass": "FORMATION_CLASS_LAND_COMBAT",
    "PromotionClass": None, "ZoneOfControl": 1, "Stackable": 0,
    "IgnoreMoves": 0, "CanTargetAir": 0, "CanCapture": 1, "AirSlots": 0,
    "WMDCapable": 0, "PseudoYieldType": None,
    "AdvisorType": "ADVISOR_CONQUEST", "PrereqDistrict": None,
}
NAVAL_COLUMNS = dict(LAND_COLUMNS, Domain="DOMAIN_SEA",
                     FormationClass="FORMATION_CLASS_NAVAL",
                     PseudoYieldType="PSEUDOYIELD_UNIT_NAVAL_COMBAT")
AIR_COLUMNS = dict(LAND_COLUMNS, Domain="DOMAIN_AIR",
                   FormationClass="FORMATION_CLASS_AIR", ZoneOfControl=0,
                   Stackable=1, IgnoreMoves=1, CanTargetAir=1, CanCapture=0,
                   PseudoYieldType="PSEUDOYIELD_UNIT_AIR_COMBAT",
                   PrereqDistrict="DISTRICT_AERODROME")


def _preset(label, unit, base, promotion, tags, ai, needs=(), **columns):
    return {"label": label, "unit": unit,
            "columns": dict(base, PromotionClass="PROMOTION_CLASS_" +
                            promotion, **columns),
            "tags": ["CLASS_" + t for t in tags], "ai": list(ai),
            # stats it cannot do without (besides Combat)
            "needs": ["Combat"] + list(needs)}


RANGED = ("RangedCombat", "Range")
BOMBARD = ("Bombard", "Range")
# key -> preset, in the editor's order
UNIT_CLASSES = {
    "melee": _preset(
        "Melee", "UNIT_WARRIOR", LAND_COLUMNS, "MELEE", ["MELEE"],
        ["UNITAI_COMBAT", "UNITAI_EXPLORE", "UNITTYPE_MELEE",
         "UNITTYPE_LAND_COMBAT"]),
    "ranged": _preset(
        "Ranged", "UNIT_ARCHER", LAND_COLUMNS, "RANGED", ["RANGED"],
        ["UNITAI_COMBAT", "UNITTYPE_RANGED", "UNITTYPE_LAND_COMBAT"],
        RANGED, ZoneOfControl=0),
    "anti_cavalry": _preset(
        "Anti-cavalry", "UNIT_SPEARMAN", LAND_COLUMNS, "ANTI_CAVALRY",
        ["ANTI_CAVALRY"],
        ["UNITAI_COMBAT", "UNITAI_EXPLORE", "UNITTYPE_MELEE",
         "UNITTYPE_ANTI_CAVALRY", "UNITTYPE_LAND_COMBAT"]),
    "light_cavalry": _preset(
        "Light cavalry", "UNIT_HORSEMAN", LAND_COLUMNS, "LIGHT_CAVALRY",
        ["LIGHT_CAVALRY"],
        ["UNITAI_COMBAT", "UNITAI_EXPLORE", "UNITTYPE_CAVALRY",
         "UNITTYPE_MELEE", "UNITTYPE_LAND_COMBAT"]),
    "heavy_cavalry": _preset(
        "Heavy cavalry", "UNIT_KNIGHT", LAND_COLUMNS, "HEAVY_CAVALRY",
        ["HEAVY_CAVALRY"],
        ["UNITAI_COMBAT", "UNITTYPE_MELEE", "UNITTYPE_CAVALRY",
         "UNITTYPE_LAND_COMBAT"]),
    # (ranged promotions, a cavalry unit's tags - the game's horse archers)
    "ranged_cavalry": _preset(
        "Ranged cavalry", "UNIT_SCYTHIAN_HORSE_ARCHER", LAND_COLUMNS,
        "RANGED", ["RANGED_CAVALRY", "MOBILE_RANGED"],
        ["UNITAI_COMBAT", "UNITAI_EXPLORE", "UNITTYPE_CAVALRY",
         "UNITTYPE_RANGED", "UNITTYPE_LAND_COMBAT"], RANGED, ZoneOfControl=0),
    "siege": _preset(
        "Siege", "UNIT_CATAPULT", LAND_COLUMNS, "SIEGE",
        ["SIEGE", "SIEGE_SETUP", "FORWARD_OBSERVER"],
        ["UNITAI_COMBAT", "UNITTYPE_RANGED", "UNITTYPE_SIEGE",
         "UNITTYPE_SIEGE_ALL", "UNITTYPE_LAND_COMBAT"], BOMBARD,
        ZoneOfControl=0),
    "recon": _preset(
        "Recon", "UNIT_SCOUT", LAND_COLUMNS, "RECON",
        ["RECON", "REVEAL_STEALTH"],
        ["UNITAI_EXPLORE", "UNITTYPE_LAND_COMBAT"],
        AdvisorType="ADVISOR_GENERIC",
        PseudoYieldType="PSEUDOYIELD_UNIT_EXPLORER"),
    "naval_melee": _preset(
        "Naval melee", "UNIT_GALLEY", NAVAL_COLUMNS, "NAVAL_MELEE",
        ["NAVAL_MELEE"],
        ["UNITAI_COMBAT", "UNITAI_EXPLORE", "UNITTYPE_MELEE",
         "UNITTYPE_NAVAL"]),
    "naval_ranged": _preset(
        "Naval ranged", "UNIT_QUADRIREME", NAVAL_COLUMNS, "NAVAL_RANGED",
        ["NAVAL_RANGED"],
        ["UNITAI_COMBAT", "UNITTYPE_RANGED", "UNITTYPE_NAVAL"], RANGED),
    "naval_raider": _preset(
        "Naval raider", "UNIT_PRIVATEER", NAVAL_COLUMNS, "NAVAL_RAIDER",
        ["NAVAL_RAIDER", "NAVAL_RANGED", "STEALTH", "REVEAL_STEALTH"],
        ["UNITAI_COMBAT", "UNITTYPE_RANGED", "UNITTYPE_NAVAL"], RANGED),
    "naval_carrier": _preset(
        "Naval carrier", "UNIT_AIRCRAFT_CARRIER", NAVAL_COLUMNS,
        "NAVAL_CARRIER", ["NAVAL_CARRIER"],
        ["UNITAI_COMBAT", "UNITTYPE_NAVAL"], AirSlots=2),
    "air_fighter": _preset(
        "Air fighter", "UNIT_BIPLANE", AIR_COLUMNS, "AIR_FIGHTER",
        ["AIRCRAFT", "AIR_FIGHTER"], ["UNITAI_COMBAT", "UNITTYPE_AIR"],
        RANGED),
    "air_bomber": _preset(
        "Air bomber", "UNIT_BOMBER", AIR_COLUMNS, "AIR_BOMBER",
        ["AIRCRAFT", "AIR_BOMBER"],
        ["UNITAI_COMBAT", "UNITTYPE_NUCLEAR", "UNITTYPE_AIR_SIEGE"],
        BOMBARD, WMDCapable=1, CanCapture=1),   # (as the game's Bomber)
}
# The class tags a preset replaces on a copied unit (any other tag of
# the copied unit is its own and stays)
ROLE_TAGS = sorted({t for p in UNIT_CLASSES.values() for t in p["tags"]})

# stat column -> its words in a "needs" message
NEED_WORDS = {"Combat": "combat strength", "RangedCombat": "ranged strength",
              "Bombard": "bombard strength", "Range": "range"}


def class_choices():
    """[(key, label)] of the presets, for the editor."""
    return [(key, "{} (like the {})".format(
        p["label"], p["unit"][len("UNIT_"):].replace("_", " ").title()))
        for key, p in UNIT_CLASSES.items()]


def normalize_unit_class(value, label):
    """A preset key, or "" (the copied unit's class). Raises ValueError."""
    value = (value or "").strip().lower()
    if value and value not in UNIT_CLASSES:
        raise ValueError("{}: unknown unit class '{}'.".format(label, value))
    return value


def class_label(key):
    return UNIT_CLASSES[key]["label"] if key in UNIT_CLASSES else ""


def class_of(row):
    """The label of a game unit row's class (its promotion class and
    domain), e.g. "Light cavalry", or "" if no preset has it."""
    if not row:
        return ""
    for p in UNIT_CLASSES.values():
        c = p["columns"]
        if row.get("PromotionClass") == c["PromotionClass"] and \
                row.get("Domain") == c["Domain"]:
            return p["label"]
    return ""
