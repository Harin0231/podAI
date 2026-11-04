# orchestrator.py
import concurrent.futures
from typing import Any, Dict, List, Set
from schemas import ArchitecturePlan, TaskNode
from sandbox_runner import sandbox_session
from worker_loop import execute_worker_task


def clean_id(raw_id: str) -> str:
    return raw_id.strip("[] \t\n\r").upper()


def compute_execution_tiers(tasks: List[TaskNode]) -> List[List[TaskNode]]:
    """Computes dependency execution tiers using Kahn's algorithm with ID normalization."""
    # 1. Normalize story_id and clean dependency lists
    for t in tasks:
        t.story_id = clean_id(t.story_id)
        t.dependencies = [
            clean_id(dep)
            for dep in t.dependencies
            if clean_id(dep) and clean_id(dep) not in ("NONE", "NULL", "EMPTY")
        ]

    # 2. Prune any dependencies pointing to non-existent tasks
    valid_ids = {t.story_id for t in tasks}
    for t in tasks:
        t.dependencies = [dep for dep in t.dependencies if dep in valid_ids]

    completed_ids: Set[str] = set()
    remaining = list(tasks)
    tiers: List[List[TaskNode]] = []

    while remaining:
        current_tier = [
            task
            for task in remaining
            if all(dep in completed_ids for dep in task.dependencies)
        ]

        if not current_tier:
            stuck = [
                f"{t.story_id} (waiting for {set(t.dependencies) - completed_ids})"
                for t in remaining
            ]
            raise ValueError(f"DAG Deadlock detected! Stuck tasks: {stuck}")

        tiers.append(current_tier)
        for task in current_tier:
            completed_ids.add(task.story_id)

        remaining = [t for t in remaining if t not in current_tier]

    return tiers


def run_pod_orchestration(
    plan: ArchitecturePlan, backend: str = "modal"
) -> Dict[str, Any]:
    locked_contract = plan.contracts_code
    shared_workspace: Dict[str, str] = {"contracts.py": locked_contract}

    tiers = compute_execution_tiers(plan.tasks)
    print("\n" + "=" * 60)
    print(
        f"POD-AI ORCHESTRATION PIPELINE: {len(plan.tasks)} Tasks across"
        f" {len(tiers)} Tiers"
    )
    print("=" * 60)

    # Boot Modal session once for the entire pipeline
    with sandbox_session(backend=backend):
        for idx, tier in enumerate(tiers):
            tier_names = [f"[{t.story_id}] {t.title}" for t in tier]
            print(f"\n>>> EXECUTING TIER {idx} ({len(tier)} tasks in parallel):")
            for name in tier_names:
                print(f"    - {name}")

            tier_results = []
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(tier)
            ) as executor:
                futures = {
                    executor.submit(
                        execute_worker_task,
                        task=task,
                        locked_contract=locked_contract,
                        shared_workspace=shared_workspace,
                        backend=backend,
                    ): task
                    for task in tier
                }

                for future in concurrent.futures.as_completed(futures):
                    task = futures[future]
                    try:
                        res = future.result()
                        tier_results.append(res)
                    except Exception as e:
                        tier_results.append({
                            "story_id": task.story_id,
                            "status": "FAILED",
                            "error": str(e),
                            "files": {},
                        })

            failures = [r for r in tier_results if r["status"] != "PASSED"]
            if failures:
                print(
                    f"\n[ORCHESTRATOR PAUSED] Tier {idx} encountered"
                    " failures/blockers:"
                )
                for f in failures:
                    print(
                        f"  - Task {f['story_id']}:"
                        f" {f.get('error') or 'Exhausted retries'}"
                    )
                return {
                    "success": False,
                    "completed_tasks": [
                        r["story_id"]
                        for r in tier_results
                        if r["status"] == "PASSED"
                    ],
                    "blocked_task": failures[0],
                    "workspace": shared_workspace,
                }

            for res in tier_results:
                shared_workspace.update(res["files"])
                print(
                    f"  + Merged {len(res['files'])} verified files from"
                    f" {res['story_id']}"
                )

    print("\n" + "=" * 60)
    print("ALL TIERS PASSED VERIFICATION GREEN!")
    print(f"Total Workspace Files Generated: {len(shared_workspace)}")
    print("=" * 60)

    return {
        "success": True,
        "completed_tasks": [t.story_id for t in plan.tasks],
        "blocked_task": None,
        "workspace": shared_workspace,
    }