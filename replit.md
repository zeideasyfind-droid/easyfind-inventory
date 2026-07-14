# EasyFind Inventory Engine

A broker pastes a property listing URL (Housing.com), and the app scrapes
it with Firecrawl, uses Firecrawl's built-in LLM extraction to turn the
page into structured JSON, normalizes the fields, checks for duplicates,
archives the raw JSON, and appends a row to a Google Sheet.

## Stack

- **Backend:** FastAPI + Uvicorn (Python 3.12)
- **Frontend:** Vanilla HTML/CSS/JS, served by FastAPI from `frontend/`
- **Extraction:** Firecrawl `/v1/scrape` with `formats: ["json"]` (Firecrawl
  runs its own LLM extraction against `prompts/firecrawl_prompt.txt` and a
  JSON schema — no separate OpenAI key needed)
- **Storage:** Google Sheets (inventory rows) via a service account;
  Google Drive (JSON archives) if `GOOGLE_DRIVE_FOLDER_ID` is set, else
  local `archives/YYYY/MM/DD/` folders

## Google Sheets integration

Writes go to a **fixed, pre-existing worksheet** — `April 2026 - March 2027`
inside spreadsheet `GOOGLE_SHEET_ID`. The app never creates a worksheet;
if that tab is missing, `/extract` fails with a clear error instead of
creating a new one (`backend/services/google_sheets.py`).

Columns A-W have a fixed mapping (date, onboarding status, property
location, society name, owner name, contact info, BHK, bathrooms,
balcony, area, floor/total floors, furnishing, tenant preference,
veg/non-veg, pets, rent, maintenance, deposit, available-from,
negotiations, visit timings, portal, URL) — see `COLUMNS` in that file
and the normalization rules in `backend/services/normalizer.py`.

**Upsert rule, not reject-on-duplicate:** before writing, the app looks
for an existing row matching the listing URL (column W); if found, that
row is updated in place. If the candidate has no URL, it falls back to
matching Contact Number + Society Name + Rent. See
`backend/services/duplicate_checker.py`.

Writes use an explicit `A{row}:W{row}` range via `values().update()`,
never `values().append()`. Sheets' append-with-autodetect was found to
mis-identify which column a table starts in when column A has no header
text and is entirely blank (true for this sheet's historical data),
silently shifting an entire row one column to the right. Always compute
the target row explicitly and write with `update()` instead.

## Running locally on Replit

The `Start application` workflow runs:

```
uvicorn backend.main:app --host 0.0.0.0 --port 5000 --reload
```

Cloud Run / Docker instead uses `PORT` (default 8080), per the
`Dockerfile` and `cloudbuild.yaml`.

## Required environment variables / secrets

Set these as Replit Secrets before extraction will fully work:

- `FIRECRAWL_API_KEY` — from firecrawl.dev
- `GOOGLE_SHEET_ID` — the target spreadsheet's ID
- `GOOGLE_SERVICE_ACCOUNT_JSON` — full JSON key for a Google service
  account with access to Sheets (and Drive, if used); the sheet (and
  Drive folder) must be shared with the service account's email
- `GOOGLE_DRIVE_FOLDER_ID` — optional; if unset, JSON archives are saved
  to local disk instead of Drive

Without these, `/health` and the frontend still work, but `/extract`
returns a clear error explaining which variable is missing.

## API

- `GET /` — frontend
- `GET /health` — `{"status": "ok"}`
- `POST /extract` — `{"url": "..."}` → `{"status": "success", "action": "inserted"|"updated", "property_id": "...", "sheet_row": N}`
  (upserts by Listing URL, or by Contact Number + Society Name + Rent if no URL match)
- `GET /inventory` — dumps current sheet rows (added for convenience, not in original spec)

## Project structure

Existing repo layout (`frontend/`, `backend/`, `prompts/`, `Dockerfile`,
`cloudbuild.yaml`, `requirements.txt`) was preserved as-is per the
implementation spec — no reorganizing.

## Multi-portal support & contact rescue (2026-07-14)

- **Portal detection:** `backend/utils.py::detect_portal(url)` maps a
  listing URL's domain to its portal name (MyGate, 99acres, MagicBricks,
  CommonFloor, NoBroker, Makaan, Housing.com); `extract.py` sets column V
  from this instead of the old hardcoded `"Housing.com"`. Homepage copy
  (`frontend/index.html`) now mentions all 7 portals with a generic
  "Paste a property URL..." placeholder.
- **Contact number rescue:** Firecrawl is now asked for `markdown`,
  `html`, and `rawHtml` in addition to `json` (the extraction schema
  itself is unchanged). `backend/services/contact_extractor.py` searches
  all of them for a complete, unmasked Indian mobile number and uses it
  if found; masked/partial numbers never match (they contain non-digit
  placeholder characters) and are never inferred or reconstructed. If
  nothing valid is found, the contact field is left empty.
- **Column B / URL preservation:** already correct before this change —
  `_NEVER_OVERWRITE_ON_UPDATE` in `google_sheets.py` protects
  `onboarding_status` (column B) on every update, and `extract.py` always
  writes the exact pasted `url` (never a Firecrawl-resolved/redirect
  URL) to column W. Verified, not modified.

## Setup status

Imported project fully set up on 2026-07-14: Python 3.12 + all `requirements.txt`
packages installed, `Start application` workflow running cleanly on port 5000,
and all required secrets (`FIRECRAWL_API_KEY`, `GOOGLE_SHEET_ID`,
`GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_DRIVE_FOLDER_ID`) configured.

A `HANDOVER.md` was referenced by a pasted instruction set (multi-portal UI
copy, contact-extraction improvements, a Column B overwrite bug, and a
redirect-URL bug) but does not exist anywhere in this repo. That work was
captured as a separate follow-up project task instead of guessed at here.

## User preferences

None recorded yet.
