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
- `GOOGLE_MAPS_API_KEY` — Module 2 only; Google Places enrichment
- `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` — Module 2 only;
  WhatsApp Cloud API (Meta) credentials for the sending account
- `WHATSAPP_RECIPIENT_NUMBER` — Module 2 only; the configured EasyFind
  Business WhatsApp number that generated listings are delivered to
  (international format, e.g. `91XXXXXXXXXX`)

Without these, `/health` and the frontend still work, but `/extract`
returns a clear error explaining which variable is missing, and
`/publish/send` returns `success: false` with the formatted caption
still attached if the Module 2 secrets aren't set.

## API

- `GET /` — frontend
- `GET /health` — `{"status": "ok"}`
- `POST /extract` — `{"url": "..."}` → `{"status": "success", "action": "inserted"|"updated", "property_id": "...", "sheet_row": N}`
  (upserts by Listing URL, or by Contact Number + Society Name + Rent if no URL match)
- `GET /inventory` — dumps current sheet rows (added for convenience, not in original spec)
- `POST /publish/preview` — multipart `owner_message` + `images[]` →
  `{"success": true, "preview": "...", "community": "...", "society"|"landmark": "..."}`
- `POST /publish/send` — same request shape → delivers the WhatsApp media
  album, `{"success": true, "message_id": "...", "image_count": N, "delivery": "sent"}`

## Project structure

Existing repo layout (`frontend/`, `backend/`, `prompts/`, `Dockerfile`,
`cloudbuild.yaml`, `requirements.txt`) was preserved as-is per the
implementation spec — no reorganizing.

## Multi-portal support (2026-07-14)

- **Portal detection:** `backend/utils.py::detect_portal(url)` maps a
  listing URL's domain to its portal name (MyGate, 99acres, MagicBricks,
  CommonFloor, NoBroker, Makaan, Housing.com); `extract.py` sets column V
  from this instead of the old hardcoded `"Housing.com"`. Homepage copy
  (`frontend/index.html`) now mentions all 7 portals with a generic
  "Paste a property URL..." placeholder.
- **Column B / URL preservation:** `_NEVER_OVERWRITE_ON_UPDATE` in
  `google_sheets.py` protects `onboarding_status` (column B) on every
  update, and `extract.py` always writes the exact pasted `url` (never a
  Firecrawl-resolved/redirect URL) to column W.
- **Column B on new rows:** `normalizer.py::normalize_property()` leaves
  `onboarding_status` as `None` (blank) for brand-new rows too — it's a
  manually-maintained broker field and the automation never writes a
  default value into it.
- **Contact number:** comes only from Firecrawl's direct JSON extraction
  (`formats: ["json"]`). A markdown/html/rawHtml "rescue" pass that
  chased masked/missing numbers elsewhere on the page was tried and then
  removed — it cost extra Firecrawl credits per scrape for numbers that
  are usually masked by design; masked/missing numbers are now simply
  left blank for manual entry.

## Module 2 — Property Publishing Engine (2026-07-15)

Independent from Module 1 (Inventory Engine above); implemented from a
20-document spec bundle (`00_README.md` .. `19_REPLIT_IMPLEMENTATION_CHECKLIST.md`).
Converts a pasted owner message + uploaded photos into one EasyFind-formatted
WhatsApp media album.

**Pipeline** (`backend/api/publish.py`): raw owner message → `parser_service`
(regex-only, deterministic, never invents a value) → `maps_service` (resolves
the Maps URL found in the message, including shortened `maps.app.goo.gl`
links, then queries Google Places) → `community_service` (classifies
Gated / Semi-Gated / Standalone / Unknown) → `formatter_service` (builds the
fixed-template caption, Indian ₹ digit grouping) → `whatsapp_service`
(uploads each image to WhatsApp Cloud API, sends one image message per
photo in original order, caption attached to the first only).

- **Gated vs. Semi-Gated vs. Standalone:** only a Maps pin with an explicit
  place name (a society/building) can produce Gated/Semi-Gated;
  `community_service._GATED_KEYWORDS` is the configurable rule set for
  telling a large township apart from a single building — update that list
  as EasyFind's own conventions evolve. A raw pin with no name, or a Maps
  lookup failure, always falls back to Standalone/Unknown with just a
  nearby public landmark — the exact address is never exposed.
- **Failure handling:** a Google Maps failure never blocks formatting
  (falls back to `Community: Unknown`, keeps the original Maps URL). A
  WhatsApp send failure returns `success: false` with the *already
  generated* caption text still attached, so nothing has to be
  reformatted to retry.
- **Endpoints:** `POST /publish/preview` and `POST /publish/send`
  (multipart: `owner_message` + `images[]`). Neither the browser nor any
  frontend code ever calls Google Maps or WhatsApp directly — all
  credentials stay server-side (`backend/config.py`).
- **Frontend:** a second card below the Inventory Engine
  (`frontend/publish.js` / `#publish-card` in `index.html`) — textarea for
  the owner message, drag-and-drop image uploader, preview panel, then a
  Send button.
- **Secrets:** `GOOGLE_MAPS_API_KEY`, `WHATSAPP_ACCESS_TOKEN`,
  `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_RECIPIENT_NUMBER` (see below).
- **Storage:** intentionally stateless — uploaded media live only for the
  duration of the request; nothing from Module 2 is written to Module 1's
  Google Sheet or Drive archive.
- **Supported media (2026-07-15):** JPG/PNG photos and MP4/3GP videos only,
  in any mixed order — this matches WhatsApp Cloud API's own supported
  format list exactly (Meta only accepts `image/jpeg`, `image/png`,
  `video/mp4`, `video/3gpp` for outbound messages). WEBP, HEIC/HEIF, MOV
  and M4V are rejected at `validate_publish_request` with a clear
  "convert to X" message rather than failing silently at delivery.
  `backend/services/whatsapp_service.py` uploads every file directly to
  WhatsApp's own Media API (no third-party CDN) and sends one message per
  file in original order, caption on the first only; failures use
  exponential backoff (1s/2s/4s) for transient/5xx errors and fail fast
  on 4xx.

### WhatsApp migration reference (2026-07-15)

A separate, older internal project's repo was reviewed as a migration
reference for Module 2's WhatsApp layer. What was reused vs. not, and why:

- **Reused:** the Bearer-token + `phone_number_id` auth pattern and a
  `config.whatsapp` block with an `apiBaseUrl`-style getter (mirrored in
  `backend/config.py`'s `Settings` properties); structured
  info/warning/error logging that never logs the access token.
- **Not reused — Cloudinary-hosted outbound links:** that project uploaded
  every outbound image to Cloudinary first and sent WhatsApp a public
  `link`, rather than uploading to WhatsApp's own Media API. Adopting that
  would mean a brand-new external dependency + secrets just to get a
  public URL, when uploading bytes directly to Meta's Media API already
  works, is self-contained, and needs nothing else running. Decision:
  keep direct Media API uploads as Module 2's only path; Cloudinary (if
  ever configured) stays scoped to Module 1's own inventory storage, not
  Module 2's send flow.
  **Why:** explicit product decision — avoid a third-party CDN as a
  prerequisite for sending a WhatsApp message; keep the send flow
  self-contained.
- **Not reused — video sending, retries:** that project's WhatsApp service
  had no outbound video support and no retry logic of any kind (single
  attempt, log-and-return-null on failure) — there was nothing to migrate
  for either. Both were built fresh for Module 2 instead (video support
  above; exponential-backoff retries in `whatsapp_service._with_retries`).

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
