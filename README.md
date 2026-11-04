# PodAI: Autonomous Agile Software Delivery Squad

> Contract-first, multi-agent software engineering squad that translates high-level Epic descriptions and acceptance criteria into verified, production-ready codebases.

Built for the **Meta Global AI Developer Hackathon**.

---

## Overview

Single-file AI autocomplete tools and unconstrained terminal subagents often suffer from **context drift**, broken cross-module imports, and unverified tests. 

**PodAI** models an agile engineering pod by enforcing a **contract-first architecture**:
1. **Scrum Master / Architect (Meta Muse Wonder)** analyzes ambiguous requirements, locks immutable interfaces in `contracts.py`, and schedules an execution DAG with explicit test assertions.
2. **Peer Developers (Meta Muse Spark)** implement modular code and pytest suites concurrently.
3. **Sandboxed Verification (Modal Containers)** proves tests pass green inside isolated cloud micro-VMs, with automated self-repair loops for runtime failures.
4. **Human-in-the-Loop Governance** provides review gates at sprint planning and final pull request sign-off.
---
## Architecture Lifecycle

```text
                 HUMAN ARCHITECT / TECH LEAD
             [Epic Spec & Acceptance Criteria]
                             │
                             ▼
              SCRUM MASTER (Meta Muse Wonder)
        ┌───────────────────────────────────────────┐
        │ • Explains Architectural Rationale        │
        │ • Locks Shared Contract (contracts.py)    │
        │ • Decomposes Task DAG & Test Case Specs   │
        └───────────────────────────────────────────┘
                             │
                             ▼
                     [PLAN REVIEW GATE] ◀── (Human Feedback Loop)
                             │
                             │ (Approved)
                             ▼
                 PARALLEL EXECUTION WAVES
        ┌───────────────────────────────────────────┐
        │  Wave 0 (Independent Core Components)    │
        │  Wave 1 (Integration & Middleware)        │
        │                                           │
        │  [Worker Agent]       [Worker Agent]      │
        │  (Meta Muse Spark)    (Meta Muse Spark)   │
        └─────────────┬──────────────────────┬──────┘
                      │                      │
                      ▼                      ▼
        ┌───────────────────────────────────────────┐
        │    MODAL EPHEMERAL MICRO-VM SANDBOXES     │
        │  • Isolated Pytest Execution              │
        │  • Automated Self-Repair on Failure       │
        └─────────────────────┬─────────────────────┘
                              │
                              ▼
                   [AWAITING PR REVIEW]
             (Human Review of Clean Artifacts)
                              │
                              ▼
                        [EPIC SHIPPED]

Key Features
Contract-First Invariants: All data schemas, enums, and protocols are locked in contracts.py before worker code synthesis begins.

Topological Wave Execution: Uses Kahn's algorithm to resolve task dependencies and dispatch independent stories in parallel execution waves.

Automated Self-Repair: When a sandbox test fails, the traceback is captured and passed back to Meta Muse Spark to fix implementation bugs without breaking shared contracts.

Smart Blocker Aggregation: Batch escalations surface structured resolution options for human lead sign-off instead of interrupting development loops.

Verified Repository Export: Generates clean directory structures containing /contracts, /app, /tests, execution traces, and a local ./verify_local.sh test runner.

Tech Stack
Reasoning & Planning: Meta Muse Wonder (Scrum Master)

Code & Test Generation: Meta Muse Spark (Worker Agents)

Execution Sandboxes: Modal Micro-VM Containers (Linux ephemeral runtime)

Control Plane & UI: FastAPI, Uvicorn, Tailwind CSS, Server-Sent State Machine

Validation Engine: Pytest, Pydantic v2

Repository Structure
Plaintext
.
├── dashboard.py         # FastAPI interactive state-machine control plane & UI
├── schemas.py           # Pydantic schemas (ArchitecturePlan, TaskNode, TestCases)
├── personas.py          # Meta Muse prompt engineering & agent persona definitions
├── orchestrator.py      # Dependency DAG & Kahn's topological wave scheduler
├── worker_loop.py       # Worker execution loop, test runner, and self-repair engine
├── sandbox_runner.py    # Modal micro-VM ephemeral container integration
├── run_pipeline.py      # Headless/CLI runner for autonomous pod execution
├── contracts.py         # Baseline system interface contract template
├── slide.html           # Architecture overview and pitch visual
└── generated_epics/     # Auto-exported clean repos with code, tests, and audit logs


Quickstart
Prerequisites
Python 3.10+

Modal Account (for cloud sandbox execution)
1. Clone & Set Up Environment
Bash
git clone [https://github.com/Harin0231/podAI.git](https://github.com/Harin0231/podAI.git)
cd podAI

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

2. Configure Environment Variables
Bash
export MODEL_API_KEY="your-model-api-key"
export MODAL_TOKEN_ID="your-modal-token-id"
export MODAL_TOKEN_SECRET="your-modal-token-secret"


3. Launch the Control Plane
Bash
python dashboard.py
Open http://localhost:8000 in your browser to inspect or run autonomous sprints.
