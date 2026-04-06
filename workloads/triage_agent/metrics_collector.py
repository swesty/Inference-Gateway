"""Aggregate triage results into a summary report."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from triage_agent.models import Incident, IncidentReport


class TriageMetrics:
    """Collects IncidentReports and produces aggregate stats."""

    def __init__(self) -> None:
        self.reports: list[IncidentReport] = []
        self.incidents: dict[str, Incident] = {}
        self.wall_clock: float = 0.0

    def add(self, report: IncidentReport, incident: Incident) -> None:
        self.reports.append(report)
        self.incidents[incident.id] = incident

    def summary(self) -> dict:
        total = len(self.reports)
        successes = [r for r in self.reports if r.success]
        failures = [r for r in self.reports if not r.success]

        # Per-step latency stats
        step_stats: dict[str, dict] = {}
        for step in ("classify", "investigate", "recommend", "summarize"):
            values = [r.step_latencies.get(step, 0.0) for r in successes if step in r.step_latencies]
            if values:
                values.sort()
                step_stats[step] = {
                    "mean": round(statistics.mean(values), 3),
                    "p50": round(values[len(values) // 2], 3),
                    "p95": round(values[int(len(values) * 0.95)], 3) if len(values) >= 2 else round(values[-1], 3),
                    "max": round(max(values), 3),
                }

        # Total latency stats
        totals = sorted(r.total_latency for r in successes) if successes else []
        total_stats = {}
        if totals:
            total_stats = {
                "mean": round(statistics.mean(totals), 3),
                "p50": round(totals[len(totals) // 2], 3),
                "p95": round(totals[int(len(totals) * 0.95)], 3) if len(totals) >= 2 else round(totals[-1], 3),
                "max": round(max(totals), 3),
            }

        # Classification accuracy vs golden set
        sev_correct = 0
        cat_correct = 0
        scored = 0
        for r in successes:
            inc = self.incidents.get(r.incident_id)
            if inc and inc.expected_severity and r.classification:
                scored += 1
                if r.classification.severity == inc.expected_severity:
                    sev_correct += 1
                if r.classification.category == inc.expected_category:
                    cat_correct += 1

        return {
            "total_incidents": total,
            "successes": len(successes),
            "failures": len(failures),
            "success_rate": round(len(successes) / total, 3) if total else 0,
            "classification_accuracy": {
                "scored": scored,
                "severity_correct": sev_correct,
                "severity_accuracy": round(sev_correct / scored, 3) if scored else 0,
                "category_correct": cat_correct,
                "category_accuracy": round(cat_correct / scored, 3) if scored else 0,
            },
            "step_latencies": step_stats,
            "total_latency": total_stats,
            "wall_clock_seconds": round(self.wall_clock, 3),
            "throughput_incidents_per_sec": round(total / self.wall_clock, 3) if self.wall_clock else 0,
            "errors": [
                {"incident_id": r.incident_id, "error": r.error}
                for r in failures
            ],
        }

    def print_table(self) -> None:
        """Print a human-readable summary table to stdout."""
        s = self.summary()
        print("\n" + "=" * 60)
        print("TRIAGE AGENT RESULTS")
        print("=" * 60)
        print(f"  Incidents:    {s['total_incidents']}")
        print(f"  Successes:    {s['successes']}")
        print(f"  Failures:     {s['failures']}")
        print(f"  Success rate: {s['success_rate']:.1%}")
        print(f"  Wall clock:   {s['wall_clock_seconds']:.1f}s")
        print(f"  Throughput:   {s['throughput_incidents_per_sec']:.2f} incidents/s")

        acc = s["classification_accuracy"]
        if acc["scored"]:
            print(f"\n  Classification ({acc['scored']} scored):")
            print(f"    Severity accuracy: {acc['severity_accuracy']:.1%}")
            print(f"    Category accuracy: {acc['category_accuracy']:.1%}")

        if s["step_latencies"]:
            print("\n  Step Latencies (seconds):")
            print(f"  {'Step':<14} {'Mean':>7} {'p50':>7} {'p95':>7} {'Max':>7}")
            for step, stats in s["step_latencies"].items():
                print(f"  {step:<14} {stats['mean']:>7.3f} {stats['p50']:>7.3f} {stats['p95']:>7.3f} {stats['max']:>7.3f}")

        if s["total_latency"]:
            t = s["total_latency"]
            print(f"\n  Total Latency: p50={t['p50']:.3f}s  p95={t['p95']:.3f}s  max={t['max']:.3f}s")

        if s["errors"]:
            print(f"\n  Errors:")
            for e in s["errors"]:
                print(f"    [{e['incident_id']}] {e['error']}")
        print("=" * 60)

    def save(self, path: str | Path) -> None:
        """Write full results (reports + summary) to a JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        output = {
            "summary": self.summary(),
            "reports": [r.model_dump() for r in self.reports],
        }
        p.write_text(json.dumps(output, indent=2, default=str))
        print(f"\nResults written to {p}")
