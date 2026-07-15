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
  • Never output Unknown, N/A, None, or any placeholder string.

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
      raw="87k"       → "87k"
      raw="2.5L"      → "2.5L"
      raw="Water bill" → "Water bill"
      raw=None, numeric=87000   → "87k"
      raw=None, numeric=250000  → "2.5L"
    """
    # Never treat a boolean (maintenance_applicable) as a raw amount
    if isinstance(raw, bool):
        raw = None
    if raw and str(raw).strip():
        # Sanity-check: reject if it's a nullish string
        cleaned = str(raw).strip()
        low = cleaned.lower()
        if low not in ("none", "null", "n/a", "na", "nil", "-"):
            return cleaned

    if numeric is None or isinstance(numeric, bool):
        return None
    n = float(numeric)
    if n == 0:
        return "Included"
    if n >= 100_000:
        lakh = n / 100_000
        return f"{int(lakh)}L" if lakh == int(lakh) else f"{lakh:.1f}L"
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
        parts.append(str(bhk))

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
                bal_str = f"{bal} balcony"
                if parts and parts[-1].startswith("with "):
                    parts[-1] += f", {bal_str}"
                else:
                    parts.append(f"with {bal_str}")
        except (TypeError, ValueError):
            pass

    return " ".join(parts)


def _community_label(community_info: dict) -> str | None:
    """Map internal community classification to EasyFind display label.
    Returns None when community is unknown/empty (field should be omitted).
    """
    raw = (community_info.get("community") or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low in ("gated community", "gated"):
        return "Gated Community"
    if low in ("semi gated", "semi-gated", "semi_gated"):
        return "Semi Gated"
    if low in ("standalone", "stand-alone", "independent"):
        return "Standalone"
    # Unknown, null-ish, or any unexpected value → omit
    if low in ("unknown", "none", "null", "n/a", "na", ""):
        return None
    # Pass through any other non-empty value as-is
    return raw


def _name_label_and_value(community_info: dict) -> tuple[str, str | None]:
    """Return (label, name) for the second-to-last block line.

    Gated Community  → label="Society",   value=society name
    Semi Gated       → label="Apartment", value=society/building name
    Standalone       → label="Landmark",  value=landmark name
    """
    community = (community_info.get("community") or "").strip().lower()
    society   = (community_info.get("society") or "").strip() or None
    landmark  = (community_info.get("landmark") or "").strip() or None

    if community in ("standalone", "stand-alone", "independent"):
        return "Landmark", landmark or society
    if community in ("semi gated", "semi-gated", "semi_gated"):
        return "Apartment", society or landmark
    # Default: Gated Community
    return "Society", society or landmark


# ── Main formatter ─────────────────────────────────────────────────────────────

def build_listing(parsed: dict, community_info: dict, maps_url: str | None) -> str:
    """Build the final EasyFind WhatsApp caption.

    Parameters
    ----------
    parsed : dict
        Output of parser_service.  Keys consulted:
          furnishing, bhk_label, bhk, bathrooms, balcony,
          rent_raw, rent, maintenance_raw, maintenance,
          deposit_raw, deposit,
          area (numeric), floor,
          available_from, tenant_type, pets_allowed,
          location.
    community_info : dict
        Output of community_service.classify_community().
        Keys: community, society, landmark, location.
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

    # Maintenance — only emit when a real value exists (not a boolean flag)
    maint_raw     = parsed.get("maintenance_raw")
    maint_numeric = parsed.get("maintenance")
    # If maintenance_raw is a non-boolean string, use it directly.
    # If it's None but we have a numeric, format it.
    # Never emit when only maintenance_applicable (bool) is set.
    maint = _preserve_amount(
        maint_raw if not isinstance(maint_raw, bool) else None,
        maint_numeric if not isinstance(maint_numeric, bool) else None,
    )
    if maint:
        lines.append(f"Maintenance: {maint}")

    # Deposit
    deposit = _preserve_amount(parsed.get("deposit_raw"), parsed.get("deposit"))
    if deposit:
        lines.append(f"Deposit: {deposit}")

    # Sq.ft — use raw numeric value (not area_label which appends "Sq. Ft.")
    area_raw = parsed.get("area")
    if area_raw is not None:
        try:
            area_num = float(area_raw)
            # Format as integer if whole number, else one decimal
            area_str = str(int(area_num)) if area_num == int(area_num) else f"{area_num:.1f}"
            lines.append(f"Sq.ft: {area_str}")
        except (TypeError, ValueError):
            pass

    # Floor — raw owner text preserved
    floor = (parsed.get("floor") or "").strip()
    if floor:
        lines.append(f"Floor: {floor}")

    # Available From — preserve owner text ("October 1", "Immediate", etc.)
    avail = (parsed.get("available_from") or "").strip()
    if avail:
        lines.append(f"Available From: {avail}")

    # Preferred Tenant — check both key names (parser uses tenant_type,
    # normalizer uses tenant_preference)
    tenant = (
        parsed.get("tenant_type")
        or parsed.get("tenant_preference")
        or ""
    ).strip().rstrip(" Only").strip()
    if tenant:
        lines.append(f"Preferred Tenant: {tenant}")

    # Pets — check both key names
    pets_raw = (
        parsed.get("pets_allowed")
        or parsed.get("pets")
        or ""
    ).strip()
    if pets_raw:
        low_pets = pets_raw.lower()
        if low_pets in ("yes", "allowed", "true", "1", "allowed"):
            lines.append("Pets: Allowed")
        elif low_pets in ("no", "not allowed", "false", "0", "not allowed"):
            lines.append("Pets: Not Allowed")
        else:
            lines.append(f"Pets: {pets_raw}")

    # Community — omit entirely when unknown/empty
    community_display = _community_label(ci)
    if community_display:
        lines.append(f"Community: {community_display}")

    # Location — prefer parsed location from owner message,
    # fall back to locality extracted from Maps address_components
    location = (
        (parsed.get("location") or "").strip()
        or (ci.get("location") or "").strip()
    )
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
