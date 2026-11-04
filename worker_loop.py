# worker_loop.py
from typing import Dict, Any, Optional
from schemas import TaskNode, WorkerOutput
from personas import run_worker_agent
from sandbox_runner import run_sandbox_verification

MAX_RETRIES = 3

def execute_worker_task(
    task: TaskNode,
    locked_contract: str,
    contract_path: str = "contracts.py",
    shared_workspace: Optional[Dict[str, str]] = None,
    backend: str = "modal",
) -> Dict[str, Any]:
    """
    Executes a single worker task with an automated self-repair loop:
    1. Worker generates code and unit tests.
    2. Modal mounts accumulated repo files + new task files.
    3. Modal runs task.test_command.
    4. If failed, feeds stderr/stdout traceback back to worker for auto-repair.
    5. Returns final status, code artifacts, and attempt count.
    """
    workspace = dict(shared_workspace or {})
    workspace[contract_path] = locked_contract

    error_context: Optional[str] = None
    attempt = 1

    print(f"\n{'='*60}")
    print(f"DISPATCHING WORKER: [{task.story_id}] {task.title}")
    print(f"Target Files: {task.owned_files}")
    print(f"Verification: {task.test_command}")
    print(f"{'='*60}")

    last_output: Optional[WorkerOutput] = None

    while attempt <= MAX_RETRIES:
        print(f"\n--> Attempt {attempt}/{MAX_RETRIES} generating code via Meta Muse...")
        
        # 1. Generate code & test suite
        try:
            worker_output = run_worker_agent(
                task=task,
                locked_contract=locked_contract,
                contract_path=contract_path,
                error_context=error_context
            )
            last_output = worker_output
        except Exception as e:
            print(f"[ERROR] Worker generation failed: {e}")
            error_context = f"Internal generation exception: {str(e)}"
            attempt += 1
            continue

        # 2. Assemble test sandbox payload (accumulated workspace + new files)
        sandbox_payload = dict(workspace)
        sandbox_payload.update(worker_output.files)

        print(f"--> Running '{task.test_command}' inside Modal container...")
        sandbox_res = run_sandbox_verification(
            files=sandbox_payload,
            test_command=task.test_command,
            backend=backend
        )

        # 3. Evaluate results
        if sandbox_res["passed"]:
            print(f"--> [PASS] Task {task.story_id} verified green on attempt {attempt}!")
            return {
                "story_id": task.story_id,
                "status": "PASSED",
                "attempts": attempt,
                "files": worker_output.files,
                "error": None
            }

        # 4. Extract failure traceback for targeted self-repair
        print(f"--> [FAIL] Attempt {attempt} failed (Exit Code: {sandbox_res['exit_code']}).")
        raw_error = sandbox_res["stderr"] or sandbox_res["stdout"]
        
        # Trim noisy logs to the most actionable traceback snippet
        error_context = raw_error[-2000:] if len(raw_error) > 2000 else raw_error
        print(f"Traceback captured ({len(error_context)} chars). Triggering self-repair prompt...")

        attempt += 1

    # If retries exhausted, signal blocker for human escalation
    return {
        "story_id": task.story_id,
        "status": "BLOCKED",
        "attempts": attempt - 1,
        "files": last_output.files if last_output else {},
        "error": error_context
    }