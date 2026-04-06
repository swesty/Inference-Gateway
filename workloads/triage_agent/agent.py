"""Four-step triage agent: classify → investigate → recommend → summarize."""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass

import asyncio

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from triage_agent.llm import STEP_TECHNIQUES, make_llm
from triage_agent.models import (
    Classification,
    Incident,
    IncidentReport,
    Recommendation,
)
from triage_agent.retry import with_retry
from triage_agent.tools import log_search, runbook_fetch, system_metrics

log = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    gateway_url: str = "http://localhost:8080"
    model: str = "nemotron"
    technique_override: str | None = None  # force all steps to one technique
    max_retries: int = 3


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an SRE triage system for a Linux dev workstation called 'gesserit'. "
     "Classify the incident into exactly one severity and one category.\n\n"
     "Severities: critical, high, medium, low\n"
     "Categories: container, storage, gateway, network, monitoring, process\n\n"
     "Respond in EXACTLY this format (three lines, nothing else):\n"
     "SEVERITY: <severity>\n"
     "CATEGORY: <category>\n"
     "CONFIDENCE: <0.0-1.0>\n\n"
     "Example:\n"
     "SEVERITY: high\n"
     "CATEGORY: network\n"
     "CONFIDENCE: 0.85"),
    ("user", "Incident: {title}\n\nDetails: {description}"),
])

_RECOMMEND_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an SRE for 'gesserit', a dev workstation. Given the incident, "
     "classification, and investigation data, provide a remediation plan.\n\n"
     "Respond in EXACTLY this format:\n"
     "ACTION: <one-line immediate action to take>\n"
     "REASONING: <2-3 sentences explaining why>\n"
     "ESCALATE: <YES or NO>"),
    ("user",
     "Incident: {title}\n"
     "Severity: {severity} | Category: {category}\n\n"
     "--- Investigation Logs ---\n{logs}\n\n"
     "--- System Metrics ---\n{metrics}\n\n"
     "--- Runbook ---\n{runbook}\n\n"
     "What should we do?"),
])

_SUMMARIZE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Write a one-paragraph executive summary of this incident triage. "
     "Include: what happened, severity, root cause hypothesis, and recommended action. "
     "Keep it under 100 words."),
    ("user",
     "Incident: {title}\n"
     "Classification: {severity} / {category}\n"
     "Recommendation: {action}\n"
     "Reasoning: {reasoning}"),
])


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_classification(raw: str) -> Classification:
    """Parse structured classification from LLM output, with graceful fallback."""
    severity = "medium"
    category = "process"
    confidence = 0.0

    sev_match = re.search(r"SEVERITY:\s*(\w+)", raw, re.IGNORECASE)
    if sev_match:
        severity = sev_match.group(1).lower()

    cat_match = re.search(r"CATEGORY:\s*(\w+)", raw, re.IGNORECASE)
    if cat_match:
        category = cat_match.group(1).lower()

    conf_match = re.search(r"CONFIDENCE:\s*([\d.]+)", raw, re.IGNORECASE)
    if conf_match:
        try:
            confidence = min(1.0, max(0.0, float(conf_match.group(1))))
        except ValueError:
            pass

    return Classification(
        severity=severity,
        category=category,
        confidence=confidence,
        raw_response=raw,
    )


def _parse_recommendation(raw: str) -> Recommendation:
    """Parse structured recommendation from LLM output, with graceful fallback."""
    action = raw.strip()
    reasoning = ""
    escalate = False

    act_match = re.search(r"ACTION:\s*(.+?)(?:\n|$)", raw, re.IGNORECASE)
    if act_match:
        action = act_match.group(1).strip()

    reason_match = re.search(r"REASONING:\s*(.+?)(?:\nESCALATE|\Z)", raw, re.IGNORECASE | re.DOTALL)
    if reason_match:
        reasoning = reason_match.group(1).strip()

    esc_match = re.search(r"ESCALATE:\s*(YES|NO)", raw, re.IGNORECASE)
    if esc_match:
        escalate = esc_match.group(1).upper() == "YES"

    return Recommendation(
        action=action,
        reasoning=reasoning,
        escalation_needed=escalate,
        raw_response=raw,
    )


# ---------------------------------------------------------------------------
# Agent entrypoint
# ---------------------------------------------------------------------------

async def run_triage(incident: Incident, config: AgentConfig) -> IncidentReport:
    """Run the full 4-step triage pipeline for a single incident."""
    report = IncidentReport(incident_id=incident.id)
    request_id = str(uuid.uuid4())
    overall_start = time.perf_counter()

    def _technique(step: str) -> str:
        return config.technique_override or STEP_TECHNIQUES.get(step, "baseline")

    # ── Step 1: Classify ──────────────────────────────────────
    try:
        t0 = time.perf_counter()
        llm = make_llm(
            config.gateway_url, config.model, _technique("classify"),
            streaming=False, timeout=15.0, request_id=request_id,
        )
        chain = _CLASSIFY_PROMPT | llm | StrOutputParser()

        raw = await with_retry(
            lambda: chain.ainvoke({"title": incident.title, "description": incident.description}),
            step_name=f"classify({incident.id})",
            max_retries=config.max_retries,
            timeout=15.0,
        )
        report.classification = _parse_classification(raw)
        report.step_latencies["classify"] = time.perf_counter() - t0
        log.info(
            "[%s] classified: %s/%s (%.0f%%)",
            incident.id, report.classification.severity,
            report.classification.category, report.classification.confidence * 100,
        )
    except Exception as exc:
        report.step_latencies["classify"] = time.perf_counter() - t0
        report.error = f"classify failed: {exc}"
        report.total_latency = time.perf_counter() - overall_start
        return report

    # ── Step 2: Investigate (mock tools, no LLM) ─────────────
    try:
        t0 = time.perf_counter()
        tasks = [
            log_search(incident, report.classification),
            system_metrics(incident, report.classification),
        ]
        # Runbook only for high/critical
        if report.classification.severity in ("high", "critical"):
            tasks.append(runbook_fetch(incident, report.classification))

        results = await asyncio.gather(*tasks)
        report.tool_results = list(results)
        report.step_latencies["investigate"] = time.perf_counter() - t0
        log.info("[%s] investigated: %d tools called", incident.id, len(results))
    except Exception as exc:
        report.step_latencies["investigate"] = time.perf_counter() - t0
        report.error = f"investigate failed: {exc}"
        report.total_latency = time.perf_counter() - overall_start
        return report

    # ── Step 3: Recommend ─────────────────────────────────────
    try:
        t0 = time.perf_counter()
        llm = make_llm(
            config.gateway_url, config.model, _technique("recommend"),
            streaming=True, timeout=30.0, request_id=request_id,
        )
        chain = _RECOMMEND_PROMPT | llm | StrOutputParser()

        # Gather tool outputs for prompt
        logs_text = next((r.result for r in report.tool_results if r.tool_name == "log_search"), "N/A")
        metrics_text = next((r.result for r in report.tool_results if r.tool_name == "system_metrics"), "N/A")
        runbook_text = next((r.result for r in report.tool_results if r.tool_name == "runbook_fetch"), "N/A")

        raw = await with_retry(
            lambda: chain.ainvoke({
                "title": incident.title,
                "severity": report.classification.severity,
                "category": report.classification.category,
                "logs": logs_text,
                "metrics": metrics_text,
                "runbook": runbook_text,
            }),
            step_name=f"recommend({incident.id})",
            max_retries=config.max_retries,
            timeout=30.0,
        )
        report.recommendation = _parse_recommendation(raw)
        report.step_latencies["recommend"] = time.perf_counter() - t0
        log.info("[%s] recommendation: %s", incident.id, report.recommendation.action[:80])
    except Exception as exc:
        report.step_latencies["recommend"] = time.perf_counter() - t0
        report.error = f"recommend failed: {exc}"
        report.total_latency = time.perf_counter() - overall_start
        return report

    # ── Step 4: Summarize ─────────────────────────────────────
    try:
        t0 = time.perf_counter()
        llm = make_llm(
            config.gateway_url, config.model, _technique("summarize"),
            streaming=False, timeout=20.0, request_id=request_id,
        )
        chain = _SUMMARIZE_PROMPT | llm | StrOutputParser()

        report.summary = await with_retry(
            lambda: chain.ainvoke({
                "title": incident.title,
                "severity": report.classification.severity,
                "category": report.classification.category,
                "action": report.recommendation.action,
                "reasoning": report.recommendation.reasoning,
            }),
            step_name=f"summarize({incident.id})",
            max_retries=config.max_retries,
            timeout=20.0,
        )
        report.step_latencies["summarize"] = time.perf_counter() - t0
        log.info("[%s] summarized (%d chars)", incident.id, len(report.summary))
    except Exception as exc:
        report.step_latencies["summarize"] = time.perf_counter() - t0
        report.error = f"summarize failed: {exc}"
        report.total_latency = time.perf_counter() - overall_start
        return report

    report.success = True
    report.total_latency = time.perf_counter() - overall_start
    return report
