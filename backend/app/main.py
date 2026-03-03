"""FastAPI entrypoint for sprint feedback intelligence APIs."""

from __future__ import annotations


# NEW CHANGE


import copy
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import (
    delete_action_item,
    delete_manual_mapping,
    get_manual_mapping,
    get_analysis_run,
    init_db,
    list_action_items,
    list_analysis_runs,
    list_manual_mappings,
    set_effective_result,
    save_manual_mapping,
    update_manual_mapping,
    upsert_action_item,
)
from app.models import (
    ActionItem,
    AnalysisRunDetail,
    AnalysisRunSummary,
    AnalyzeRequest,
    AnalyzeResponse,
    ManualMapping,
    ManualMappingCreate,
    ManualMappingUpdate,
    MomRequest,
    MomResponse,
)
from app.services.analysis import AnalysisService

def apply_manual_mappings(base_result: AnalyzeResponse, manual: list[ManualMapping]) -> AnalyzeResponse:
    result = copy.deepcopy(base_result)
    for mapping in manual:
        target_index = next(
            (
                idx
                for idx, item in enumerate(result.unmapped_feedback)
                if item.text.strip().lower() == mapping.feedback_text.strip().lower()
            ),
            None,
        )
        if target_index is not None:
            moved = result.unmapped_feedback.pop(target_index)
            moved.mapped_action_item_id = mapping.action_item_id
            moved.type = mapping.feedback_type
            moved.confidence = 1.0
            result.mapped_feedback.append(moved)
    return result


def refresh_effective_result(run_id: int) -> AnalyzeResponse:
    run = get_analysis_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    manual = [ManualMapping(**m) for m in list_manual_mappings(run_id)]
    base_result = AnalyzeResponse(**run["result"])
    effective = apply_manual_mappings(base_result, manual)
    set_effective_result(run_id, effective.model_dump())
    return effective


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Sprint Review Feedback Intelligence API", version="0.2.0", lifespan=lifespan)
service = AnalysisService()
frontend_dir = Path(__file__).resolve().parents[2] / "frontend"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if frontend_dir.exists():
    app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")


@app.get("/")
def root() -> FileResponse:
    index = frontend_dir / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend not initialized")
    return FileResponse(index)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def config() -> dict[str, object]:
    endpoint = service.client.endpoint
    parsed = urlparse(endpoint) if endpoint else None
    endpoint_host = parsed.netloc if parsed else ""
    return {
        "dial_available": service.client.available,
        "dial_endpoint_host": endpoint_host,
        "has_dial_api_key": bool(service.client.api_key),
        "force_mock_from_env": service.force_mock,
        "analysis_retries": service.analysis_retries,
        "mom_retries": service.mom_retries,
        "fallback_to_mock_on_dial_error": service.fallback_to_mock_on_error,
    }


@app.get("/action-items", response_model=list[ActionItem])
def get_action_items() -> list[ActionItem]:
    return [ActionItem(**row) for row in list_action_items()]


@app.post("/action-items", response_model=ActionItem)
def save_action_item(item: ActionItem) -> ActionItem:
    upsert_action_item(item.model_dump())
    return item


@app.delete("/action-items/{item_id}")
def remove_action_item(item_id: str) -> dict[str, bool]:
    deleted = delete_action_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Action item not found")
    return {"deleted": True}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    return service.analyze(payload)


@app.post("/mom", response_model=MomResponse)
def generate_mom(payload: MomRequest) -> MomResponse:
    return service.generate_mom(payload)


@app.get("/analysis-runs", response_model=list[AnalysisRunSummary])
def get_analysis_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[AnalysisRunSummary]:
    return [AnalysisRunSummary(**row) for row in list_analysis_runs(limit)]


@app.get("/analysis-runs/{run_id}", response_model=AnalysisRunDetail)
def get_analysis_run_by_id(run_id: int) -> AnalysisRunDetail:
    run = get_analysis_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")

    manual = [ManualMapping(**m) for m in list_manual_mappings(run_id)]
    if run["effective_result"] is not None:
        result = AnalyzeResponse(**run["effective_result"])
    else:
        result = refresh_effective_result(run_id)

    return AnalysisRunDetail(
        id=run["id"],
        created_at=run["created_at"],
        transcript=run["transcript"],
        result=result,
        manual_mappings=manual,
    )


@app.get("/mappings/manual", response_model=list[ManualMapping])
def get_manual_mappings(run_id: int | None = None) -> list[ManualMapping]:
    return [ManualMapping(**row) for row in list_manual_mappings(run_id)]


@app.post("/mappings/manual", response_model=ManualMapping)
def create_manual_mapping(payload: ManualMappingCreate) -> ManualMapping:
    run = get_analysis_run(payload.analysis_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")

    action_exists = any(item["id"] == payload.action_item_id for item in list_action_items())
    if not action_exists:
        raise HTTPException(status_code=404, detail="Action item not found")

    try:
        saved = save_manual_mapping(payload.model_dump())
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Mapping already exists for this run and feedback text",
        ) from None
    refresh_effective_result(payload.analysis_run_id)
    return ManualMapping(**saved)


@app.put("/mappings/manual/{mapping_id}", response_model=ManualMapping)
def edit_manual_mapping(mapping_id: int, payload: ManualMappingUpdate) -> ManualMapping:
    existing = get_manual_mapping(mapping_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Manual mapping not found")

    action_exists = any(item["id"] == payload.action_item_id for item in list_action_items())
    if not action_exists:
        raise HTTPException(status_code=404, detail="Action item not found")

    try:
        updated = update_manual_mapping(mapping_id, payload.model_dump())
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Mapping already exists for this run and feedback text",
        ) from None
    if updated is None:
        raise HTTPException(status_code=404, detail="Manual mapping not found")
    refresh_effective_result(existing["analysis_run_id"])
    return ManualMapping(**updated)


@app.delete("/mappings/manual/{mapping_id}")
def remove_manual_mapping(mapping_id: int) -> dict[str, bool]:
    existing = get_manual_mapping(mapping_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Manual mapping not found")
    deleted = delete_manual_mapping(mapping_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Manual mapping not found")
    refresh_effective_result(existing["analysis_run_id"])
    return {"deleted": True}
