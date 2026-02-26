# AI-Powered Sprint Review Feedback Intelligence System

Current implementation:
- Backend: FastAPI + SQLite (`backend/app/data.db`)
- AI integration: EPAM DIAL wrapper with mock fallback
- Frontend MVP: single-page UI served by FastAPI

## Quick start
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/`

## Environment
Create `backend/.env` from `backend/.env.example`.

Key settings:
- `DIAL_API_KEY`
- `DIAL_ENDPOINT`
- `USE_MOCK_ANALYSIS=true` for local flow without DIAL
- `DIAL_ANALYSIS_RETRIES=2` retry count for `/analyze` DIAL JSON failures
- `DIAL_MOM_RETRIES=1` retry count for `/mom` failures
- `FALLBACK_TO_MOCK_ON_DIAL_ERROR=true` fallback to mock output after retries

## Implemented APIs
- `GET /health`
- `GET /config`
- `GET /action-items`
- `POST /action-items`
- `DELETE /action-items/{item_id}`
- `POST /analyze`
- `POST /mom`
- `GET /analysis-runs`
- `GET /analysis-runs/{run_id}`
- `GET /mappings/manual?run_id=...`
- `POST /mappings/manual`
- `PUT /mappings/manual/{mapping_id}`
- `DELETE /mappings/manual/{mapping_id}`

Notes:
- Manual mapping duplicates are prevented per run for the same feedback text.
- Effective analysis results are persisted and refreshed after mapping create/update/delete.
