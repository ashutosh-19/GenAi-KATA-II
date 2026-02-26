from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import database as db
from app.main import app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    db.DB_PATH = tmp_path / "test.db"
    db.init_db()
    with TestClient(app) as test_client:
        yield test_client


def test_manual_mapping_create_duplicate_update_delete_and_effective_result(client: TestClient) -> None:
    action_item = {
        "id": "US-101",
        "title": "Login page enhancement",
        "description": "Improve login UX",
        "acceptance_criteria": ["User can login successfully"],
        "type": "Feature",
    }
    create_item = client.post("/action-items", json=action_item)
    assert create_item.status_code == 200

    transcript = "\n".join(
        [
            "Improve login page with clearer error message",
            "Dashboard crashes intermittently on export",
        ]
    )
    analyze = client.post("/analyze", json={"transcript": transcript, "use_mock": True})
    assert analyze.status_code == 200
    run = analyze.json()
    run_id = run["analysis_run_id"]
    assert run_id is not None
    assert any(i["text"] == "Dashboard crashes intermittently on export" for i in run["unmapped_feedback"])

    create_mapping = client.post(
        "/mappings/manual",
        json={
            "analysis_run_id": run_id,
            "feedback_text": "Dashboard crashes intermittently on export",
            "action_item_id": "US-101",
            "feedback_type": "Bug",
        },
    )
    assert create_mapping.status_code == 200
    mapping = create_mapping.json()
    mapping_id = mapping["id"]

    duplicate_mapping = client.post(
        "/mappings/manual",
        json={
            "analysis_run_id": run_id,
            "feedback_text": "Dashboard crashes intermittently on export",
            "action_item_id": "US-101",
            "feedback_type": "Bug",
        },
    )
    assert duplicate_mapping.status_code == 409

    details_after_create = client.get(f"/analysis-runs/{run_id}")
    assert details_after_create.status_code == 200
    created_result = details_after_create.json()["result"]
    assert any(
        i["text"] == "Dashboard crashes intermittently on export"
        and i["mapped_action_item_id"] == "US-101"
        for i in created_result["mapped_feedback"]
    )
    assert not any(i["text"] == "Dashboard crashes intermittently on export" for i in created_result["unmapped_feedback"])

    update_mapping = client.put(
        f"/mappings/manual/{mapping_id}",
        json={
            "feedback_text": "Dashboard crashes intermittently on export",
            "action_item_id": "US-101",
            "feedback_type": "Task",
        },
    )
    assert update_mapping.status_code == 200
    assert update_mapping.json()["feedback_type"] == "Task"

    details_after_update = client.get(f"/analysis-runs/{run_id}")
    assert details_after_update.status_code == 200
    updated_result = details_after_update.json()["result"]
    assert any(
        i["text"] == "Dashboard crashes intermittently on export" and i["type"] == "Task"
        for i in updated_result["mapped_feedback"]
    )

    delete_mapping = client.delete(f"/mappings/manual/{mapping_id}")
    assert delete_mapping.status_code == 200

    details_after_delete = client.get(f"/analysis-runs/{run_id}")
    assert details_after_delete.status_code == 200
    deleted_result = details_after_delete.json()["result"]
    assert any(i["text"] == "Dashboard crashes intermittently on export" for i in deleted_result["unmapped_feedback"])


def test_analysis_history_uses_effective_result_counts(client: TestClient) -> None:
    action_item = {
        "id": "US-201",
        "title": "Checkout reliability",
        "description": "Fix payment reliability issues",
        "acceptance_criteria": ["Payment retry works"],
        "type": "Bug",
    }
    assert client.post("/action-items", json=action_item).status_code == 200

    transcript = "\n".join(
        [
            "Payment flow needs better error prompts",
            "Search panel crashes after filtering",
        ]
    )
    run_resp = client.post("/analyze", json={"transcript": transcript, "use_mock": True})
    assert run_resp.status_code == 200
    run_payload = run_resp.json()
    run_id = run_payload["analysis_run_id"]
    assert run_id is not None
    initial_unmapped = len(run_payload["unmapped_feedback"])

    assert (
        client.post(
            "/mappings/manual",
            json={
                "analysis_run_id": run_id,
                "feedback_text": "Search panel crashes after filtering",
                "action_item_id": "US-201",
                "feedback_type": "Bug",
            },
        ).status_code
        == 200
    )

    history_resp = client.get("/analysis-runs")
    assert history_resp.status_code == 200
    history = history_resp.json()
    run_summary = next(i for i in history if i["id"] == run_id)
    assert run_summary["mapped_count"] >= 1
    assert run_summary["unmapped_count"] == max(initial_unmapped - 1, 0)
