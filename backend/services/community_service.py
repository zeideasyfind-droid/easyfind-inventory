"""Community classification (09_COMMUNITY_DETECTION.md).

Turns a maps_service enrichment result into one of EasyFind's three
community types. The keyword list below is the "configured rules"
09_GOOGLE_MAPS_ENRICHMENT.md refers to for telling a large gated
township/society apart from a smaller named apartment building -- update
this list as EasyFind's own classification conventions evolve; nothing
else in this module should need to change.
"""

_GATED_KEYWORDS = (
    "township",
    "layout",
    "enclave",
    "county",
    "meadows",
    "gardens",
    "habitat",
    "city",
    "nagar",
    "phase",
    "greens",
    "woods",
    "palm",
    "royale",
    "elite",
    "eco ",
)

# Only these place types indicate an actual named building/premise rather
# than a generic area or POI.
_NAMED_PLACE_TYPES = {"premise", "subpremise", "establishment", "lodging"}


def classify_community(place: dict | None) -> dict:
    """Returns {"community": ..., "society": ..., "landmark": ...}.

    Never expose the exact standalone property address (07_FORMATTER_ENGINE
    / 09_COMMUNITY_DETECTION) -- only a nearby public landmark is surfaced
    for Standalone listings, never formatted_address/coordinates.
    """
    if not place or not (place.get("name") or "").strip():
        return {"community": "Unknown", "society": None, "landmark": None}

    name = place["name"].strip()
    types = set(place.get("types") or [])

    if place.get("source") == "nearby":
        # No society name was ever known -- this is just the closest
        # public landmark to a raw pin, so the property is Standalone.
        return {"community": "Standalone", "society": None, "landmark": name}

    if not (types & _NAMED_PLACE_TYPES):
        # A named place was searched for but what Places returned isn't a
        # specific building -- treat it the same as "no known society".
        return {"community": "Standalone", "society": None, "landmark": name}

    lowered = name.lower()
    if any(keyword in lowered for keyword in _GATED_KEYWORDS):
        return {"community": "Gated", "society": name, "landmark": None}

    return {"community": "Semi-Gated", "society": name, "landmark": None}
