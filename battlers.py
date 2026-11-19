#!/usr/bin/env python3
"""Pin Battlers — original-creature battle game for Pin Book.

Design (Robert, 2026-11-18): original creatures only (no Disney
characters — family prototype, IP-safe), and one pin equals one
battler: every pin a user owns unlocks that pin's battler.

How it works:
- 6 creature species, one per element. A pin's battler species comes
  from its set (SET_ELEMENTS); unmapped sets fall back to a
  deterministic hash of the set name so every pin gets a battler.
- Stats scale with the pin's tier: common 1.0x, chaser 1.2x,
  super chaser 1.4x.
- Battles are turn-based 1v1 vs the computer: Attack (physical),
  Special (elemental, type effectiveness applies), Defend (halves
  the next hit taken). Damage = max(1, atk * power / def *
  type_mult * random 0.85-1.0).
"""
import hashlib
import random

# ---------------------------------------------------------------- species
# name, element, hp, attack, defense, special name, special power
SPECIES = {
    "ember": {
        "name": "Emberfox", "element": "ember", "hp": 90, "atk": 22,
        "def": 12, "special": "Flame Dash", "special_power": 30,
        "blurb": "A quick fox wreathed in flame. Hits hard, bruises easy.",
    },
    "tide": {
        "name": "Tidewhisker", "element": "tide", "hp": 100, "atk": 18,
        "def": 16, "special": "Tidal Splash", "special_power": 28,
        "blurb": "A sleek otter that rides the waves. Steady all-rounder.",
    },
    "leaf": {
        "name": "Bramblepaw", "element": "leaf", "hp": 95, "atk": 20,
        "def": 14, "special": "Thorn Whip", "special_power": 28,
        "blurb": "A forest prowler with thorns for claws. Patient hunter.",
    },
    "volt": {
        "name": "Voltbunny", "element": "volt", "hp": 80, "atk": 26,
        "def": 10, "special": "Static Hop", "special_power": 32,
        "blurb": "A crackling rabbit, fastest thing on four legs.",
    },
    "frost": {
        "name": "Snowhorn", "element": "frost", "hp": 105, "atk": 16,
        "def": 18, "special": "Glacier Ram", "special_power": 26,
        "blurb": "A shaggy ice-horned beast. Slow, stubborn, hard to hurt.",
    },
    "stone": {
        "name": "Pebbleback", "element": "stone", "hp": 120, "atk": 14,
        "def": 20, "special": "Boulder Roll", "special_power": 24,
        "blurb": "A boulder with legs. Hits like a landslide, moves like one.",
    },
}

ELEMENTS = list(SPECIES.keys())

# Attacker element -> defender element -> multiplier.
# Each element is strong (2x) against two, weak (0.5x) against two.
TYPE_CHART = {
    "ember": {"leaf": 2.0, "frost": 2.0, "tide": 0.5, "stone": 0.5},
    "tide": {"ember": 2.0, "stone": 2.0, "leaf": 0.5, "volt": 0.5},
    "leaf": {"tide": 2.0, "stone": 2.0, "ember": 0.5, "frost": 0.5},
    "volt": {"tide": 2.0, "frost": 2.0, "stone": 0.5, "leaf": 0.5},
    "frost": {"leaf": 2.0, "stone": 2.0, "ember": 0.5, "volt": 0.5},
    "stone": {"ember": 2.0, "volt": 2.0, "tide": 0.5, "leaf": 0.5},
}

TIER_MULT = {"common": 1.0, "chaser": 1.2, "super_chaser": 1.4}

# Set name -> element. Sets the kids collect from, curated 2026-11-18.
# Any set not listed falls back to a hash of its name (deterministic).
SET_ELEMENTS = {
    "Super Heroes T-Shirts": "ember",
    "Cupcakes": "ember",
    "Blue Color Story": "tide",
    "Ducks of Disney – Rubber Duckies": "tide",
    "Munchlings": "leaf",
    "Stitch Holidays": "volt",
    "Seasons - Donald Duck": "frost",
    "Holiday": "frost",
    "Character Donuts": "stone",
    "Cupcake Treats": "stone",
}


def element_for_set(set_name):
    """Element for a set: curated map, else a stable hash fallback."""
    if set_name in SET_ELEMENTS:
        return SET_ELEMENTS[set_name]
    digest = hashlib.md5(set_name.encode("utf-8")).hexdigest()
    return ELEMENTS[int(digest, 16) % len(ELEMENTS)]


def type_mult(attacker_element, defender_element):
    """Damage multiplier for an elemental move."""
    if attacker_element == defender_element:
        return 1.0
    return TYPE_CHART.get(attacker_element, {}).get(defender_element, 1.0)


def battler_for_pin(pin):
    """Build a battler dict for one owned pin.

    pin is a sqlite Row (or dict) with pin_name, tier, set_name,
    set_id, pin_id. Returns a plain dict (session-safe).
    """
    tier = pin["tier"] if isinstance(pin, dict) else pin["tier"]
    element = element_for_set(pin["set_name"])
    spec = SPECIES[element]
    mult = TIER_MULT.get(tier, 1.0)
    return {
        "pin_id": pin["pin_id"],
        "pin_name": pin["pin_name"],
        "set_name": pin["set_name"],
        "tier": tier,
        "species": spec["name"],
        "element": element,
        "blurb": spec["blurb"],
        "special": spec["special"],
        "special_power": round(spec["special_power"] * mult),
        "max_hp": round(spec["hp"] * mult),
        "atk": round(spec["atk"] * mult),
        "def": round(spec["def"] * mult),
    }


def random_ai_battler():
    """A computer opponent: random species, random tier (mostly common)."""
    element = random.choice(ELEMENTS)
    spec = SPECIES[element]
    tier = random.choices(["common", "chaser", "super_chaser"],
                          weights=[70, 25, 5])[0]
    mult = TIER_MULT[tier]
    return {
        "pin_id": None,
        "pin_name": "Wild " + spec["name"],
        "set_name": "Wild",
        "tier": tier,
        "species": spec["name"],
        "element": element,
        "blurb": spec["blurb"],
        "special": spec["special"],
        "special_power": round(spec["special_power"] * mult),
        "max_hp": round(spec["hp"] * mult),
        "atk": round(spec["atk"] * mult),
        "def": round(spec["def"] * mult),
    }


def calc_damage(attacker, defender, power, elemental):
    """Damage for one move. Returns (damage, effectiveness label)."""
    mult = 1.0
    label = ""
    if elemental:
        mult = type_mult(attacker["element"], defender["element"])
        if mult > 1.0:
            label = "It's super effective!"
        elif mult < 1.0:
            label = "It's not very effective..."
    raw = attacker["atk"] * power / max(1, defender["def"])
    dmg = max(1, int(round(raw * mult * random.uniform(0.85, 1.0))))
    return dmg, label
