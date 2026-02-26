"""Core analysis workflow with mock fallback and DIAL-backed generation."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any

from app.database import list_action_items, save_analysis_run
from app.dial_client import DialClient
from app.models import (
    ActionItem,
    ActionSuggestion,
    AnalyzeRequest,
    AnalyzeResponse,
    FeedbackItem,
    MomRequest,
    MomResponse,
)


class AnalysisService:
    def __init__(self) -> None:
        self.client = DialClient()
        self.force_mock = os.getenv("USE_MOCK_ANALYSIS", "true").lower() == "true"
        self.analysis_retries = max(0, int(os.getenv("DIAL_ANALYSIS_RETRIES", "2")))
        self.mom_retries = max(0, int(os.getenv("DIAL_MOM_RETRIES", "1")))
        self.fallback_to_mock_on_error = os.getenv("FALLBACK_TO_MOCK_ON_DIAL_ERROR", "true").lower() == "true"

    def analyze(self, payload: AnalyzeRequest) -> AnalyzeResponse:
        action_items = payload.action_items or [ActionItem(**row) for row in list_action_items()]
        use_mock = payload.use_mock or self.force_mock or not self.client.available
        request = AnalyzeRequest(transcript=payload.transcript, action_items=action_items, use_mock=use_mock)

        if use_mock:
            result = self._mock_analyze(request)
        else:
            result = self._dial_analyze_with_guardrails(request)

        run_id = save_analysis_run(payload.transcript, result.model_dump())
        result.analysis_run_id = run_id
        return result

    def generate_mom(self, payload: MomRequest) -> MomResponse:
        action_items = payload.action_items or [ActionItem(**row) for row in list_action_items()]
        use_mock = payload.use_mock or self.force_mock or not self.client.available
        request = MomRequest(transcript=payload.transcript, action_items=action_items, use_mock=use_mock)

        if use_mock:
            return MomResponse(minutes=self._mock_mom(request.transcript, request.action_items))

        errors: list[str] = []
        for attempt in range(self.mom_retries + 1):
            try:
                prompt = self._build_mom_prompt(request.action_items, request.transcript)
                if attempt > 0:
                    prompt += (
                        "\n\nRetry instruction: previous response format was not acceptable."
                        " Return plain text MOM with the requested sections."
                    )
                minutes = self.client.chat_text(prompt).strip()
                if minutes:
                    return MomResponse(minutes=minutes)
                raise ValueError("Empty MOM output")
            except Exception as exc:
                errors.append(str(exc))

        if self.fallback_to_mock_on_error:
            return MomResponse(minutes=self._mock_mom(request.transcript, request.action_items))
        raise RuntimeError(f"MOM generation failed after retries: {' | '.join(errors)}")

    def _dial_analyze_with_guardrails(self, payload: AnalyzeRequest) -> AnalyzeResponse:
        errors: list[str] = []
        for attempt in range(self.analysis_retries + 1):
            try:
                prompt = self._build_analysis_prompt(payload.action_items, payload.transcript)
                if attempt > 0:
                    prompt += (
                        "\n\nRetry instruction: previous output was invalid."
                        " Return only JSON that matches the exact schema and uses only provided action_item_id values."
                    )
                raw = self.client.chat_json(prompt)
                return self._normalize_analysis_output(raw, payload.action_items)
            except Exception as exc:
                errors.append(str(exc))

        if self.fallback_to_mock_on_error:
            return self._mock_analyze(payload)
        raise RuntimeError(f"Analysis failed after retries: {' | '.join(errors)}")

    def _mock_analyze(self, payload: AnalyzeRequest) -> AnalyzeResponse:
        lines = [line.strip(" -\t") for line in payload.transcript.splitlines() if line.strip()]
        mapped: list[FeedbackItem] = []
        unmapped: list[FeedbackItem] = []
        grouped: dict[str, list[str]] = defaultdict(list)

        for line in lines:
            classification = self._classify_feedback_type(line)
            matched = self._match_action_item(line, payload.action_items)

            if matched is None:
                unmapped.append(
                    FeedbackItem(
                        text=line,
                        type=classification,
                        mapped_action_item_id=None,
                        confidence=0.45,
                    )
                )
            else:
                mapped.append(
                    FeedbackItem(
                        text=line,
                        type=classification,
                        mapped_action_item_id=matched.id,
                        confidence=0.75,
                    )
                )
                grouped[matched.id].append(line)

        suggestions = [
            ActionSuggestion(
                action_item_id=item.id,
                suggestion=(
                    "Refine acceptance criteria with measurable validation, then create implementation "
                    "subtasks for each feedback theme."
                ),
                rationale=f"Generated from {len(grouped[item.id])} mapped transcript feedback items.",
            )
            for item in payload.action_items
            if grouped[item.id]
        ]

        return AnalyzeResponse(mapped_feedback=mapped, unmapped_feedback=unmapped, suggestions=suggestions)

    def _mock_mom(self, transcript: str, action_items: list[ActionItem]) -> str:
        top_lines = [line.strip() for line in transcript.splitlines() if line.strip()][:8]
        items = "\n".join([f"- [{i.type}] {i.title} ({i.id})" for i in action_items])
        discussion = "\n".join([f"- {line}" for line in top_lines])
        return (
            "Minutes of Meeting\n\n"
            "Reviewed Action Items:\n"
            f"{items}\n\n"
            "Discussion Highlights:\n"
            f"{discussion}\n\n"
            "Next Steps:\n"
            "- Confirm mapping of unmapped feedback\n"
            "- Prioritize high-impact bug and feature suggestions\n"
            "- Finalize sprint follow-up owners"
        )

    @staticmethod
    def _normalize_analysis_output(raw: dict[str, Any], action_items: list[ActionItem]) -> AnalyzeResponse:
        valid_types = {"Feature", "Bug", "Task"}
        valid_action_ids = {item.id for item in action_items}

        mapped_feedback: list[FeedbackItem] = []
        unmapped_feedback: list[FeedbackItem] = []
        suggestions: list[ActionSuggestion] = []

        def parse_type(value: Any, text: str) -> str:
            candidate = str(value).strip() if value is not None else ""
            if candidate in valid_types:
                return candidate
            return AnalysisService._classify_feedback_type(text)

        def parse_confidence(value: Any, default: float) -> float:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                parsed = default
            return max(0.0, min(1.0, parsed))

        for entry in raw.get("mapped_feedback", []) if isinstance(raw.get("mapped_feedback", []), list) else []:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            feedback_type = parse_type(entry.get("type"), text)
            mapped_id = entry.get("mapped_action_item_id")
            mapped_id = str(mapped_id).strip() if mapped_id is not None else None
            confidence = parse_confidence(entry.get("confidence"), 0.7)
            if mapped_id not in valid_action_ids:
                mapped_id = None

            item = FeedbackItem(
                text=text,
                type=feedback_type,  # type: ignore[arg-type]
                mapped_action_item_id=mapped_id,
                confidence=confidence,
            )
            if mapped_id is None:
                unmapped_feedback.append(item)
            else:
                mapped_feedback.append(item)

        for entry in raw.get("unmapped_feedback", []) if isinstance(raw.get("unmapped_feedback", []), list) else []:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            feedback_type = parse_type(entry.get("type"), text)
            confidence = parse_confidence(entry.get("confidence"), 0.5)
            unmapped_feedback.append(
                FeedbackItem(
                    text=text,
                    type=feedback_type,  # type: ignore[arg-type]
                    mapped_action_item_id=None,
                    confidence=confidence,
                )
            )

        mapped_keys = {(item.text.lower(), item.mapped_action_item_id or "") for item in mapped_feedback}
        dedup_unmapped: list[FeedbackItem] = []
        seen_unmapped: set[str] = set()
        for item in unmapped_feedback:
            text_key = item.text.lower()
            if (text_key, "") in mapped_keys:
                continue
            if text_key in seen_unmapped:
                continue
            seen_unmapped.add(text_key)
            dedup_unmapped.append(item)
        unmapped_feedback = dedup_unmapped

        for entry in raw.get("suggestions", []) if isinstance(raw.get("suggestions", []), list) else []:
            if not isinstance(entry, dict):
                continue
            action_item_id = str(entry.get("action_item_id", "")).strip()
            suggestion = str(entry.get("suggestion", "")).strip()
            rationale = str(entry.get("rationale", "")).strip()
            if action_item_id not in valid_action_ids or not suggestion:
                continue
            suggestions.append(
                ActionSuggestion(
                    action_item_id=action_item_id,
                    suggestion=suggestion,
                    rationale=rationale or "Generated from transcript feedback.",
                )
            )

        return AnalyzeResponse(
            mapped_feedback=mapped_feedback,
            unmapped_feedback=unmapped_feedback,
            suggestions=suggestions,
        )

    @staticmethod
    def _classify_feedback_type(text: str) -> str:
        t = text.lower()
        if any(word in t for word in ["bug", "error", "crash", "failure", "issue"]):
            return "Bug"
        if any(word in t for word in ["add", "new", "enhancement", "improve", "feature"]):
            return "Feature"
        return "Task"

    @staticmethod
    def _match_action_item(text: str, action_items: list[ActionItem]) -> ActionItem | None:
        normalized = set(text.lower().replace(":", " ").replace(",", " ").split())
        best_item: ActionItem | None = None
        best_score = 0

        for item in action_items:
            candidate_words = set((item.title + " " + item.description).lower().split())
            score = len(normalized.intersection(candidate_words))
            if score > best_score:
                best_item = item
                best_score = score

        return best_item if best_score > 1 else None

    @staticmethod
    def _build_analysis_prompt(action_items: list[ActionItem], transcript: str) -> str:
        action_items_json = json.dumps([item.model_dump() for item in action_items], indent=2)
        return f"""
You are analyzing sprint review feedback.
Map transcript feedback to action items. Classify each feedback as Feature/Bug/Task.
Also return unmapped feedback and action-item-level suggestions.
Use only these exact types: Feature, Bug, Task.
Use only action_item_id values from the provided action items.

Return strict JSON in this shape:
{{
  "mapped_feedback": [
    {{"text":"...","type":"Feature|Bug|Task","mapped_action_item_id":"...","confidence":0.0}}
  ],
  "unmapped_feedback": [
    {{"text":"...","type":"Feature|Bug|Task","mapped_action_item_id":null,"confidence":0.0}}
  ],
  "suggestions": [
    {{"action_item_id":"...","suggestion":"...","rationale":"..."}}
  ]
}}

Action items:
{action_items_json}

Transcript:
{transcript}
""".strip()

    @staticmethod
    def _build_mom_prompt(action_items: list[ActionItem], transcript: str) -> str:
        action_items_json = json.dumps([item.model_dump() for item in action_items], indent=2)
        return f"""
Generate concise Minutes of Meeting for a sprint review.
Include sections: Participants (if inferable), Reviewed Items, Key Feedback, Decisions, Action Items, Risks, Next Steps.

Action items context:
{action_items_json}

Transcript:
{transcript}
""".strip()
