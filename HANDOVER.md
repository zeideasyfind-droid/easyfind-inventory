# Handover — Multi-Portal Bug Fixes (EasyFind Inventory Engine)

> **Read this entire file before writing any code.** It reflects verified, current-state findings (some bugs already fixed and confirmed live) — do not re-diagnose from scratch or redo work described as already done below.

Work directly on the connected GitHub repository, on the existing branch. Do not create a new repo, clone elsewhere, or use temp directories. Do not touch anything outside the 3 points below (Firecrawl prompt/schema, normalization logic, sheet column mapping, duplicate detection, backend architecture, API routes, Dockerfile, Cloud Build/Run config, and env vars are all out of scope unless explicitly called out here).

Context: this repo scrapes rental listings via Firecrawl and writes rows to a fixed Google Sheet worksheet ("April 2026 - March 2027", columns A–W). It was built and tested against Housing.com only; the user now needs it to work across 7 portals (MyGate, 99acres, MagicBricks, CommonFloor, NoBroker, Makaan, Housing.com). A live test run against 5 real listings (see Validation below) surfaced the concrete bugs consolidated into the 3 points below.

---

## Point 1 — Multi-portal identity: UI text + `portal` column

Two parts, same root cause (the app still assumes "Housing.com" everywhere):

1. **Homepage copy** (`frontend/` — index/template + JS, UI text only): replace Housing.com-specific wording with portal-agnostic wording covering MyGate, 99acres, MagicBricks, CommonFloor, NoBroker, Makaan, Housing.com. Change the input placeholder to exactly `Paste a property URL...`. No other UI/layout changes.
2. **`portal` column is hardcoded** — confirmed bug: `backend/services/normalizer.py::normalize_property()` sets `"portal": "Housing.com"` unconditionally on every row, regardless of the actual source site. Fix: derive the portal name from the input URL's domain (e.g. `99acres.com` → "99acres", `link.mygate.com`/`mygate.com` → "MyGate", `magicbricks.com` → "MagicBricks", `commonfloor.com` → "CommonFloor", `nobroker.in` → "NoBroker", `makaan.com` → "Makaan", `housing.com` → "Housing.com"). Do not touch the Firecrawl prompt/schema or any other normalizer field to do this.

**Known separate issue, do not silently paper over it:** Housing.com itself currently returns a bot-protection block page to Firecrawl ("Request Blocked... suspicious activity") for at least one real listing — this is not an extraction bug, it's Housing.com's anti-bot wall. If it reproduces, surface a clear error to the user instead of writing an empty/garbage row (extraction already raises `FirecrawlError` on outright API failures — check whether this blocked-page case is instead returning HTTP 200 with empty JSON, which would currently sail through as a "successful" row of nulls; if so, treat all-null extraction as a failure to report, not a silent insert).

## Point 2 — Contact number extraction accuracy

Improve the *existing* contact field only — do not change the Firecrawl JSON schema. After Firecrawl returns its result, also search the fetched content itself (markdown/html/rawHtml, descriptions, broker/owner notes, header/footer, any other text Firecrawl returns) for a valid, complete Indian mobile number, and populate the contact field if one is found there but not in the direct field.

Hard constraints:
- Never infer, reconstruct, or "unmask" a partially hidden number (e.g. MagicBricks currently shows `+91-98XXXXXXXX` — confirmed masked in testing; leave the field blank for rows like this).
- No browser automation, no clicking "Show Contact", no login/OTP flows, no bypassing portal restrictions.
- If no complete number exists anywhere in the fetched content, leave the field empty (this is already correct behavior when Firecrawl returns `null`/`"null"` — the normalizer's `_clean_str` already nulls those out; just don't regress it).

## Point 3 — Google Sheets write correctness (verify, mostly already fixed)

Both of these were already root-caused and fixed earlier in the current codebase — **this point is a verification/regression pass, not a rewrite**, unless testing reveals the fix is incomplete:

- **Column B (Onboarding Status) must never be overwritten by the engine.** `backend/services/google_sheets.py` already has a `_NEVER_OVERWRITE_ON_UPDATE = {"onboarding_status"}` set plus a `_merge_for_update()` step used inside `upsert_row()`, which preserves column B (and any column with no new extracted value) on updates. This was live-tested against the real sheet this session and confirmed working. Re-verify it still holds after Points 1–2's changes; do not remove or weaken it.
- **Original pasted URL must be preserved verbatim** (column W), even for shortlinks like `https://link.mygate.com/gz2trg` that redirect elsewhere. Current code already stores `normalized["url"] = url` where `url` is the raw request payload the user pasted — not anything Firecrawl resolves internally — so this should already be correct. Confirm with the MyGate shortlink specifically that column W ends up with the exact short URL, not a redirect/auth/session URL.

---

## Validation (run end-to-end for all 5, do not skip any)

- `https://www.99acres.com/3-bhk-bedroom-apartment-flat-for-rent-in-ars-signature-homes-kada-agrahara-bangalore-east-1280-sqft-spid-P92416104`
- `https://housing.com/rent/20577772-1200-sqft-2-bhk-independent-house-on-rent-in-hsr-layout-bengaluru`
- `https://link.mygate.com/gz2trg`
- `https://www.magicbricks.com/propertyDetails/2-BHK-1150-Sq-ft-Multistorey-Apartment-FOR-Rent-Electronic-City-in-Bangalore&id=4d423835343736373537`
- `https://www.commonfloor.com/listing/semi-furnished-3bhk-apartment-for-rent-in-old-airport-road-bangalore-at-golf-manor-apartment/ynnyrqjokrmpif6s`

For each, confirm: extraction succeeds (or fails loudly/visibly, for the Housing.com block case); `portal` column matches the real source site; column W has the exact URL the user pasted; contact number is populated only when a complete real number was found in the content, and stays blank for masked ones (99acres, MagicBricks); the sheet row lands correctly; column B is untouched; no regression elsewhere.

**Baseline extraction results from this session (for comparison, not to be treated as ground truth if the site changes):** 99acres, MyGate, CommonFloor extracted cleanly. MagicBricks extracted cleanly except masked phone. Housing.com returned an anti-bot block page (all fields empty) — expected to still fail unless that block is IP/rate-limit related and clears on retry.

## Deliverables expected back
1. Files modified.
2. Root cause of each bug fixed.
3. Validation results for all 5 URLs above.
4. Commit hash.
5. Pull Request URL (preferred) or confirmation the push landed on the working branch.

If any validation fails, stop before pushing and report the failure rather than making unrelated changes.
