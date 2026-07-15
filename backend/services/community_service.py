"""Community classification (09_COMMUNITY_DETECTION.md).

Turns a maps_service enrichment result into one of EasyFind's three
community types. The keyword list below is the "configured rules"
09_GOOGLE_MAPS_ENRICHMENT.md refers to for telling a large gated
township/society apart from a smaller named apartment building -- update
this list as EasyFind's own classification conventions evolve; nothing
else in this module should need to change.

Priority order
--------------
1. maps_service pre-classified community (from Google Place types)  — authoritative.
2. Google place types re-evaluated here against extended keyword set.
3. Owner message hint (owner_community / owner_society from parser).
4. Unknown fallback  — only when none of the above produced a result.

Locality
--------
If maps_service returned a locality (from address_components), it is
passed through as community_info["location"] so the formatter can always
emit a correct Location line without relying on the owner text parser.
"""
from __future__ import annotations

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
    "society",
    "residences",
    "grove",
    "villas",
    "heights",   # large villa complexes, not standalone
    "park",
)

_SEMI_GATED_KEYWORDS = (
    "apartment",
    "residency",
    "towers",
    "block",
    "building",
    "heights",
)

# Only these place types indicate an actual named building/premise rather
# than a generic area or POI.
_NAMED_PLACE_TYPES = {
    "premise",
    "subpremise",
    "establishment",
    "lodging",
    "apartment_complex",
    "apartment_building",
    "residential_complex",
    "housing_complex",
    "gated_community",
    "neighborhood",
    "point_of_interest",   # many large societies only get this from Google
}


def _normalise_community(raw: str | None) -> str | None:
    """Normalise any variant of community string to one of:
    'Gated Community', 'Semi Gated', 'Standalone', or None."""
    if not raw:
        return None
    low = raw.strip().lower()
    if low in ("gated community", "gated"):
        return "Gated Community"
    if low in ("semi gated", "semi-gated", "semi_gated"):
        return "Semi Gated"
    if low in ("standalone", "stand-alone", "independent"):
        return "Standalone"
    return None


def classify_community(place: dict | None, owner_hint: dict | None = None) -> dict:
    """Returns {"community": ..., "society": ..., "landmark": ...,
                "location": ...}.

    `place` (from maps_service) is always preferred when present -- it is
    the one source that can actually confirm a real building.

    `owner_hint` (parser_service's owner_community/owner_society, taken
    straight from labels like "Community: Gated Community" in the raw
    message) is only used when Maps enrichment produced nothing at all.

    Never expose the exact standalone property address -- only a nearby
    public landmark is surfaced for Standalone listings.
    """
    locality: str | None = None

    # ── Priority 1: maps_service pre-classification ───────────────────────────
    if place and (place.get("name") or "").strip():
        name      = place["name"].strip()
        types     = set(place.get("types") or [])
        locality  = place.get("locality")  # from address_components

        # Use maps_service classification when it's already done the work.
        maps_community = _normalise_community(place.get("community"))

        if place.get("source") == "nearby":
            # Raw pin fallback — nearest landmark only.
            return {
                "community": "Standalone",
                "society":   None,
                "landmark":  name,
                "location":  locality,
            }

        if maps_community == "Standalone":
            # maps_service only returns Standalone via the nearby path above
            # or when types are exclusively point_of_interest.  Trust it.
            return {
                "community": "Standalone",
                "society":   None,
                "landmark":  name,
                "location":  locality,
            }

        # Named place confirmed — resolve Gated vs Semi Gated.
        lowered = name.lower()

        if maps_community == "Gated Community":
            return {
                "community": "Gated Community",
                "society":   name,
                "landmark":  None,
                "location":  locality,
            }

        if maps_community == "Semi Gated":
            # Double-check with keywords: a large complex misclassified by
            # Google types should still be Gated Community.
            if any(kw in lowered for kw in _GATED_KEYWORDS):
                return {
                    "community": "Gated Community",
                    "society":   name,
                    "landmark":  None,
                    "location":  locality,
                }
            return {
                "community": "Semi Gated",
                "society":   name,
                "landmark":  None,
                "location":  locality,
            }

        # ── Priority 2: local re-evaluation when maps_service gave no label ───
        if types & _NAMED_PLACE_TYPES:
            if any(kw in lowered for kw in _GATED_KEYWORDS):
                return {
                    "community": "Gated Community",
                    "society":   name,
                    "landmark":  None,
                    "location":  locality,
                }
            if any(kw in lowered for kw in _SEMI_GATED_KEYWORDS):
                return {
                    "community": "Semi Gated",
                    "society":   name,
                    "landmark":  None,
                    "location":  locality,
                }
            # Named place but no keyword match — default to Semi Gated,
            # never Standalone from a named place.
            return {
                "community": "Semi Gated",
                "society":   name,
                "landmark":  None,
                "location":  locality,
            }

        # Types are too generic (e.g. point_of_interest only) but the place
        # has a proper name — still try keyword heuristics before giving up.
        if any(kw in lowered for kw in _GATED_KEYWORDS):
            return {
                "community": "Gated Community",
                "society":   name,
                "landmark":  None,
                "location":  locality,
            }
        if any(kw in lowered for kw in _SEMI_GATED_KEYWORDS):
            return {
                "community": "Semi Gated",
                "society":   name,
                "landmark":  None,
                "location":  locality,
            }
        # Named place, no type match, no keyword match → Semi Gated
        # (never Standalone just because keywords didn't fire)
        return {
            "community": "Semi Gated",
            "society":   name,
            "landmark":  None,
            "location":  locality,
        }

    # ── Priority 3: owner hint from parsed message ────────────────────────────
    owner_hint = owner_hint or {}
    community  = _normalise_community(owner_hint.get("owner_community"))
    society    = (owner_hint.get("owner_society") or "").strip() or None
    if community or society:
        return {
            "community": community or "Semi Gated",
            "society":   society,
            "landmark":  None,
            "location":  None,
        }

    # ── Priority 4: Unknown — no data at all ─────────────────────────────────
    return {"community": None, "society": None, "landmark": None, "location": None}
