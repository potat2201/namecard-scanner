# Namecard Scanner

Scan business cards, extract contact fields (name, company, title, phone, email, etc.), store them in SQLite, and browse them in a web table.

## Stack

- **Backend**: Python, FastAPI, SQLAlchemy, SQLite
- **OCR**: Ollama vision on your LAN, OpenAI Vision, or Tesseract (fallback)
- **Frontend**: React + Vite

## Prerequisites

- Python 3.11+
- Node.js 18+
- **Ollama with a vision model** (recommended if you have a home-server GPU), **or**
- **Tesseract** (fully offline on this Mac):

  ```bash
  brew install tesseract tesseract-lang
  ```

## Ollama setup (LAN)

On your Ollama machine (`192.168.1.25` or similar), pull a **vision** model:

```bash
ollama pull llava
# or: ollama pull llama3.2-vision
```

Allow connections from your Mac. On the Ollama host, set:

```bash
export OLLAMA_HOST=0.0.0.0:11434
```

Then restart Ollama so other devices on the LAN can reach it.

Copy and edit `.env` in the project root:

```bash
cp .env.example .env
```

```env
OLLAMA_BASE_URL=http://192.168.1.25:11434
OLLAMA_MODEL=llava
```

Verify from your Mac:

```bash
curl http://192.168.1.25:11434/api/tags
curl http://localhost:8000/api/ocr-status
```

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env` (Ollama settings are pre-filled in `.env.example`):

```bash
cp ../.env.example ../.env
```

Run API (from `backend/`):

```bash
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**

## Access from iPhone / other devices (home LAN)

1. Find your Mac's IP (e.g. `192.168.1.89`):

   ```bash
   ipconfig getifaddr en0
   ```

2. Start in LAN mode (listens on all interfaces):

   ```bash
   chmod +x scripts/dev-lan.sh
   ./scripts/dev-lan.sh
   ```

   Or manually in two terminals:

   ```bash
   # Terminal 1 — backend
   cd backend && source .venv/bin/activate
   LAN_EXPOSE=true uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

   # Terminal 2 — frontend
   cd frontend && npm run dev:lan
   ```

3. On your iPhone (same Wi‑Fi), open **http://192.168.1.89:5173** (use your Mac's IP).

4. If it does not connect, allow **Node** and **Python** in **System Settings → Network → Firewall** on the Mac.

Set `LAN_EXPOSE=true` in `.env` and add your Mac IP to `CORS_ORIGINS` if you use the split-terminal setup above.

## Notion sync

Contacts sync **two-way** with a Notion database. Local scans, edits, and deletes push to Notion; changes made in Notion are pulled every few minutes (or on demand).

1. Create an integration at [notion.so/my-integrations](https://www.notion.so/my-integrations).
2. Create a parent page in Notion and **share it with your integration**.
3. Copy the page ID from the page URL (`https://www.notion.so/.../<page_id>`).
4. Add to `.env`:

   ```env
   NOTION_TOKEN=secret_...
   NOTION_PARENT_PAGE_ID=your_page_id
   NOTION_SYNC_ENABLED=true
   NOTION_SYNC_POLL_SECONDS=300
   ```

5. Restart the backend. On first run, a **Namecard Contacts** database is created under your parent page. Copy the logged `NOTION_DATABASE_ID` into `.env` to skip re-lookup on future starts.

**Conflict resolution:** last-write-wins using `updated_at` (local) vs Notion `last_edited_time`.

**Manual sync:**

```bash
curl http://localhost:8000/api/notion-status
curl -X POST "http://localhost:8000/api/sync/notion?direction=both"
```

Name card **images** sync to Google Drive when configured; **text fields** sync to Notion.

## Google Drive photo backup

Every uploaded name card photo is copied to Google Drive **after OCR**. Photos are placed in a **domain subfolder** under your `namecard` folder (e.g. `acme.com/`) and named **`email@domain.com.jpg`**. If Drive upload fails (when configured), the scan is aborted.

### Personal Gmail (recommended)

Service accounts **cannot** upload to personal My Drive folders (Google storage quota restriction). Use OAuth instead:

1. In [Google Cloud Console](https://console.cloud.google.com/), enable the **Google Drive API**.
2. Configure the **OAuth consent screen**:
   - User type: **External**
   - Publishing status: **Testing** (stay in Testing — do not publish to Production)
   - **Test users** → add your Gmail (e.g. `potat2201@gmail.com`)
   - Scopes → add `.../auth/drive.file` only (not full `drive` — that requires Google verification)
3. **Credentials → Create OAuth client ID → Desktop app** — download JSON as `backend/google-oauth-client.json`.
4. Create a folder named **`namecard`** in your Google Drive (no sharing needed).
5. Add to `.env`:

   ```env
   GOOGLE_DRIVE_OAUTH_CLIENT_PATH=backend/google-oauth-client.json
   GOOGLE_DRIVE_FOLDER_NAME=namecard
   GOOGLE_DRIVE_FOLDER_ID=your_folder_id_from_drive_url
   ```

6. Authorize once:

   ```bash
   cd backend && source .venv/bin/activate
   pip install -r requirements.txt
   python scripts/google_drive_auth.py
   ```

7. Restart the backend and upload a test name card.

### Google Workspace (service account)

Service accounts can upload to **Shared drives** only. For My Drive folders, use OAuth above.

Leave all `GOOGLE_DRIVE_*` auth paths unset to skip Drive uploads (local-only mode).

The Drive API is free for normal personal use; uploaded photos count against your Google Drive storage quota.

### Port 5173 already in use?

Another Vite app (or a stuck dev server) may be holding the port:

```bash
kill $(lsof -t -iTCP:5173 -sTCP:LISTEN)
```

Or set a different port in `.env`: `PORT=5174` (and add that origin to `CORS_ORIGINS` if calling the API directly).

## Usage

1. Drag & drop or click to upload a name card photo.
2. OCR runs, the photo is uploaded to Google Drive under **`namecard/<domain>/email@domain.com.jpg`** (domain from email, or website if no email), then saved to SQLite and synced to Notion. Cards without a domain go to **`Unknown Domain/`**.
3. View, search, edit, or delete contacts in the table.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/notion-status` | Notion sync configuration and last sync time |
| POST | `/api/sync/notion?direction=both\|push\|pull` | Run Notion sync manually |
| GET | `/api/ocr-status` | Check Ollama / Tesseract availability |
| GET | `/api/contacts` | List contacts (`?q=search`) |
| POST | `/api/scan` | Upload image, extract & save |
| PATCH | `/api/contacts/{id}` | Update fields |
| DELETE | `/api/contacts/{id}` | Remove contact |

## Data

- Database: `backend/data/namecards.db`
- Uploaded images: `backend/data/uploads/`

## Tips

- **Accuracy**: Ollama vision (`OLLAMA_*`) is tried first, then OpenAI, then Tesseract.
- **Model name**: `OLLAMA_MODEL` must match a vision model on that host (`ollama list`).
- **Corrections**: Use **Edit** on any row after scanning — OCR is rarely perfect.
- **Export**: Query SQLite directly or add CSV export later.

## Project layout

```
namecard-scanner/
├── backend/
│   ├── app/
│   │   ├── main.py      # API routes
│   │   ├── google_drive.py  # Drive photo backup on upload
│   │   ├── notion_sync.py  # Notion two-way sync
│   │   ├── ocr.py       # Ollama / OpenAI / Tesseract
│   │   ├── parser.py    # Field extraction from text
│   │   └── models.py    # Contact table
│   └── requirements.txt
└── frontend/            # Web GUI
```
