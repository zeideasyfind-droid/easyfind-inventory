"""Deterministic template builder — EasyFind listing formatter.

Final stage of the pipeline:
  Raw Message → Parser → Normalizer → Maps Enrichment → Community Detection
  → Formatter → Validator → WhatsApp caption

Rules (non-negotiable):
  • Output is structurally identical to a hand-written EasyFind inventory post.
  • Never invent a value; never add marketing text, emojis or branding.
  • Preserve broker shorthand exactly as parsed:
      87k  2.5L  Water bill  October 1  Family  Not Allowed
    Do NOT convert to ₹87,000 / ₹2,50,000 / ISO dates.
  • Field order is fixed and must never change.
  • Sentence case for the title line only.
  • Any field that was not parsed is simply omitted — never a placeholder.

Canonical output format:

    Fully furnished 4 BHK with 3 bathrooms, 2 balcony

    Rent: 87k
    Maintenance: Water bill
    Deposit: 2.5L
    Sq.ft: 2850
    Floor: 2 Story Villa
    Available From: October 1
    Preferred Tenant: Family
    Pets: Not Allowed
    Community: Gated Community
    Location: *Sarjapur Road*

    *Odion The Woods of East*
    https://maps.app.goo.gl/xxxxxxxx
"""

from __future__ import annotations


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sentence_case(s: str) -> str:
    """First character upper, rest untouched (preserves '4 BHK', 'BDA', etc.)."""
    if not s:
        return ""
    return s[0].upper() + s[1:]


def _preserve_amount(raw: str | None, numeric: float | None) -> str | None:
    """Return the broker shorthand string when available; fall back to a
    compact numeric representation only when no text was captured.

    Examples:
      raw="87k"    → "87k"
      raw="2.5L"   → "2.5L"
      raw="Water bill" → "Water bill"
      raw=None, numeric=87000 → "87k"
      raw=None, numeric=250000 → "2.5L"
    """
    if raw and raw.strip():
        return raw.strip()
    if numeric is None:
        return None
    n = float(numeric)
    if n >= 100_000:
        l = n / 100_000
        return f"{int(l)}L" if l == int(l) else f"{l:.1f}L"
    if n >= 1_000:
        k = n / 1_000
        return f"{int(k)}k" if k == int(k) else f"{k:.1f}k"
    return str(int(n))


def _build_title(parsed: dict) -> str:
    """Produce the sentence-case title line.

    Pattern: <Furnishing> <BHK> with <N> bathroom(s), <N> balcony
    Any component that is missing is simply skipped.
    """
    parts: list[str] = []

    furnishing = (parsed.get("furnishing") or "").strip()
    if furnishing:
        # Normalise common variants to title words, then sentence-case the whole.
        low = furnishing.lower()
        if "fully" in low:
            parts.append("Fully furnished")
        elif "semi" in low or "partial" in low:
            parts.append("Semi furnished")
        elif "unfurnish" in low or "un-furnish" in low:
            parts.append("Unfurnished")
        else:
            parts.append(_sentence_case(furnishing))

    bhk = (parsed.get("bhk_label") or parsed.get("bhk") or "").strip()
    if bhk:
        parts.append(bhk)

    bath = parsed.get("bathrooms")
    if bath is not None:
        try:
            b = int(bath)
            parts.append(f"with {b} {'bathroom' if b == 1 else 'bathrooms'}")
        except (TypeError, ValueError):
            pass

    balcony = parsed.get("balcony")
    if balcony is not None:
        try:
            bal = int(balcony)
            if bal > 0:
                bal_str = f"{bal} {'balcony' if bal == 1 else 'balcony'}"
                # Append to the "with N bathroom(s)" phrase if present
                if parts and parts[-1].startswith("with "):
                    parts[-1] += f", {bal_str}"
                else:
                    parts.append(f"with {bal_str}")
        except (TypeError, ValueError):
            pass

    return " ".join(parts)


def _community_label(community_info: dict) -> str:
    """Map internal community classification to EasyFind display label."""
    raw = (community_info.get("community") or "").strip()
    low = raw.lower()
    if "semi" in low:
        return "Semi Gated"
    if "stand" in low or "alone" in low:
        return "Standalone"
    if "gated" in low or raw == "Gated":
        return "Gated Community"
    return raw if raw else "Gated Community"


def _name_label_and_value(community_info: dict) -> tuple[str, str | None]:
    """Return (label, name) for the second-to-last block line.

    Gated Community  → label="Society",   value=society name
    Semi Gated       → label="Apartment", value=society/building name
    Standalone       → label="Landmark",  value=landmark name
    """
    community = (community_info.get("community") or "").lower()
    society  = community_info.get("society")
    landmark = community_info.get("landmark")

    if "semi" in community:
        return "Apartment", society or landmark
    if "stand" in community or "alone" in community:
        return "Landmark", landmark or society
    # Default: Gated Community
    return "Society", society or landmark


# ── Main formatter ─────────────────────────────────────────────────────────────

def build_listing(parsed: dict, community_info: dict, maps_url: str | None) -> str:
    """Build the final EasyFind WhatsApp caption.

    Parameters
    ----------
    parsed : dict
        Output of parser_service / normalizer.  Keys consulted:
          furnishing, bhk_label, bhk, bathrooms, balcony,
          rent_raw, rent, maintenance_raw, maintenance,
          deposit_raw, deposit, area_label, floor,
          available_from, tenant_type, pets_allowed,
          location.
    community_info : dict
        Output of community_service.classify_community().
        Keys: community, society, landmark.
    maps_url : str | None
        Resolved Google Maps link (already shortened or full).
    """
    ci = community_info or {}
    lines: list[str] = []

    # ── Title ─────────────────────────────────────────────────────────────────
    title = _build_title(parsed)
    if title:
        lines.append(title)
        lines.append("")

    # ── Field block ───────────────────────────────────────────────────────────
    # Rent
    rent = _preserve_amount(parsed.get("rent_raw"), parsed.get("rent"))
    if rent:
        lines.append(f"Rent: {rent}")

    # Maintenance
    maint = _preserve_amount(parsed.get("maintenance_raw"), parsed.get("maintenance"))
    if maint:
        lines.append(f"Maintenance: {maint}")

    # Deposit
    deposit = _preserve_amount(parsed.get("deposit_raw"), parsed.get("deposit"))
    if deposit:
        lines.append(f"Deposit: {deposit}")

    # Sq.ft
    area = (parsed.get("area_label") or parsed.get("area") or "").strip()
    if area:
        lines.append(f"Sq.ft: {area}")

    # Floor
    floor = (parsed.get("floor") or "").strip()
    if floor:
        lines.append(f"Floor: {floor}")

    # Available From — preserve owner text (e.g. "October 1", "Immediate")
    avail = (parsed.get("available_from") or "").strip()
    if avail:
        lines.append(f"Available From: {avail}")

    # Preferred Tenant
    tenant = (parsed.get("tenant_type") or "").strip().rstrip(" Only").strip()
    if tenant:
        lines.append(f"Preferred Tenant: {tenant}")

    # Pets
    pets_raw = (parsed.get("pets_allowed") or "").strip().lower()
    if pets_raw in ("yes", "allowed", "true", "1"):
        lines.append("Pets: Allowed")
    elif pets_raw in ("no", "not allowed", "false", "0"):
        lines.append("Pets: Not Allowed")
    elif pets_raw:
        lines.append(f"Pets: {parsed['pets_allowed'].strip()}")

    # Community
    lines.append(f"Community: {_community_label(ci)}")

    # Location  (WhatsApp bold)
    location = (parsed.get("location") or "").strip()
    if location:
        lines.append(f"Location: *{location}*")

    # ── Society / Apartment / Landmark + Maps link ────────────────────────────
    label, name_value = _name_label_and_value(ci)
    if name_value or maps_url:
        lines.append("")
        if name_value:
            lines.append(f"*{name_value}*")
        if maps_url:
            lines.append(maps_url)

    # Strip trailing blank lines
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)
