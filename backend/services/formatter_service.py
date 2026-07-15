"""Deterministic template builder (07_FORMATTER_ENGINE.md /
10_EASYFIND_LISTING_TEMPLATE.md).

Final stage of the pipeline: Raw Message -> Parser -> Standardizer -> Maps
Enrichment -> Community Detection -> Template Builder -> Validator ->
Final Caption. Never invents a value and never generates marketing text --
every line comes straight from parsed/enriched fields, and any field that
wasn't found is simply omitted (never a placeholder).
"""


def _format_inr(amount: float) -> str:
    """Indian digit grouping: 200000 -> '₹2,00,000' (last 3 digits, then
    groups of 2, matching the example in 10_EASYFIND_LISTING_TEMPLATE.md)."""
    value = int(round(amount))
    sign = "-" if value < 0 else ""
    value = abs(value)
    digits = str(value)

    if len(digits) <= 3:
        grouped = digits
    else:
        last3 = digits[-3:]
        rest = digits[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        grouped = ",".join(groups) + "," + last3

    return f"{sign}\u20b9{grouped}"


def build_listing(parsed: dict, community_info: dict, maps_url: str | None) -> str:
    """Builds the final caption text. `parsed` is parser_service's output,
    `community_info` is community_service's classification result."""
    lines: list[str] = []

    header_parts = []
    if parsed.get("bhk_label"):
        header_parts.append(parsed["bhk_label"])
    if parsed.get("furnishing"):
        header_parts.append(parsed["furnishing"])
    if header_parts:
        lines.append(" | ".join(header_parts))
        lines.append("")

    money_lines = []
    if parsed.get("rent") is not None:
        rent_line = f"Rent: {_format_inr(parsed['rent'])}"
        if parsed.get("maintenance_applicable"):
            rent_line += " + Maintenance"
        money_lines.append(rent_line)
    if parsed.get("deposit") is not None:
        money_lines.append(f"Deposit: {_format_inr(parsed['deposit'])}")
    if money_lines:
        lines.extend(money_lines)
        lines.append("")

    detail_lines = []
    if parsed.get("area_label"):
        detail_lines.append(f"Area: {parsed['area_label']}")
    if parsed.get("bathrooms") is not None:
        detail_lines.append(f"Bathrooms: {parsed['bathrooms']}")
    if parsed.get("balcony") is not None:
        detail_lines.append(f"Balcony: {parsed['balcony']}")
    if detail_lines:
        lines.extend(detail_lines)
        lines.append("")

    if parsed.get("available_from"):
        lines.append(f"Available: {parsed['available_from']}")
        lines.append("")

    community = (community_info or {}).get("community", "Unknown")
    lines.append(f"Community: {community}")
    society = (community_info or {}).get("society")
    landmark = (community_info or {}).get("landmark")
    if society:
        lines.append("Society:")
        lines.append(society)
    elif landmark:
        lines.append("Landmark:")
        lines.append(landmark)
    lines.append("")

    if maps_url:
        lines.append("Maps:")
        lines.append(maps_url)
        lines.append("")

    if parsed.get("brokerage_applicable"):
        lines.append("Brokerage Applicable")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)
