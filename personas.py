import json
import os
import re
from typing import Type, TypeVar
from openai import OpenAI
from pydantic import BaseModel
from schemas import ArchitecturePlan, TaskNode, WorkerOutput

API_KEY = os.getenv("MODEL_API_KEY") or os.getenv("META_API_KEY")
if not API_KEY:
    raise ValueError(
        "Missing API key. Set MODEL_API_KEY in your environment before running."
    )

client = OpenAI(
    base_url=os.getenv("META_API_BASE_URL", "https://api.meta.ai/v1"),
    api_key=API_KEY,
)

MODEL_NAME = os.getenv("META_MODEL", "muse-spark-1.3")
T = TypeVar("T", bound=BaseModel)


def _repair_json_string(text: str) -> str:
    """Repairs common LLM JSON defects (unescaped backslashes, trailing commas)."""
    # Remove thought blocks
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    # Find the JSON boundaries
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    # Remove trailing commas before closing braces/brackets
    text = re.sub(r",\s*([\]}])", r"\1", text)
    return text


def _extract_and_parse_json(raw_text: str, target_cls: Type[T]) -> T:
    """Extracts and parses JSON with robust fallback repairs."""
    if not raw_text or not raw_text.strip():
        raise ValueError("API returned empty response.")

    cleaned = _repair_json_string(raw_text)

    # Attempt 1: Direct parse
    try:
        data = json.loads(cleaned, strict=False)
        return target_cls.model_validate(data)
    except Exception:
        pass

    # Attempt 2: Sanitize rogue single backslashes common in regex/docstrings
    try:
        sanitized = re.sub(r'\\(?![/"\\bfnrtu]|u[0-9a-fA-F]{4})', r"\\\\", cleaned)
        data = json.loads(sanitized, strict=False)
        return target_cls.model_validate(data)
    except Exception:
        pass

    # Attempt 3: Fix unescaped control newlines inside multiline string values
    try:
        sanitized = re.sub(
            r'("(?:[^"\\]|\\.)*")',
            lambda m: m.group(0).replace("\n", "\\n").replace("\r", "\\r"),
            cleaned,
            flags=re.DOTALL,
        )
        data = json.loads(sanitized, strict=False)
        return target_cls.model_validate(data)
    except Exception as final_err:
        raise ValueError(
            f"Failed to parse LLM response into {target_cls.__name__}: {final_err}\n"
            f"Snippet around error: {cleaned[max(0, len(cleaned)-300):]}"
        )


# ============================================================================
# 1. SCRUM MASTER / LEAD ARCHITECT (Meta Muse Wonder)
# ============================================================================


def run_scrum_master(spec: str) -> ArchitecturePlan:
    """Invokes Meta Muse Wonder to dynamically design rate limiter architecture,
    lock contracts, and decompose tasks with explicit test case specifications.
    """
    developer_prompt = """You are the Lead Systems Architect & Scrum Master of PodAI.
Your goal is to inspect the incoming Rate Limiter Epic specification, lock the interface
contracts in executable Python code, provide architectural rationale, and dynamically decompose
the feature into an executable task DAG with explicit test case specifications.

Return a single valid JSON object strictly conforming to ArchitecturePlan.

IMPORTANT JSON SAFETY RULES:
- `contracts_code` must be a clean, valid JSON string: use standard '\\n' escapes for newlines.
- Avoid raw triple-double-quotes inside code strings; use regular single quotes or standard docstrings.

ARCHITECTURAL PRINCIPLES:
1. CONTRACT-FIRST DESIGN (Field: contracts_code):
   - You MUST write complete, valid Python code in `contracts_code`.
   - Define all shared Pydantic models, Abstract Base Classes, configuration schemas,
     and response types (e.g. BaseRateLimiter, BaseStorage, RateLimitStatus, MetricsResponse).
   - Downstream workers run in isolated sandboxes and compile against this contract.
   - This field must NEVER be empty.

2. ARCHITECTURAL RATIONALE (Field: plan_rationale):
   - Explain WHY you structured the system this way.
   - Justify your DAG concurrency topology (Wave 0 independent tasks vs. subsequent integration waves).
   - Detail thread-safety guarantees and algorithm/storage trade-offs.

3. DYNAMIC TASK DECOMPOSITION (Field: tasks):
   Decompose the solution into 3 to 5 modular tasks:
   - story_id: Short alphanumeric identifier prefixed with 'RL-' (e.g. 'RL-01', 'RL-02'). No brackets.
   - title: Specific component-level title.
   - description: Clear requirements for this unit of work.
   - owned_files: Explicit list of files. Code must be under `app/`, tests under `tests/`.
     * Each task must own its implementation file and dedicated test file.
     * `contracts.py` is locked by you and must NEVER be placed in `owned_files`.
   - dependencies: List story_ids that MUST pass before this task can run. Independent foundation tasks use [].
   - acceptance_criteria: 3 to 5 bulleted functional criteria.
   - test_cases: 2 to 4 explicit test specifications (each with `name`, `description`, `expected_outcome`).
   - test_command: Complete pytest command (e.g. 'pytest tests/test_bucket.py -v'). No filter flags ('::').

RELIABILITY GUIDELINES:
- For time-sensitive calculations, use `time.monotonic()`.
- For float assertions, use `pytest.approx()`.
- Return valid JSON only.
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        response_format={"type": "json_object"},
        messages=[
            {"role": "developer", "content": developer_prompt},
            {
                "role": "user",
                "content": (
                    "Analyze this rate limiter specification. Lock contracts.py, "
                    "provide architectural rationale, and autonomously decompose into "
                    f"a parallel task DAG with pre-defined test cases:\n\n{spec}"
                ),
            },
        ],
        max_completion_tokens=8192,  # Increased from 4096 to prevent truncation
        extra_body={"reasoning_effort": "low"},
        temperature=0.0,
    )

    raw_json = response.choices[0].message.content
    return _extract_and_parse_json(raw_json, ArchitecturePlan)


# ============================================================================
# 2. WORKER AGENT / PEER DEVELOPER (Meta Muse Spark)
# ============================================================================


def run_worker_agent(
    task: TaskNode,
    locked_contract: str,
    contract_path: str = "contracts.py",
    error_context: str | None = None,
) -> WorkerOutput:
    """Invokes Meta Muse Spark to generate complete implementations and test files."""
    test_cases_block = ""
    if getattr(task, "test_cases", None):
        test_cases_block = (
            "\nMANDATORY TEST CASES TO IMPLEMENT IN "
            f"{task.owned_files[-1] if task.owned_files else 'tests/'}:\n"
            + "\n".join(
                f"- def {tc.name}(): {tc.description} (Expected: {tc.expected_outcome})"
                for tc in task.test_cases
            )
        )

    developer_prompt = f"""You are an expert Python Backend Engineer in PodAI.
Your task is to implement the code and test suite for: [{task.story_id}] {task.title}
Target Files: {task.owned_files}

Acceptance Criteria:
{chr(10).join(f'- {c}' for c in task.acceptance_criteria)}
{test_cases_block}

MANDATORY RULES:
1. Write complete, production-ready, valid Python code for all files in {task.owned_files}.
2. Ensure the test file implements and passes all specified test cases.
3. NEVER truncate files, use placeholders (like `# TODO` or `...`), or leave unclosed parentheses, strings, or brackets. Every block must be fully closed and executable.
4. Import shared schemas correctly from `{contract_path}` and other upstream modules.
5. In time-sensitive classes and tests, use time.monotonic() and robust assertions (e.g. pytest.approx).
6. Output your response as a valid JSON object matching WorkerOutput:
   {{
     "files": {{
       "{task.owned_files[0] if task.owned_files else 'app/file.py'}": "<complete code>",
       "{task.owned_files[-1] if len(task.owned_files) > 1 else 'tests/test_file.py'}": "<complete test code>"
     }},
     "implementation_notes": "Implemented components and passing test suite"
   }}
"""

    user_msg = f"Locked Contract:\n{locked_contract}\n\n"
    if error_context:
        user_msg += (
            "PREVIOUS ATTEMPT FAILED WITH TRACEBACK:\n"
            f"{error_context}\n"
            "Please fix the syntax/logic error.\n"
        )
    else:
        user_msg += "Implement the assigned files and test cases now."

    response = client.chat.completions.create(
        model=MODEL_NAME,
        response_format={"type": "json_object"},
        messages=[
            {"role": "developer", "content": developer_prompt},
            {"role": "user", "content": user_msg},
        ],
        max_completion_tokens=8192,
        extra_body={"reasoning_effort": "low"},
        temperature=0.0,
    )

    raw_json = response.choices[0].message.content
    return _extract_and_parse_json(raw_json, WorkerOutput)