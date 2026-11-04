import json
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator


class TestCaseSpec(BaseModel):
    name: str = Field(default="test_case")
    description: str = Field(default="")
    expected_outcome: str = Field(default="")


class TaskNode(BaseModel):
    story_id: str = Field(default="STORY-101")
    title: str = Field(default="Task")
    description: str = Field(default="")
    dependencies: list[str] = Field(default_factory=list)
    owned_files: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    test_cases: list[TestCaseSpec] = Field(default_factory=list)  # <-- Added
    test_command: str = Field(default="pytest")

    @field_validator(
        "dependencies", "owned_files", "acceptance_criteria", mode="before"
    )
    @classmethod
    def normalize_list(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(item) for item in v if item]
        if isinstance(v, str):
            cleaned = v.strip()
            return (
                []
                if not cleaned or cleaned.lower() in ("none", "null", "[]")
                else [cleaned]
            )
        return []

    @field_validator("test_cases", mode="before")
    @classmethod
    def normalize_test_cases(cls, v: Any) -> list[Any]:
        if isinstance(v, list):
            normalized = []
            for item in v:
                if isinstance(item, dict):
                    normalized.append(item)
                elif isinstance(item, str):
                    normalized.append({
                        "name": item,
                        "description": item,
                        "expected_outcome": "PASS",
                    })
            return normalized
        return []


class ArchitecturePlan(BaseModel):
    contracts_code: str = ""
    contract_file_path: str = "contracts.py"
    plan_rationale: str = ""  # <-- Added
    tasks: list[TaskNode] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def harmonize_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize common model key variations
            if "tasks" not in data:
                for alt in ("stories", "user_stories", "task_nodes", "subtasks"):
                    if alt in data:
                        data["tasks"] = data[alt]
                        break
            if "contracts_code" not in data:
                for alt in (
                    "contract_code",
                    "contract",
                    "contracts",
                    "interfaces",
                    "types",
                ):
                    if alt in data:
                        data["contracts_code"] = data[alt]
                        break
            if "plan_rationale" not in data:
                for alt in (
                    "rationale",
                    "architecture_rationale",
                    "design_rationale",
                    "reasoning",
                ):
                    if alt in data:
                        data["plan_rationale"] = data[alt]
                        break
        return data


class WorkerOutput(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)
    implementation_notes: str = ""

    @field_validator("files", mode="before")
    @classmethod
    def normalize_files(cls, v: Any) -> dict[str, str]:
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items()}
        if isinstance(v, list):
            res = {}
            for item in v:
                if isinstance(item, dict):
                    path = item.get("path") or item.get("file") or item.get("filename")
                    content = item.get("content") or item.get("code") or ""
                    if path:
                        res[str(path)] = str(content)
            return res
        return {}