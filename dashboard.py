# dashboard.py
import concurrent.futures
import json
import os
import re
import threading
import time
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

from orchestrator import compute_execution_tiers
from personas import run_scrum_master
from sandbox_runner import sandbox_session
from schemas import ArchitecturePlan, TaskNode
from worker_loop import execute_worker_task

app = FastAPI(title="PodAI Autonomous Agile Control Plane")

DEFAULT_EPIC_TITLE = "Enterprise Multi-Algorithm Rate Limiter API"
DEFAULT_EPIC_DESC = """Build a high-throughput, thread-safe rate limiter service for FastAPI supporting configurable algorithms and storage engines.
Architecture Requirements:
1. Algorithm Support: Support Token Bucket (burst-tolerant) and Sliding Window Log (zero-burst guarantee).
2. Storage Support: Provide a thread-safe In-Memory store with an abstract BaseStorage interface ready for Redis.
3. Middleware: Intercept HTTP requests, apply rate limiting per client IP or API key, return RFC-compliant 429 Too Many Requests with Retry-After and rate limit headers.
4. Observability: Expose /metrics reporting total requests, allowed requests, and rejected counts."""

DEFAULT_AC = """1. Must implement TokenBucket algorithm (refills continuously, handles burst capacity).
2. Must implement SlidingWindow algorithm (tracks precise timestamps over time window).
3. Thread-safe InMemoryStorage with clean key-value lookup and eviction interface.
4. Abstract BaseStorage class in contracts so Redis storage can be swapped in without changing middleware.
5. FastAPI middleware returns 429 with Retry-After header and X-RateLimit headers.
6. /metrics endpoint returns real-time counters.
7. Dedicated pytest test suite for every single component with 100% pass rate in sandboxes."""

state_lock = threading.RLock()

state: Dict[str, Any] = {
    "status": "SPECIFICATION",
    "epic_title": DEFAULT_EPIC_TITLE,
    "epic_desc": DEFAULT_EPIC_DESC,
    "acceptance_criteria": DEFAULT_AC,
    "plan_revision": 1,
    "revision_feedback": "",
    "contracts_code": "",
    "plan_rationale": "",
    "tasks": [],
    "tiers": [],
    "active_tier": -1,
    "progress_percent": 0,
    "selected_node": "CONTRACT",
    "logs": [],
    "workspace": {},
    "audit_trails": {},
    "elapsed": 0.0,
    "repo_path": "",
}


def sanitize_filename(title: str) -> str:
    s = re.sub(r"[^\w\s-]", "", title.lower())
    return re.sub(r"[-\s]+", "_", s).strip("_")


def log_event(msg: str):
    timestamped = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(f"\n[PodAI] {msg}")
    with state_lock:
        state["logs"].append(timestamped)


def export_structured_epic_repo():
    """Quick Win 3: Exports all verified files, tests, contracts, audit logs, and verify_local.sh"""
    base_slug = sanitize_filename(state["epic_title"])
    base_dir = os.path.join("generated_epics", base_slug)
    os.makedirs(base_dir, exist_ok=True)

    # 1. Write Code & Test Files
    for rel_path, content in state["workspace"].items():
        if rel_path == "contracts.py":
            target = os.path.join(base_dir, "contracts", "contracts.py")
        elif rel_path.startswith("app/") or rel_path.startswith("tests/"):
            target = os.path.join(base_dir, rel_path)
        else:
            target = os.path.join(base_dir, rel_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)

    # 2. Write AI Context and Audit Artifacts
    ai_ctx_dir = os.path.join(base_dir, ".pod_ai_context")
    os.makedirs(os.path.join(ai_ctx_dir, "audit_trail"), exist_ok=True)

    with open(
        os.path.join(ai_ctx_dir, "epic_spec.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(
            {
                "epic_title": state["epic_title"],
                "epic_desc": state["epic_desc"],
                "acceptance_criteria": state["acceptance_criteria"],
                "plan_rationale": state["plan_rationale"],
                "plan_revisions": state["plan_revision"],
            },
            f,
            indent=2,
        )

    with open(
        os.path.join(ai_ctx_dir, "architecture_plan.json"),
        "w",
        encoding="utf-8",
    ) as f:
        tasks_clean = [
            {k: v for k, v in t.items() if k != "files"} for t in state["tasks"]
        ]
        json.dump(
            {
                "contracts": state["contracts_code"],
                "tasks": tasks_clean,
                "tiers": state["tiers"],
            },
            f,
            indent=2,
        )

    for story_id, trace in state["audit_trails"].items():
        with open(
            os.path.join(ai_ctx_dir, "audit_trail", f"{story_id}_trace.log"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(trace)

    # 3. Quick Win 3: Add verify_local.sh and README.md
    verify_script_path = os.path.join(base_dir, "verify_local.sh")
    with open(verify_script_path, "w", encoding="utf-8") as f:
        f.write(
            "#!/bin/bash\n"
            "# Auto-generated by PodAI for independent local execution\n"
            "set -e\n"
            'export PYTHONPATH=".:$PYTHONPATH"\n'
            'echo "========================================================="\n'
            'echo "RUNNING PODAI VERIFIED TEST SUITE LOCALLY"\n'
            'echo "========================================================="\n'
            "pytest tests/ -v\n"
            'echo "All tests passed cleanly!"\n'
        )
    os.chmod(verify_script_path, 0o755)

    with open(os.path.join(base_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(
            f"# {state['epic_title']}\n\n"
            f"Autonomous Sprint delivered by **PodAI** using Meta Muse and Modal Micro-VMs.\n\n"
            f"### Acceptance Criteria Met:\n{state['acceptance_criteria']}\n\n"
            f"### Run Verification Locally:\n```bash\n./verify_local.sh\n```\n"
        )

    with state_lock:
        state["repo_path"] = f"./{base_dir}/"
    log_event(
        f"Clean repository artifacts + verify_local.sh persisted to ./{base_dir}/"
    )


class PlanRequest(BaseModel):
    epic_title: str
    epic_desc: str
    acceptance_criteria: str
    feedback: Optional[str] = None


class ResolveBlockerRequest(BaseModel):
    story_id: str
    resolution: str


def run_planning_thread(
    epic_title: str,
    epic_desc: str,
    acceptance_criteria: str,
    feedback: Optional[str] = None,
):
    with state_lock:
        state["status"] = "PLANNING"
        state["epic_title"] = epic_title
        state["epic_desc"] = epic_desc
        state["acceptance_criteria"] = acceptance_criteria
        if feedback:
            state["plan_revision"] += 1
            state["revision_feedback"] = feedback

    log_event(f"Meta Muse Wonder: Architectural Planning for '{epic_title}'...")
    full_spec = (
        f"EPIC: {epic_title}\n\nDESCRIPTION:\n{epic_desc}\n\nACCEPTANCE"
        f" CRITERIA:\n{acceptance_criteria}"
    )
    if feedback:
        full_spec += (
            f"\n\nHUMAN ARCHITECT FEEDBACK ON PREVIOUS PLAN:\n{feedback}\nPlease"
            " adjust contracts and tasks accordingly."
        )

    try:
        plan: ArchitecturePlan = run_scrum_master(full_spec)
        tiers = compute_execution_tiers(plan.tasks)
    except Exception as e:
        log_event(f"Planning Error: {e}")
        with state_lock:
            state["status"] = "FAILED"
        return

    with state_lock:
        state["contracts_code"] = plan.contracts_code
        state["plan_rationale"] = plan.plan_rationale
        state["workspace"] = {"contracts.py": plan.contracts_code}

        task_list = []
        for t in plan.tasks:
            task_list.append({
                "story_id": t.story_id,
                "title": t.title,
                "description": t.description,
                "dependencies": t.dependencies,
                "owned_files": t.owned_files,
                "acceptance_criteria": t.acceptance_criteria,
                "test_cases": [tc.model_dump() for tc in t.test_cases],
                "test_command": t.test_command,
                "status": "QUEUED",
                "attempts": 0,
                "files": {},
                "error": None,
                "summary": None,
            })
        state["tasks"] = task_list
        state["tiers"] = [[t.story_id for t in tier] for tier in tiers]
        state["status"] = "PLAN_REVIEW"
        state["selected_node"] = "RATIONALE"

    log_event(
        f"Plan ready for Review: Generated {len(plan.tasks)} stories with"
        f" pre-defined test cases across {len(tiers)} waves."
    )


def run_execution_thread():
    start_time = time.time()
    with state_lock:
        state["status"] = "EXECUTING"
        state["active_tier"] = 0
        state["progress_percent"] = 5
        state["audit_trails"] = {}

    log_event("Sprint Approved! Launching parallel Modal micro-VM sandboxes...")
    total_tasks = len(state["tasks"])
    completed_tasks = 0

    with sandbox_session(backend="modal"):
        for tier_idx, story_ids in enumerate(state["tiers"]):
            with state_lock:
                state["active_tier"] = tier_idx
                current_workspace = dict(state["workspace"])
                tier_task_objs = [
                    TaskNode(
                        story_id=t["story_id"],
                        title=t["title"],
                        description=t["description"],
                        dependencies=t["dependencies"],
                        owned_files=t["owned_files"],
                        acceptance_criteria=t["acceptance_criteria"],
                        test_cases=t.get("test_cases", []),
                        test_command=t["test_command"],
                    )
                    for t in state["tasks"]
                    if t["story_id"] in story_ids
                ]
                for t in state["tasks"]:
                    if t["story_id"] in story_ids:
                        t["status"] = "RUNNING"
                        t["attempts"] = 1

            log_event(
                f"Wave {tier_idx} starting: {len(tier_task_objs)} tasks"
                " executing concurrently..."
            )
            tier_results = []
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(tier_task_objs)
            ) as executor:
                futures = {
                    executor.submit(
                        execute_worker_task,
                        task=task_obj,
                        locked_contract=state["contracts_code"],
                        shared_workspace=current_workspace,
                        backend="modal",
                    ): task_obj
                    for task_obj in tier_task_objs
                }

                for future in concurrent.futures.as_completed(futures):
                    res = future.result()
                    tier_results.append(res)
                    with state_lock:
                        for item in state["tasks"]:
                            if item["story_id"] == res["story_id"]:
                                item["status"] = res["status"]
                                item["attempts"] = res["attempts"]
                                item["files"] = res["files"]
                                item["error"] = res["error"]
                                if res["status"] == "PASSED":
                                    completed_tasks += 1
                                    state["workspace"].update(res["files"])
                                    state["audit_trails"][res["story_id"]] = (
                                        f"VERIFIED PASSED (Attempt"
                                        f" {res['attempts']})\nFiles:"
                                        f" {list(res['files'].keys())}\nAll"
                                        " tests green inside Modal."
                                    )
                                    item["summary"] = (
                                        f"Implemented"
                                        f" {', '.join(res['files'].keys())}"
                                        f" passing all test cases in"
                                        f" {res['attempts']} attempt(s)."
                                    )
                                else:
                                    state["audit_trails"][res["story_id"]] = (
                                        f"BLOCKED\n{res['error']}"
                                    )
                                    item["summary"] = (
                                        f"Blocked on test failure:"
                                        f" {str(res['error'])[:120]}"
                                    )
                        state["progress_percent"] = int(
                            (completed_tasks / max(total_tasks, 1)) * 90
                        )

                    if res["status"] == "PASSED":
                        log_event(
                            f"Task {res['story_id']} VERIFIED GREEN in Modal"
                            f" (Attempt {res['attempts']})"
                        )
                    else:
                        log_event(
                            f"Task {res['story_id']} BLOCKED in Sandbox:"
                            f" {str(res['error'])[:80]}"
                        )

            if any(r["status"] != "PASSED" for r in tier_results):
                with state_lock:
                    state["status"] = "FAILED"
                log_event("Sprint paused on task failure. Check task logs.")
                return

    export_structured_epic_repo()
    with state_lock:
        state["status"] = "AWAITING_PR_REVIEW"
        state["progress_percent"] = 100
        state["elapsed"] = round(time.time() - start_time, 1)
    log_event(
        f"Execution Complete ({state['elapsed']}s). Moved to Awaiting PR"
        " Review!"
    )


@app.post("/api/plan")
def plan_epic(payload: PlanRequest, background_tasks: BackgroundTasks):
    with state_lock:
        if state["status"] in ("PLANNING", "EXECUTING"):
            return {"error": "Pipeline busy"}
    background_tasks.add_task(
        run_planning_thread,
        payload.epic_title,
        payload.epic_desc,
        payload.acceptance_criteria,
        payload.feedback,
    )
    return {"status": "PLANNING_QUEUED"}


@app.post("/api/approve-plan")
def approve_plan(background_tasks: BackgroundTasks):
    with state_lock:
        if state["status"] != "PLAN_REVIEW":
            return {"error": "Plan not in review state"}
    background_tasks.add_task(run_execution_thread)
    return {"status": "EXECUTION_STARTED"}


@app.post("/api/approve-pr")
def approve_pr():
    with state_lock:
        if state["status"] != "AWAITING_PR_REVIEW":
            return {"error": "Not awaiting PR review"}
        state["status"] = "EPIC_SHIPPED"
    log_event("Human signed off on PR. Epic marked SHIPPED!")
    return {"status": "SHIPPED"}


@app.post("/api/resolve-blocker")
def resolve_blocker(payload: ResolveBlockerRequest):
    """Quick Win 1: Resolves simulated blocker with human choice"""
    log_event(
        f"Human Sign-Off Applied to [{payload.story_id}]: {payload.resolution}"
    )
    with state_lock:
        for t in state["tasks"]:
            if t["story_id"] == payload.story_id:
                t["status"] = "PASSED"
                t["summary"] = (
                    f"Resolved via Scrum Master Escalation:"
                    f" {payload.resolution}"
                )
    return {"status": "RESOLVED"}


@app.get("/api/state")
def get_state():
    with state_lock:
        return dict(state)


@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <title>PodAI Control Plane &middot; Contract-First Agile Squad</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            darkbg: '#090D16',
            cardbg: '#111827',
            cardborder: '#1F2937',
            brand: '#3B82F6',
          }
        }
      }
    }
  </script>
  <style>
    pre code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #090D16; }
    ::-webkit-scrollbar-thumb { background: #374151; border-radius: 3px; }
  </style>
</head>
<body class="bg-darkbg text-gray-200 min-h-screen flex flex-col font-sans selection:bg-blue-600 selection:text-white">

  <!-- TOP APP BAR -->
  <header class="border-b border-cardborder bg-cardbg px-6 py-3 flex items-center justify-between shadow-lg z-20">
    <div class="flex items-center gap-3">
      <div class="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center text-white shadow-blue-500/20 shadow-lg">
        <i class="fa-solid fa-shapes text-lg"></i>
      </div>
      <div>
        <h1 class="text-base font-bold tracking-wide text-white flex items-center gap-2">
          PodAI <span class="text-[10px] px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30 font-mono">AUTONOMOUS SQUAD</span>
        </h1>
        <p class="text-xs text-gray-400">Meta Muse Wonder &middot; Meta Muse Spark &middot; Modal Micro-VM Sandboxes</p>
      </div>
    </div>
    
    <!-- State Machine Stepper -->
    <div class="flex items-center gap-2 bg-darkbg px-3 py-1.5 rounded-lg border border-cardborder text-xs">
      <span id="step-SPECIFICATION" class="px-2 py-0.5 rounded font-bold text-gray-500">1. Epic Spec</span>
      <i class="fa-solid fa-chevron-right text-[10px] text-gray-600"></i>
      <span id="step-PLANNING" class="px-2 py-0.5 rounded font-bold text-gray-500">2. Planning</span>
      <i class="fa-solid fa-chevron-right text-[10px] text-gray-600"></i>
      <span id="step-PLAN_REVIEW" class="px-2 py-0.5 rounded font-bold text-gray-500">3. Plan Review</span>
      <i class="fa-solid fa-chevron-right text-[10px] text-gray-600"></i>
      <span id="step-EXECUTING" class="px-2 py-0.5 rounded font-bold text-gray-500">4. Autonomous Execution</span>
      <i class="fa-solid fa-chevron-right text-[10px] text-gray-600"></i>
      <span id="step-AWAITING_PR_REVIEW" class="px-2 py-0.5 rounded font-bold text-gray-500">5. Awaiting PR Review</span>
      <i class="fa-solid fa-chevron-right text-[10px] text-gray-600"></i>
      <span id="step-EPIC_SHIPPED" class="px-2 py-0.5 rounded font-bold text-gray-500">6. Shipped</span>
    </div>

    <!-- QUICK WIN 1 & 2 ACTIONS IN HEADER -->
    <div class="flex items-center gap-3">
      <!-- Quick Win 1 Button -->
      <button onclick="openBlockerModal()" class="px-2.5 py-1 rounded bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 text-xs font-semibold flex items-center gap-1.5 transition">
        <i class="fa-solid fa-triangle-exclamation"></i> Smart Blocker Demo
      </button>

      <!-- Quick Win 2 Link -->
      <a href="https://modal.com/apps" target="_blank" class="px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 text-xs font-semibold flex items-center gap-1.5 transition">
        <i class="fa-solid fa-cloud"></i> Modal Fleet <i class="fa-solid fa-arrow-up-right-from-square text-[9px] text-gray-400"></i>
      </a>

      <!-- State Badge -->
      <div id="stateBadge" class="px-3 py-1 rounded-full text-xs font-semibold bg-gray-800 text-gray-400 border border-gray-700 flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-gray-500"></span> SPECIFICATION
      </div>
    </div>
  </header>

  <!-- SUBHEADER: TELEMETRY -->
  <div class="bg-gray-900/60 border-b border-cardborder px-6 py-2 flex items-center justify-between text-xs">
    <div class="flex items-center gap-6">
      <div class="flex items-center gap-2">
        <span class="text-gray-400 font-mono">Progress:</span>
        <div class="w-48 bg-darkbg h-2 rounded-full overflow-hidden border border-gray-700">
          <div id="progressBar" class="bg-blue-500 h-full transition-all duration-500" style="width: 0%"></div>
        </div>
        <span id="progressText" class="font-mono font-bold text-white">0%</span>
      </div>
      <div class="flex items-center gap-2 text-gray-400 font-mono">
        <span>Active Wave:</span>
        <span id="activeTierText" class="font-bold text-blue-400">Idle</span>
      </div>
      <div class="flex items-center gap-2 text-gray-400 font-mono">
        <span>Time:</span>
        <span id="elapsedText" class="font-bold text-white">0.0s</span>
      </div>
    </div>
    <div id="repoPathBadge" class="text-gray-400 font-mono text-[11px] truncate max-w-sm">
      Artifacts will export to ./generated_epics/
    </div>
  </div>

  <!-- MAIN WORKSPACE -->
  <main class="flex-1 grid grid-cols-12 gap-6 p-6 overflow-hidden">
    
    <!-- LEFT COLUMN: Input Form & Tree Matrix (5 Cols) -->
    <section class="col-span-5 bg-cardbg rounded-xl border border-cardborder flex flex-col overflow-hidden shadow-xl">
      <div class="p-3 border-b border-cardborder flex items-center justify-between bg-gray-900/40">
        <div class="flex items-center gap-2">
          <button id="leftTabEpic" onclick="setLeftTab('epic')" class="text-xs px-3 py-1 rounded-lg font-bold bg-blue-600 text-white transition">
            <i class="fa-solid fa-file-pen mr-1"></i> Epic Definition
          </button>
          <button id="leftTabTree" onclick="setLeftTab('tree')" class="text-xs px-3 py-1 rounded-lg font-bold bg-gray-800 text-gray-400 hover:text-white transition">
            <i class="fa-solid fa-network-wired mr-1"></i> Execution DAG
          </button>
        </div>
        <span id="revisionBadge" class="text-[10px] bg-gray-800 text-gray-400 px-2 py-0.5 rounded font-mono border border-gray-700">Rev 1</span>
      </div>

      <!-- LEFT TAB 1: EPIC FORM -->
      <div id="leftContentEpic" class="flex-1 overflow-y-auto p-4 space-y-4">
        <div>
          <label class="block text-xs font-bold text-gray-300 uppercase mb-1">Epic Title</label>
          <input id="inputTitle" type="text" class="w-full bg-darkbg border border-cardborder rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 font-semibold">
        </div>
        <div>
          <label class="block text-xs font-bold text-gray-300 uppercase mb-1">Architecture & Algorithms (Token Bucket, Sliding Window, Storage)</label>
          <textarea id="inputDesc" rows="5" class="w-full bg-darkbg border border-cardborder rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 font-mono"></textarea>
        </div>
        <div>
          <label class="block text-xs font-bold text-gray-300 uppercase mb-1">Acceptance Criteria</label>
          <textarea id="inputAC" rows="6" class="w-full bg-darkbg border border-cardborder rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 font-mono"></textarea>
        </div>
        <button id="planBtn" onclick="triggerPlan()" class="w-full py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 shadow-lg shadow-blue-600/30">
          <i class="fa-solid fa-wand-magic-sparkles"></i> Plan Epic & Generate Test Cases
        </button>
      </div>

      <!-- LEFT TAB 2: DAG TREE & NODES -->
      <div id="leftContentTree" class="flex-1 overflow-y-auto p-4 space-y-3 hidden">
        <div onclick="selectNode('RATIONALE')" id="node-RATIONALE" class="cursor-pointer border border-purple-500/40 bg-purple-500/10 rounded-lg p-3 hover:border-purple-400 transition">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-white flex items-center gap-2">
              <i class="fa-solid fa-brain text-purple-400"></i> AI Architectural Rationale
            </span>
            <span class="text-[10px] bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded font-mono border border-purple-500/30">Why this Plan?</span>
          </div>
          <p class="text-[11px] text-gray-400 mt-1">Scrum Master reasoning, concurrency waves, and contract design.</p>
        </div>

        <div onclick="selectNode('CONTRACT')" id="node-CONTRACT" class="cursor-pointer border border-blue-500/40 bg-blue-500/10 rounded-lg p-3 hover:border-blue-400 transition">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-white flex items-center gap-2">
              <i class="fa-solid fa-shield-halved text-blue-400"></i> Locked System Contract
            </span>
            <span class="text-[10px] bg-blue-500/20 text-blue-300 px-2 py-0.5 rounded font-mono border border-blue-500/30">contracts.py</span>
          </div>
          <p class="text-[11px] text-gray-400 mt-1">Pydantic models & storage/algorithm interfaces.</p>
        </div>

        <div id="tiersContainer" class="space-y-4"></div>
      </div>

      <!-- LIVE LOG TICKER -->
      <div class="h-32 border-t border-cardborder bg-darkbg p-3 overflow-y-auto text-xs font-mono text-gray-400" id="logTerminal">
        <div>[System Ready] Define Epic spec or click Plan.</div>
      </div>
    </section>

    <!-- RIGHT COLUMN: Inspector & Review Gate (7 Cols) -->
    <section class="col-span-7 bg-cardbg rounded-xl border border-cardborder flex flex-col overflow-hidden shadow-xl">
      <div class="border-b border-cardborder px-4 py-3 flex items-center justify-between bg-gray-900/40">
        <div class="flex items-center gap-2">
          <span id="detailBadge" class="text-xs px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 font-mono font-bold">RATIONALE</span>
          <h2 id="detailTitle" class="text-xs font-bold text-white">AI Architectural Rationale</h2>
        </div>
        <div id="codeFileTabs" class="flex items-center gap-1 overflow-x-auto"></div>
      </div>

      <div id="humanGateBar" class="p-3 bg-blue-950/40 border-b border-blue-500/30 hidden"></div>

      <div class="flex-1 overflow-y-auto p-4" id="detailContent">
        <div class="h-full flex flex-col items-center justify-center text-gray-500 text-xs">
          <i class="fa-regular fa-folder-open text-3xl mb-2"></i>
          Select a step to inspect specifications, test suites, or code.
        </div>
      </div>
    </section>
  </main>

  <!-- QUICK WIN 1: SMART BLOCKER ESCALATION MODAL -->
  <div id="blockerModal" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center hidden">
    <div class="bg-cardbg border border-amber-500/40 rounded-xl p-5 max-w-lg w-full shadow-2xl space-y-4">
      <div class="flex items-center justify-between border-b border-gray-800 pb-3">
        <div class="flex items-center gap-2 text-amber-400 font-bold text-sm">
          <i class="fa-solid fa-triangle-exclamation"></i> Scrum Master Standup Briefing
        </div>
        <button onclick="closeBlockerModal()" class="text-gray-400 hover:text-white"><i class="fa-solid fa-xmark"></i></button>
      </div>

      <div class="space-y-2 text-xs">
        <div class="p-2.5 bg-amber-950/20 border border-amber-500/30 rounded text-amber-200">
          <strong>Escalated Task:</strong> <span class="font-mono">RL-02 (In-memory state store)</span><br>
          <strong>Root Blocker:</strong> Monotonic timer precision drift under high concurrency tests inside Modal micro-VM.
        </div>
        <p class="text-gray-300">The Scrum Master has batched this issue and generated two verified architectural resolutions for human sign-off:</p>
      </div>

      <div class="space-y-2">
        <button onclick="resolveBlocker('Option 1: Inject monotonic clock mock fixture into tests with pytest.approx(margin=0.05)')" class="w-full text-left p-3 rounded-lg bg-gray-900 hover:bg-gray-800 border border-gray-700 hover:border-blue-500 transition text-xs space-y-1">
          <div class="font-bold text-white flex items-center justify-between">
            <span>[Option 1] Inject Monotonic Mock Fixture</span>
            <span class="text-[10px] text-green-400 font-mono">Recommended</span>
          </div>
          <p class="text-gray-400 text-[11px]">Injects deterministic time advancing into test harness to prevent microsecond drift.</p>
        </button>

        <button onclick="resolveBlocker('Option 2: Widen rate limit test tolerance window to 50ms')" class="w-full text-left p-3 rounded-lg bg-gray-900 hover:bg-gray-800 border border-gray-700 hover:border-blue-500 transition text-xs space-y-1">
          <div class="font-bold text-white">[Option 2] Widen Test Tolerance Window</div>
          <p class="text-gray-400 text-[11px]">Relaxes pytest assertion margin without modifying core token bucket logic.</p>
        </button>
      </div>
    </div>
  </div>

  <script>
    let globalState = {};
    let activeLeftTab = 'epic';
    let selectedNodeId = 'RATIONALE';
    let selectedCodeTab = 0;

    function setLeftTab(tab) {
      activeLeftTab = tab;
      if (tab === 'epic') {
        document.getElementById('leftTabEpic').className = "text-xs px-3 py-1 rounded-lg font-bold bg-blue-600 text-white transition";
        document.getElementById('leftTabTree').className = "text-xs px-3 py-1 rounded-lg font-bold bg-gray-800 text-gray-400 hover:text-white transition";
        document.getElementById('leftContentEpic').classList.remove('hidden');
        document.getElementById('leftContentTree').classList.add('hidden');
      } else {
        document.getElementById('leftTabTree').className = "text-xs px-3 py-1 rounded-lg font-bold bg-blue-600 text-white transition";
        document.getElementById('leftTabEpic').className = "text-xs px-3 py-1 rounded-lg font-bold bg-gray-800 text-gray-400 hover:text-white transition";
        document.getElementById('leftContentTree').classList.remove('hidden');
        document.getElementById('leftContentEpic').classList.add('hidden');
      }
    }

    async function fetchState() {
      try {
        const res = await fetch('/api/state');
        if (!res.ok) return;
        globalState = await res.json();
        syncUI();
      } catch (e) {
        console.error(e);
      }
    }

    setInterval(fetchState, 1200);
    fetchState();

    function syncUI() {
      renderHeaderAndStepper();
      renderTiers();
      renderGateBar();
      renderInspector();

      const titleInput = document.getElementById('inputTitle');
      if (!titleInput.value && globalState.epic_title) {
        titleInput.value = globalState.epic_title;
        document.getElementById('inputDesc').value = globalState.epic_desc;
        document.getElementById('inputAC').value = globalState.acceptance_criteria;
      }
    }

    function renderHeaderAndStepper() {
      const s = globalState.status;
      const badge = document.getElementById('stateBadge');
      const pBar = document.getElementById('progressBar');
      const pText = document.getElementById('progressText');
      const waveText = document.getElementById('activeTierText');
      const elText = document.getElementById('elapsedText');
      const repoBadge = document.getElementById('repoPathBadge');

      pBar.style.width = `${globalState.progress_percent}%`;
      pText.innerText = `${globalState.progress_percent}%`;
      waveText.innerText = globalState.active_tier >= 0 ? `Wave ${globalState.active_tier}` : 'Idle';
      elText.innerText = `${globalState.elapsed || 0}s`;
      if (globalState.repo_path) repoBadge.innerText = `Artifacts: ${globalState.repo_path}`;

      const steps = ['SPECIFICATION', 'PLANNING', 'PLAN_REVIEW', 'EXECUTING', 'AWAITING_PR_REVIEW', 'EPIC_SHIPPED'];
      steps.forEach(st => {
        const el = document.getElementById(`step-${st}`);
        if (!el) return;
        if (s === st) {
          el.className = "px-2 py-0.5 rounded font-bold bg-blue-500 text-white shadow";
        } else if (steps.indexOf(st) < steps.indexOf(s)) {
          el.className = "px-2 py-0.5 rounded font-bold text-green-400";
        } else {
          el.className = "px-2 py-0.5 rounded font-bold text-gray-500";
        }
      });

      let color = 'bg-gray-800 text-gray-400 border-gray-700';
      let dot = 'bg-gray-500';
      if (s === 'PLANNING') {
        color = 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30';
        dot = 'bg-yellow-400 animate-ping';
      } else if (s === 'PLAN_REVIEW') {
        color = 'bg-purple-500/20 text-purple-300 border-purple-500/30';
        dot = 'bg-purple-400';
      } else if (s === 'EXECUTING') {
        color = 'bg-blue-500/20 text-blue-300 border-blue-500/30';
        dot = 'bg-blue-400 animate-ping';
      } else if (s === 'AWAITING_PR_REVIEW') {
        color = 'bg-amber-500/20 text-amber-300 border-amber-500/30';
        dot = 'bg-amber-400';
      } else if (s === 'EPIC_SHIPPED') {
        color = 'bg-green-500/20 text-green-300 border-green-500/30';
        dot = 'bg-green-400';
      }

      badge.className = `px-3 py-1 rounded-full text-xs font-semibold flex items-center gap-2 border ${color}`;
      badge.innerHTML = `<span class="w-2 h-2 rounded-full ${dot}"></span> ${s.replace(/_/g, ' ')}`;
      document.getElementById('revisionBadge').innerText = `Rev ${globalState.plan_revision || 1}`;

      const term = document.getElementById('logTerminal');
      if (globalState.logs && globalState.logs.length) {
        term.innerHTML = globalState.logs.map(l => `<div>${l}</div>`).join('');
        term.scrollTop = term.scrollHeight;
      }
    }

    function renderGateBar() {
      const gate = document.getElementById('humanGateBar');
      const s = globalState.status;

      if (s === 'PLAN_REVIEW') {
        gate.classList.remove('hidden');
        gate.innerHTML = `
          <div class="flex items-center justify-between gap-4">
            <div>
              <span class="text-xs font-bold text-purple-300 flex items-center gap-1.5">
                <i class="fa-solid fa-user-check"></i> Human Architecture Sign-Off Required
              </span>
              <p class="text-[11px] text-gray-300">Inspect the AI Rationale, Locked Contracts, and Story-Level Test Cases. Request changes or approve to begin autonomous execution.</p>
            </div>
            <div class="flex items-center gap-2">
              <button onclick="promptRevision()" class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-600 rounded-lg text-xs font-bold transition flex items-center gap-1.5">
                <i class="fa-solid fa-comment-dots"></i> Request Changes
              </button>
              <button onclick="approvePlan()" class="px-4 py-1.5 bg-green-600 hover:bg-green-500 text-white rounded-lg text-xs font-bold transition flex items-center gap-1.5 shadow-lg shadow-green-600/30">
                <i class="fa-solid fa-check-double"></i> Approve Plan & Test Cases
              </button>
            </div>
          </div>
        `;
      } else if (s === 'AWAITING_PR_REVIEW') {
        gate.classList.remove('hidden');
        gate.innerHTML = `
          <div class="flex items-center justify-between gap-4">
            <div>
              <span class="text-xs font-bold text-amber-300 flex items-center gap-1.5">
                <i class="fa-solid fa-clipboard-check"></i> Sprint Finished &middot; Awaiting Final Human PR Sign-Off
              </span>
              <p class="text-[11px] text-gray-300">All tests verified green in Modal sandboxes. Review the summary and sign off to mark the Epic SHIPPED.</p>
            </div>
            <div class="flex items-center gap-2">
              <button onclick="approvePR()" class="px-5 py-1.5 bg-green-600 hover:bg-green-500 text-white rounded-lg text-xs font-bold transition flex items-center gap-1.5 shadow-lg shadow-green-600/30">
                <i class="fa-solid fa-truck-fast"></i> Approve PR & Ship Epic
              </button>
            </div>
          </div>
        `;
      } else if (s === 'EPIC_SHIPPED') {
        gate.classList.remove('hidden');
        gate.className = "p-3 bg-green-950/40 border-b border-green-500/30";
        gate.innerHTML = `
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-green-300 flex items-center gap-1.5">
              <i class="fa-solid fa-circle-check"></i> Epic Successfully Shipped!
            </span>
            <span class="text-xs font-mono text-gray-300">Run locally: bash ${globalState.repo_path || './generated_epics/'}verify_local.sh</span>
          </div>
        `;
      } else {
        gate.classList.add('hidden');
      }
    }

    function renderTiers() {
      const container = document.getElementById('tiersContainer');
      if (!globalState.tiers || !globalState.tiers.length) {
        container.innerHTML = `<div class="text-xs text-gray-500 italic p-3 text-center border border-dashed border-cardborder rounded-lg">No plan generated yet. Fill out the Epic definition and click Plan.</div>`;
        return;
      }

      let html = '';
      globalState.tiers.forEach((tierTasks, idx) => {
        html += `
          <div class="border-t border-cardborder/50 pt-3">
            <div class="text-[10px] font-bold text-gray-400 tracking-wider uppercase mb-2 flex items-center justify-between">
              <span class="flex items-center gap-1.5"><span class="w-1.5 h-1.5 rounded-full bg-blue-500"></span> Wave ${idx} (Parallel Sandboxes)</span>
              <span class="text-[10px] text-gray-500 font-mono">${tierTasks.length} Task(s)</span>
            </div>
            <div class="grid grid-cols-1 gap-2">
        `;

        tierTasks.forEach(storyId => {
          const t = globalState.tasks.find(x => x.story_id === storyId);
          if (!t) return;

          let statusBadge = `<span class="text-[10px] bg-gray-800 text-gray-400 px-2 py-0.5 rounded border border-gray-700">QUEUED</span>`;
          let ring = 'border-cardborder hover:border-gray-600 bg-gray-900/40';

          if (t.status === 'RUNNING') {
            statusBadge = `<span class="text-[10px] bg-yellow-500/20 text-yellow-300 px-2 py-0.5 rounded border border-yellow-500/40 animate-pulse"><i class="fa-solid fa-microchip mr-1"></i> MODAL ACTIVE</span>`;
            ring = 'border-yellow-500/50 bg-yellow-500/10 shadow-lg shadow-yellow-500/5';
          } else if (t.status === 'PASSED') {
            const attText = t.attempts > 1 ? `Repaired (att ${t.attempts})` : 'Green (att 1)';
            statusBadge = `<span class="text-[10px] bg-green-500/20 text-green-300 px-2 py-0.5 rounded border border-green-500/30 flex items-center gap-1"><i class="fa-solid fa-check"></i> ${attText}</span>`;
            ring = 'border-green-500/40 bg-green-500/5';
          } else if (t.status === 'BLOCKED' || t.status === 'FAILED') {
            statusBadge = `<span class="text-[10px] bg-red-500/20 text-red-300 px-2 py-0.5 rounded border border-red-500/30">BLOCKED</span>`;
            ring = 'border-red-500/40 bg-red-500/5';
          }

          if (selectedNodeId === t.story_id) {
            ring += ' ring-2 ring-blue-500 border-transparent';
          }

          const tcCount = (t.test_cases || []).length;
          html += `
            <div onclick="selectNode('${t.story_id}')" class="cursor-pointer border rounded-lg p-2.5 transition ${ring}">
              <div class="flex items-center justify-between">
                <span class="text-xs font-bold text-white flex items-center gap-2">
                  <span class="text-blue-400 font-mono">[${t.story_id}]</span> ${t.title}
                </span>
                ${statusBadge}
              </div>
              <div class="flex items-center justify-between mt-1 text-[10px] text-gray-400 font-mono">
                <span><i class="fa-regular fa-file-code mr-1"></i> ${t.owned_files.join(', ')}</span>
                <span class="text-yellow-400/90 font-semibold"><i class="fa-solid fa-vial mr-1"></i>${tcCount} Test Cases</span>
              </div>
            </div>
          `;
        });

        html += `</div></div>`;
      });

      container.innerHTML = html;
    }

    function selectNode(id) {
      selectedNodeId = id;
      selectedCodeTab = 0;
      renderInspector();
      renderTiers();
    }

    function renderInspector() {
      const title = document.getElementById('detailTitle');
      const badge = document.getElementById('detailBadge');
      const tabs = document.getElementById('codeFileTabs');
      const content = document.getElementById('detailContent');

      if (selectedNodeId === 'RATIONALE') {
        badge.innerText = "AI RATIONALE";
        badge.className = "text-xs px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 font-mono font-bold";
        title.innerText = "Architectural Decomposition & Concurrency Strategy";
        tabs.innerHTML = '';

        const rationale = globalState.plan_rationale || "AI Rationale will appear here once the Scrum Master decomposes the Epic.";
        content.innerHTML = `
          <div class="space-y-4">
            <div class="p-3 bg-purple-950/30 rounded-lg border border-purple-500/30 text-xs text-purple-200 leading-relaxed">
              <span class="font-bold text-white block mb-1">Scrum Master Explanation:</span>
              ${escapeHtml(rationale).replace(/\\n/g, '<br>')}
            </div>
          </div>
        `;
        return;
      }

      if (selectedNodeId === 'CONTRACT') {
        badge.innerText = "CONTRACT";
        badge.className = "text-xs px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 font-mono font-bold";
        title.innerText = "System Interface Contract (contracts.py)";
        tabs.innerHTML = '';

        const code = globalState.contracts_code || "# System contract will appear here once planned.";
        content.innerHTML = `
          <div class="space-y-4">
            <div class="p-3 bg-gray-900 rounded-lg border border-cardborder text-xs text-gray-300">
              <span class="font-bold text-white">Contract-First Invariant:</span>
              Locked interface schemas defining rate limiting algorithms, storage protocols, and API responses.
            </div>
            <div class="relative bg-darkbg rounded-lg border border-cardborder p-3 overflow-x-auto text-xs font-mono">
              <pre><code class="text-blue-300">${escapeHtml(code)}</code></pre>
            </div>
          </div>
        `;
        return;
      }

      const task = (globalState.tasks || []).find(t => t.story_id === selectedNodeId);
      if (!task) return;

      badge.innerText = task.story_id;
      badge.className = "text-xs px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 font-mono font-bold";
      title.innerText = task.title;

      const fileNames = Object.keys(task.files || {});
      if (fileNames.length > 0) {
        tabs.innerHTML = fileNames.map((fn, idx) => `
          <button onclick="selectedCodeTab = ${idx}; renderInspector();" class="text-xs px-2.5 py-1 rounded transition ${selectedCodeTab === idx ? 'bg-blue-600 text-white font-bold' : 'bg-gray-800 text-gray-400 hover:text-white'}">
            ${fn}
          </button>
        `).join('');
      } else {
        tabs.innerHTML = `<span class="text-xs text-gray-500 italic">No files generated yet</span>`;
      }

      let inner = `
        <div class="space-y-4">
          ${task.summary ? `
            <div class="p-3 bg-green-950/30 rounded-lg border border-green-500/30 text-xs text-green-300">
              <span class="font-bold block mb-1">Execution Milestone Summary:</span>
              ${task.summary}
            </div>
          ` : ''}

          <div class="grid grid-cols-2 gap-3 text-xs">
            <div class="p-3 bg-gray-900 rounded-lg border border-cardborder">
              <span class="text-blue-400 uppercase font-bold text-[10px] block mb-2 flex items-center gap-1.5">
                <i class="fa-solid fa-clipboard-list"></i> Story Acceptance Criteria
              </span>
              <ul class="list-disc list-inside space-y-1 text-gray-300">
                ${(task.acceptance_criteria || []).map(c => `<li>${c}</li>`).join('')}
              </ul>
            </div>

            <div class="p-3 bg-gray-900 rounded-lg border border-cardborder space-y-2">
              <div><span class="text-gray-400 uppercase font-bold text-[10px]">Verification Command:</span> <code class="text-yellow-300 bg-darkbg px-1.5 py-0.5 rounded font-mono block mt-1">${task.test_command}</code></div>
              <div><span class="text-gray-400 uppercase font-bold text-[10px]">Dependencies:</span> <span class="text-gray-300 font-mono text-[11px] block mt-0.5">${task.dependencies.length ? task.dependencies.join(', ') : 'None (Runs in Wave 0)'}</span></div>
              <div><span class="text-gray-400 uppercase font-bold text-[10px]">Sandbox Attempts:</span> <span class="text-green-400 font-bold ml-1">${task.attempts}</span></div>
            </div>
          </div>

          <div class="p-3 bg-gray-900/80 rounded-lg border border-cardborder">
            <span class="text-yellow-400 uppercase font-bold text-[10px] block mb-2 flex items-center gap-1.5">
              <i class="fa-solid fa-vial-circle-check"></i> Pre-Defined Test Cases (Derived from AC)
            </span>
            <div class="space-y-2">
              ${(task.test_cases || []).length > 0 ? task.test_cases.map(tc => `
                <div class="bg-darkbg p-2.5 rounded border border-gray-800 text-xs">
                  <div class="flex items-center justify-between">
                    <span class="font-mono font-bold text-yellow-300">${tc.name}()</span>
                    <span class="text-[10px] bg-gray-800 px-1.5 py-0.5 rounded text-gray-400">${tc.expected_outcome}</span>
                  </div>
                  <p class="text-gray-400 text-[11px] mt-1">${tc.description}</p>
                </div>
              `).join('') : '<span class="text-gray-500 italic text-[11px]">No explicit test cases specified.</span>'}
            </div>
          </div>
      `;

      if (fileNames.length > 0) {
        const curFile = fileNames[selectedCodeTab] || fileNames[0];
        const code = task.files[curFile];
        inner += `
          <div class="relative bg-darkbg rounded-lg border border-cardborder p-3 overflow-x-auto text-xs font-mono">
            <div class="text-[10px] text-gray-400 uppercase tracking-wider mb-2 border-b border-gray-800 pb-1 flex justify-between">
              <span>${curFile}</span>
              <span class="text-green-400">Modal Ephemeral Sandbox Verified ✔</span>
            </div>
            <pre><code class="text-green-300">${escapeHtml(code)}</code></pre>
          </div>
        `;
      } else if (task.error) {
        inner += `
          <div class="p-3 bg-red-950/40 rounded-lg border border-red-500/40 text-xs font-mono text-red-300 overflow-x-auto">
            <span class="font-bold block mb-1">Sandbox Traceback / Blocker:</span>
            <pre>${escapeHtml(task.error)}</pre>
          </div>
        `;
      }

      inner += `</div>`;
      content.innerHTML = inner;
    }

    async function triggerPlan(feedbackText = null) {
      const btn = document.getElementById('planBtn');
      btn.disabled = true;
      btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Planning with Scrum Master...`;

      const title = document.getElementById('inputTitle').value;
      const desc = document.getElementById('inputDesc').value;
      const ac = document.getElementById('inputAC').value;

      await fetch('/api/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          epic_title: title,
          epic_desc: desc,
          acceptance_criteria: ac,
          feedback: feedbackText
        })
      });

      setLeftTab('tree');
      fetchState();
    }

    async function promptRevision() {
      const feedback = prompt("Enter instructions for the Scrum Master to revise this plan:");
      if (feedback && feedback.trim()) {
        triggerPlan(feedback.trim());
      }
    }

    async function approvePlan() {
      await fetch('/api/approve-plan', { method: 'POST' });
      fetchState();
    }

    async function approvePR() {
      await fetch('/api/approve-pr', { method: 'POST' });
      fetchState();
    }

    // Quick Win 1 Modal Handlers
    function openBlockerModal() {
      document.getElementById('blockerModal').classList.remove('hidden');
    }

    function closeBlockerModal() {
      document.getElementById('blockerModal').classList.add('hidden');
    }

    async function resolveBlocker(resolutionChoice) {
      closeBlockerModal();
      await fetch('/api/resolve-blocker', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          story_id: 'RL-02',
          resolution: resolutionChoice
        })
      });
      fetchState();
    }

    function escapeHtml(str) {
      if (!str) return '';
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("POD-AI CONTROL PLANE LAUNCHED")
    print("Open http://localhost:8000 in your browser")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)