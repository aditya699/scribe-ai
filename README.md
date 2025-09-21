# scribe-ai

Real-time AI medical scribe and follow‑up assistant. This FastAPI service powers live voice transcription during consultations, stores audio securely, and sends WhatsApp notifications with summaries. Patients can later message questions that are handled via a RAG pipeline.

## Features
- Real‑time transcription over WebSocket with chunked audio streaming
- Async processing: store → transcribe → aggregate transcript
- MongoDB for sessions, transcription, chunks, notifications, and error logs
- Azure Blob Storage for audio chunk storage
- Twilio WhatsApp notifications with delivery status webhooks
- RAG webhook to process incoming patient messages for follow‑ups
- Health checks per module and global root/health endpoints

## Tech Stack
- FastAPI, Uvicorn
- MongoDB (async PyMongo)
- Azure Blob Storage (aio SDK)
- OpenAI (Async client) for transcription via `gpt-4o-mini-transcribe`
- Twilio WhatsApp API
- Pydantic v2, pydantic‑settings

## Prerequisites
- Python 3.13+
- MongoDB instance (connection URI)
- Azure Storage account (connection string)
- OpenAI API key
- Twilio account with a WhatsApp‑enabled number
- Public HTTPS URL for webhooks (e.g., ngrok)

## Installation
```bash
# From project root
python -m venv .venv
. .venv/Scripts/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -U pip
pip install -e .[dev]
```

## Environment Variables
Create a `.env` in the project root (same folder as `main.py`):
```
MONGO_URI=mongodb+srv://<user>:<pass>@<cluster>/scribe-ai?retryWrites=true&w=majority
OPENAI_API_KEY=sk-...
BLOB_STORAGE_ACCOUNT_KEY=DefaultEndpointsProtocol=...;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_WHATSAPP_FROM=whatsapp:+1415XXXXXXX
WEBHOOK_BASE_URL=https://<your-public-host>  # e.g., your ngrok base URL
```
Notes:
- `WEBHOOK_BASE_URL` is used by notification services for callbacks.
- `TWILIO_WHATSAPP_FROM` can be provided with or without `whatsapp:` prefix (it will be normalized).

## Running the Server
```bash
# Development (auto‑reload)
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```
The API will be available at `http://localhost:8001`. Docs: `http://localhost:8001/docs`

## Exposing Webhooks (ngrok)
Twilio requires a public HTTPS URL.
```bash
ngrok http http://localhost:8001
```
Update `.env` `WEBHOOK_BASE_URL` with the printed https URL.

### Configure Twilio Webhooks
- Status callback for WhatsApp messages → `POST {WEBHOOK_BASE_URL}/v1/notifications/twilio/whatsapp/status`
- Incoming WhatsApp messages (if using WhatsApp for RAG) → `POST {WEBHOOK_BASE_URL}/v1/rag/whatsapp/incoming`
Set these in your Twilio Console for the WhatsApp sender.

## API Reference (high‑level)

### Root
- `GET /` → `{ "message": "Medical RAG Assistant API is running" }`
- `GET /health` → `{ "status": "healthy" }`

### Sessions (`/v1/sessions`)
- `POST /create`
  - Body:
    ```json
    {
      "doctor_id": "string",
      "patient_whatsapp_number": "+91XXXXXXXXXX",
      "patient_name": "string",
      "request_id": "optional-idempotency-key"
    }
    ```
  - 201 Created → `SessionCreateResponse` and `Location: /v1/sessions/{session_id}`
- `GET /{session_id}` → `SessionResponse`
- `GET /` → health `{ "status": "healthy", "module": "sessions" }`

### Transcription (`/v1/transcription`)
- `POST /start`
  - Body: `{ "session_id": "..." }`
  - 201 → `{ success, message, transcription_session_id }` and `Location`
- `POST /end`
  - Body: `{ "transcription_session_id": "..." }`
  - 200 → `{ success, message }` and triggers patient WhatsApp notification
- `WEBSOCKET /{transcription_session_id}/stream`
  - Client flow:
    1) Connect WS → receive `connection_confirmed` with `max_chunk_size_bytes=1048576` and `expected_chunk_duration_seconds=8`
    2) Send JSON metadata before each binary chunk:
       ```json
       {"type":"audio_chunk_metadata","sequence_number":0,"chunk_size_bytes":12345,"duration_seconds":9.1}
       ```
    3) Send binary audio bytes (WebM/Opus), size must match metadata and be ≤ 1 MB
    4) Receive `transcript_update` messages per chunk with `partial_transcript`, `full_transcript`, and `processing_time_ms`
  - Errors are sent as `{ "type":"error", "error_code": "...", "error_message": "..." }`
- `GET /health` → connectivity checks for MongoDB, Blob, OpenAI

### Notifications (`/v1/notifications`)
- `POST /twilio/whatsapp/status` (Twilio callback)
  - Twilio posts `MessageSid`, `MessageStatus`, optional `ErrorCode`, `ErrorMessage`
  - Updates DB status: queued → sent → delivered → read or → failed/undelivered
- `GET /health` → DB and Twilio config checks

### RAG (`/v1/rag`)
- `POST /whatsapp/incoming` (Twilio inbound webhook)
  - Form fields: `From`, `Body`, `MessageSid`
  - Stores message, links to patient, kicks off RAG pipeline, returns `{ "status": "received" }`

## Data Storage
- MongoDB collections: `sessions`, `transcription_sessions`, `audio_chunks`, `whatsapp_notifications`, `error_logs`
- Azure Blob containers: `audio-chunks` (paths like `audio-chunks/{transcription_session_id}/000000_<uuid>.webm`)

## Development
- Code style: Black (88), Ruff rules `E,F,I`
- Install dev tools: `pip install -e .[dev]`
- Run with autoreload: `uvicorn main:app --reload`

## Security & Notes
- Do not commit `.env` or secrets
- Limit WS chunk size to 1 MB; send metadata before bytes
- Service logs errors to `error_logs` collection

## License
MIT
