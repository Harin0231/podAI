# run_pipeline.py
import time
from personas import run_scrum_master
from orchestrator import run_pod_orchestration

SPEC = """
Build an in-memory rate limiter API in Python using FastAPI with the token bucket algorithm.
Requirements:
1. Core token bucket algorithm that supports configurable capacity and refill rate.
2. In-memory storage for tracking rate limits per client IP address.
3. FastAPI middleware that intercepts incoming requests, returns HTTP 429 Too Many Requests with a Retry-After header when rate limited.
4. An endpoint /metrics that reports total requests, accepted requests, and rate-limited requests.
5. High test coverage with pytest.
"""

if __name__ == "__main__":
    start_time = time.time()

    # 1. Meta Muse Wonder: System Architect & Scrum Master
    print("Step 1: Scrum Master analyzing spec & locking contracts...")
    plan = run_scrum_master(SPEC)

    print(f"Scrum Master generated contract ({len(plan.contracts_code)} chars)")
    print(f"Scrum Master decomposed {len(plan.tasks)} tasks.")

    # 2. Parallel Orchestration across Modal sandboxes
    result = run_pod_orchestration(plan, backend="modal")

    elapsed = time.time() - start_time
    print(f"\nPipeline finished in {elapsed:.1f} seconds. Status: {'SUCCESS' if result['success'] else 'FAILED'}")