"""Pydantic data models for the triage agent pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Incident(BaseModel):
    """An incoming incident to triage."""

    id: str
    title: str
    description: str
    source: str = Field(description="monitoring | user_report | automated_alert")
    timestamp: str
    expected_severity: str | None = Field(
        default=None, description="Golden-set ground truth for validation"
    )
    expected_category: str | None = Field(
        default=None, description="Golden-set ground truth for validation"
    )


class Classification(BaseModel):
    """Step 1 output: severity + category classification."""

    severity: str = Field(description="critical | high | medium | low")
    category: str = Field(
        description="container | storage | gateway | network | monitoring | process"
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_response: str = ""


class ToolResult(BaseModel):
    """Output from a mock investigation tool."""

    tool_name: str
    query: str
    result: str
    latency_ms: float


class Recommendation(BaseModel):
    """Step 3 output: actionable recommendation."""

    action: str
    reasoning: str
    escalation_needed: bool = False
    raw_response: str = ""


class IncidentReport(BaseModel):
    """Complete triage report for one incident."""

    incident_id: str
    classification: Classification | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    recommendation: Recommendation | None = None
    summary: str = ""
    step_latencies: dict[str, float] = Field(
        default_factory=dict, description="step_name → seconds"
    )
    total_latency: float = 0.0
    success: bool = False
    error: str | None = None
