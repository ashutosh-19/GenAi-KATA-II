from __future__ import annotations

from app.models import ActionItem, AnalyzeRequest
from app.services import analysis as analysis_module


def _build_service(monkeypatch):
    service = analysis_module.AnalysisService()
    service.force_mock = False
    service.client.api_key = "x"
    service.client.endpoint = "https://example.test"
    monkeypatch.setattr(analysis_module, "save_analysis_run", lambda _t, _r: 1)
    return service


def test_analyze_retries_and_normalizes_invalid_dial_output(monkeypatch) -> None:
    service = _build_service(monkeypatch)
    service.analysis_retries = 1
    service.fallback_to_mock_on_error = False

    calls = {"count": 0}

    def fake_chat_json(_prompt: str):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("bad json")
        return {
            "mapped_feedback": [
                {
                    "text": "Crash on save",
                    "type": "Unknown",
                    "mapped_action_item_id": "BAD-ID",
                    "confidence": "2.1",
                }
            ],
            "unmapped_feedback": [
                {
                    "text": "Crash on save",
                    "type": "Task",
                    "mapped_action_item_id": "US-1",
                    "confidence": "x",
                },
                {"text": "Add dark mode", "type": "Feature", "confidence": 0.8},
            ],
            "suggestions": [
                {"action_item_id": "US-1", "suggestion": "Stabilize save flow", "rationale": ""},
                {"action_item_id": "BAD-ID", "suggestion": "Ignore", "rationale": "x"},
            ],
        }

    monkeypatch.setattr(service.client, "chat_json", fake_chat_json)

    payload = AnalyzeRequest(
        transcript="Crash on save\nAdd dark mode",
        use_mock=False,
        action_items=[
            ActionItem(
                id="US-1",
                title="Save workflow",
                description="Stabilize save behavior",
                acceptance_criteria=["No crashes on save"],
                type="Bug",
            )
        ],
    )
    result = service.analyze(payload)

    assert calls["count"] == 2
    assert result.analysis_run_id == 1
    assert len(result.mapped_feedback) == 0
    assert len(result.unmapped_feedback) == 2
    assert any(i.text == "Crash on save" and i.type == "Bug" and i.confidence == 1.0 for i in result.unmapped_feedback)
    assert any(i.text == "Add dark mode" and i.type == "Feature" for i in result.unmapped_feedback)
    assert len(result.suggestions) == 1
    assert result.suggestions[0].action_item_id == "US-1"
    assert result.suggestions[0].rationale == "Generated from transcript feedback."


def test_analyze_falls_back_to_mock_when_dial_fails(monkeypatch) -> None:
    service = _build_service(monkeypatch)
    service.analysis_retries = 1
    service.fallback_to_mock_on_error = True

    def always_fail(_prompt: str):
        raise ValueError("still invalid")

    monkeypatch.setattr(service.client, "chat_json", always_fail)

    payload = AnalyzeRequest(
        transcript="Login feature needs improvement",
        use_mock=False,
        action_items=[
            ActionItem(
                id="US-2",
                title="Login feature",
                description="Improve experience",
                acceptance_criteria=["User sees clear message on error"],
                type="Feature",
            )
        ],
    )
    result = service.analyze(payload)

    assert result.analysis_run_id == 1
    assert len(result.mapped_feedback) == 1
    assert result.mapped_feedback[0].mapped_action_item_id == "US-2"
