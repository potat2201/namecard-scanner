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

## Usage

1. Drag & drop or click to upload a name card photo.
2. The app OCRs the image, parses fields, and saves a row to the database.
3. View, search, edit, or delete contacts in the table.

## API

| Method | Path | Description |
|--------|------|-------------|
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
│   │   ├── ocr.py       # Ollama / OpenAI / Tesseract
│   │   ├── parser.py    # Field extraction from text
│   │   └── models.py    # Contact table
│   └── requirements.txt
└── frontend/            # Web GUI
```
