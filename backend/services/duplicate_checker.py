"""Confidence-based duplicate detection against rows already in Google Sheets.

The goal is to keep exactly one PID for one physical property while
preserving the existing extraction pipeline. Matching prefers canonical
listing URLs when available, then falls back to a weighted confidence
score across multiple stable property signals.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "source",
    "campaign",
}

_MONEY_LAKH_RE = re.compile(r"([\d.]+)\s*l(?:akh)?s?\b", re.IGNORECASE)
_MONEY_THOUSAND_RE = re.compile(r"([\d.]+)\s*k\b", re.IGNORECASE)
_MONEY_DIGITS_RE = re.compile(r"[\d.]+")


@dataclass(frozen=True)
class MatchResult:
    row: dict | None
    confidence: int
    classification: str
    fingerprint: str
    matched_on: str


def _norm(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _norm_number(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)

    text = str(value).strip()
    if not text:
        return None

    lakh_match = _MONEY_LAKH_RE.search(text)
    if lakh_match:
        return round(float(lakh_match.group(1)) * 100000, 2)

    thousand_match = _MONEY_THOUSAND_RE.search(text)
    if thousand_match:
        return round(float(thousand_match.group(1)) * 1000, 2)

    digits_match = _MONEY_DIGITS_RE.search(text.replace(",", ""))
    if digits_match:
        return round(float(digits_match.group()), 2)

    return None


def canonicalize_url(url: str | None) -> str:
    if not url:
        return ""
    text = str(url).strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlparse(text)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or ""
    if path != "/":
        path = path.rstrip("/")
    path = path or "/"
    filtered_qs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower() in _TRACKING_QUERY_KEYS:
            continue
        filtered_qs.append((key.lower(), value))
    filtered_qs.sort()
    query = urlencode(filtered_qs)
    return urlunparse(("https", host, path, "", query, ""))


def _numeric_close(a, b, tolerance: float) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tolerance


def _fingerprint_parts(property_dict: dict) -> list[str]:
    return [
        _norm(property_dict.get("portal")),
        _norm(property_dict.get("society_name")),
        _norm(property_dict.get("property_location")),
        _norm(property_dict.get("contact_number")),
        str(int(property_dict.get("bhk"))) if property_dict.get("bhk") not in (None, "") and float(property_dict.get("bhk")).is_integer() else _norm(property_dict.get("bhk")),
        str(int(property_dict.get("area"))) if property_dict.get("area") not in (None, "") and float(property_dict.get("area")).is_integer() else _norm(property_dict.get("area")),
        _norm(property_dict.get("floor_label")),
    ]


def generate_property_fingerprint(property_dict: dict) -> str:
    parts = [part for part in _fingerprint_parts(property_dict) if part]
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest() if joined else ""


def _score_row(candidate: dict, row: dict) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    candidate_url = canonicalize_url(candidate.get("url"))
    row_url = canonicalize_url(row.get("url"))
    if candidate_url and row_url and candidate_url == row_url:
        return 100, ["canonical_url"]

    if _norm(candidate.get("portal")) and _norm(candidate.get("portal")) == _norm(row.get("portal")):
        score += 8
        reasons.append("portal")

    if _norm(candidate.get("society_name")) and _norm(candidate.get("society_name")) == _norm(row.get("society_name")):
        score += 22
        reasons.append("society_name")

    if _norm(candidate.get("property_location")) and _norm(candidate.get("property_location")) == _norm(row.get("property_location")):
        score += 15
        reasons.append("property_location")

    if _norm(candidate.get("contact_number")) and _norm(candidate.get("contact_number")) == _norm(row.get("contact_number")):
        score += 20
        reasons.append("contact_number")

    if _norm(candidate.get("owner_name")) and _norm(candidate.get("owner_name")) == _norm(row.get("owner_name")):
        score += 8
        reasons.append("owner_name")

    if candidate.get("bhk") is not None and row.get("bhk") is not None and float(candidate.get("bhk")) == float(row.get("bhk")):
        score += 8
        reasons.append("bhk")

    candidate_area = _norm_number(candidate.get("area"))
    row_area = _norm_number(row.get("area"))
    if _numeric_close(candidate_area, row_area, 50):
        score += 8
        reasons.append("area")

    candidate_rent = _norm_number(candidate.get("rent"))
    row_rent = _norm_number(row.get("rent"))
    if _numeric_close(candidate_rent, row_rent, 2000):
        score += 6
        reasons.append("rent")

    candidate_deposit = _norm_number(candidate.get("deposit"))
    row_deposit = _norm_number(row.get("deposit"))
    if _numeric_close(candidate_deposit, row_deposit, 10000):
        score += 3
        reasons.append("deposit")

    if _norm(candidate.get("floor_label")) and _norm(candidate.get("floor_label")) == _norm(row.get("floor_label")):
        score += 2
        reasons.append("floor_label")

    candidate_fp = generate_property_fingerprint(candidate)
    row_fp = generate_property_fingerprint(row)
    if candidate_fp and row_fp and candidate_fp == row_fp:
        score += 25
        reasons.append("fingerprint")

    return min(score, 99), reasons


def find_best_match(candidate: dict, existing_rows: list) -> MatchResult:
    candidate = dict(candidate or {})
    candidate["canonical_url"] = canonicalize_url(candidate.get("url"))
    candidate["property_fingerprint"] = generate_property_fingerprint(candidate)

    best_row = None
    best_score = -1
    best_reasons: list[str] = []
    for row in existing_rows:
        enriched_row = dict(row)
        enriched_row["canonical_url"] = canonicalize_url(row.get("url"))
        enriched_row["property_fingerprint"] = generate_property_fingerprint(enriched_row)
        score, reasons = _score_row(candidate, enriched_row)
        if score > best_score:
            best_row = row
            best_score = score
            best_reasons = reasons

    if best_score >= 95:
        classification = "definite_duplicate"
    elif best_score >= 80:
        classification = "likely_duplicate"
    else:
        classification = "new_property"
        best_row = None

    matched_on = ",".join(best_reasons) if best_reasons else "no_match"
    return MatchResult(
        row=best_row,
        confidence=max(best_score, 0),
        classification=classification,
        fingerprint=candidate["property_fingerprint"],
        matched_on=matched_on,
    )


def find_matching_row(candidate: dict, existing_rows: list) -> dict | None:
    return find_best_match(candidate, existing_rows).row
