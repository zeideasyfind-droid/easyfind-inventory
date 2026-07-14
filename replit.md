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

## User preferences

None recorded yet.
