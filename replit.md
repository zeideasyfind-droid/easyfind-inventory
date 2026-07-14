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
- `POST /extract` — `{"url": "..."}` → `{"status": "success", "property_id": "...", "sheet_row": N}`
  (or `{"status": "duplicate", ...}` if already in the sheet)
- `GET /inventory` — dumps current sheet rows (added for convenience, not in original spec)

## Project structure

Existing repo layout (`frontend/`, `backend/`, `prompts/`, `Dockerfile`,
`cloudbuild.yaml`, `requirements.txt`) was preserved as-is per the
implementation spec — no reorganizing.

## User preferences

None recorded yet.
