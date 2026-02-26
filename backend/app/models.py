"""Pydantic models used by API contracts and AI outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ActionType = Literal["Feature", "Bug", "Task"]


class ActionItem(BaseModel):
    id: str = Field(..., description="Stable action item identifier")
    title: str
    description: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    type: ActionType


class FeedbackItem(BaseModel):
    text: str
    type: ActionType
    mapped_action_item_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ActionSuggestion(BaseModel):
    action_item_id: str
    suggestion: str
    rationale: str


class AnalyzeRequest(BaseModel):
    transcript: str = Field(..., min_length=10)
    action_items: list[ActionItem] = Field(default_factory=list)
    use_mock: bool = True


class AnalyzeResponse(BaseModel):
    analysis_run_id: int | None = None
    mapped_feedback: list[FeedbackItem]
    unmapped_feedback: list[FeedbackItem]
    suggestions: list[ActionSuggestion]


class MomRequest(BaseModel):
    transcript: str = Field(..., min_length=10)
    action_items: list[ActionItem] = Field(default_factory=list)
    use_mock: bool = True


class MomResponse(BaseModel):
    minutes: str


class AnalysisRunSummary(BaseModel):
    id: int
    created_at: str
    transcript_preview: str
    mapped_count: int
    unmapped_count: int
    suggestion_count: int


class ManualMappingCreate(BaseModel):
    analysis_run_id: int
    feedback_text: str
    action_item_id: str
    feedback_type: ActionType


class ManualMappingUpdate(BaseModel):
    feedback_text: str
    action_item_id: str
    feedback_type: ActionType


class ManualMapping(BaseModel):
    id: int
    analysis_run_id: int
    feedback_text: str
    action_item_id: str
    feedback_type: ActionType
    created_at: str


class AnalysisRunDetail(BaseModel):
    id: int
    created_at: str
    transcript: str
    result: AnalyzeResponse
    manual_mappings: list[ManualMapping] = Field(default_factory=list)
