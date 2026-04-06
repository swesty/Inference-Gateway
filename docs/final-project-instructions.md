This is an InferenceOps assignment. You own one agentic use case and the entire path from the first request byte until the response is served, then you experiment, justify, and dashboard the system like a production review.

Submission:

Submit a GitHub repo URL which includes a submission.ipynb file (and submission.pdf - use nbconvert to do this for failsafe), runnable top-to-bottom with committed sample data.

We will only use submission.pdf if notebook rendering fails but live presentation walks through submission.ipynb

What will Github Repo include

Runnable path through nginx (if you require it) → gateway → tunnel → vLLM as in class, or documented equivalent.

Enough README (or a short SUBMISSION.md) to: clone, configure .env from .env.example, start stack, run their agent / load script. No secrets in the repo.

What will submission.ipnyb/pdf include

Story: agentic use case, E2E diagram (image or mermaid), SLOs, InferenceOps “where we look first.”

Experiments: what arms they ran, pinned model / vLLM / GPU / flags.

Evidence: code that loads committed sample data (e.g. data/samples/… or exported metrics/JSONL snippet) and produces tables + at least a couple plots (latency, errors, etc.).

Decisions: short model + instance justification tied to those numbers.

Dashboard: one screenshot checked in (e.g. figures/dashboard.png) or clear note that graders follow links only if you allow live demos.

1. Assigment Objectives

Define an agentic application (multi-step / tools / crew-style), with clear success metrics and failure modes.

Trace every request end-to-end: LB → gateway → tunnel → vLLM, and know which metrics belong to which hop.

Run repeatable inference experiments: at least two distinct vllm serve engine configurations, controlled holds, pinned versions and flags.

Justify model and GPU/instance using workload + measured latency, throughput, errors, and cost, not only docs.

Build a dashboard a stakeholder can read in a few minutes: health of the full path, not only GPU charts. (include this screenshot in your notebook).

2. End-to-end Github Code

Include this as a system diagram in your notebook. You can use cursor to create a mermaid diagram code and use this to preview

https://marketplace.visualstudio.com/items?itemName=MermaidChart.vscode-mermaid-chart

This is what your project needs to include:

Client

python crew.py or curl to OpenAI-compatible HTTP

Load balancer

nginx / other e.g. 127.0.0.1:8780, monitoring/nginx-gateway-lb.conf

Inference gateway

gateway.py — routing, X-Technique, engine/backend mapping, /health, Prometheus llm_gateway_*, optional JSONL

Tunnel

ssh -L — laptop 8000+ → instance vLLM

vLLM/SGLang/Llama.cpp

your choice of engine: vllm serve — model + engine arguments

InferenceOps question you must answer in notebook:

If latency or errors spike, which layer do you check first (LB 502 vs gateway upstream vs tunnel vs vLLM OOM), and what metric do you use?

3. Part A — Agentic use case and metrics

Pick one agentic pattern (or propose equivalent depth):

Research / RAG agent — retrieve → synthesize; golden prompts or checks you define.

Ops / triage agent — classify + steps; mocked tools OK if documented.

Code agent — multi-step review or edit loop with a fixed small benchmark set.

Brief (include in the notebook)

User journey and failure modes (timeouts, bad tool args, partial runs).

SLIs / SLOs on the caller-visible path: e.g. p50/p95 for completed tasks, success rate on a golden set, cost per successful task (instance hourly rate × experiment window / successful completions, or Lambda cost hooks if configured).

Hypothesis: which vLLM engine settings should help your traffic (long shared prefixes → prefix cache; long prefill → chunked prefill; etc.) then tie to your traces, not generic bullets only.

4. Part B. Experiments (engine + gateway in the loop)

Implement a minimal path that hits the stack through nginx and the gateway (not a shortcut that bypasses them unless you justify an explicit “baseline ablation” arm).

Minimum matrix:

≥ 2 distinct vllm serve configurations (real engine-arg deltas — e.g. baseline vs chunked prefill or vs prefix caching). A label-only sweep on the same server is not enough as the only comparison.

≥ 1 extra dimension you label clearly: e.g. per-request beam vs eagle2 on the same server, or a small controlled change in generation params, state what is held constant and why.

Execution: scripted N runs per arm or bounded load (fixed concurrency, fixed duration). Record:

vLLM version, model id, exact serve flags or script names (scripts/vllm_engine/…), GPU SKU.

Gateway / .env knobs that matter: VLLM_SERVER_PROFILE, VLLM_AUTO_ENGINE_ROUTING, backend map JSON if used.

Include Results Table in NB per arm: p50/p95 (full response or TTFB + generation if you split), throughput, error rate, cost proxy for that run window.

5. Part C. Model and instance memo

NB clearly specifying

Model why this model for this agent (context, behavior, tool use, license). What’s the next model if p95 or cost fails SLO?

Instance / SKU why this GPU and region; what breaks if you drop VRAM or tier (batch, KV cache, OOM).

Production knob when you’d change gateway routing vs vLLM engine args vs scale-out (another gateway backend, etc.).

Senior bar: every claim should cite your numbers from Part B where possible.

6. Part D. Dashboard (agent + InferenceOps)

Build one dashboard (Grafana + Prometheus is the default; other tools OK if equivalent).

Must show:

End-to-end story: request volume and error rate over time for the path you actually use (via gateway / LB-exposed failures if measurable).

Latency: p50/p95 (or histograms) broken down by technique / server_profile (or labels your gateway exports).

Layer coverage: panels that relate to gateway (llm_gateway_*, 9101) and vLLM (/metrics through tunnel) — call out which is which in a text panel.

Efficiency: at least one of tokens/s, cost proxy, or vLLM engine utilization-style metrics if available.

Nice to have: one panel for agent-level success (e.g. golden-set pass rate over time).

Include: screenshot(s) + dashboard JSON export (or import path) + note on Prometheus scrape targets (gateway + vLLM).

7. Submission checklist

Architecture + ports: LB → gateway → tunnel → vLLM

Agentic brief + metrics: SLIs tied to user-visible path

Reproducibility: Commands, .env keys (no secrets), scripts used

Experiment results: Table / notebook + pinned versions (also include in Readme.md)

Model + SKU memo: Data-backed

Dashboard: Full-path + labeled layers

Reflection: Readme.md (≤ 300 words: surprise + one next instrumentation)

8. Grading rubric (suggested)

AreaWeight - Agent framing + SLOs = 10%

End-to-end path + InferenceOps (LB, gateway, diagnosis story) = 20%

Experimental rigor (real engine deltas, controls) = 25%

Model / instance justification= 20%

Dashboard (full path, not GPU-only) = 15%

Presentation= 10%

9. Stretch (optional)

Multi-gateway backend via nginx + compare under concurrent load.

Speculative decoding arm with documented draft model and failure handling.

OTLP traces (Jaeger) for requests, mapped to the same diagram.

Scoring will be privately communicated and not shared amongst the group members publicly.
