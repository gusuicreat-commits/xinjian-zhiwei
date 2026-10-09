"""Versioned synthetic query contract; collection never confirms a root cause."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = "query-task-v3"
TOOLS = {"query_evidence", "query_package_requirement", "query_approved_cases"}
KINDS = {
    "configuration": ("sensor", {"saved_configuration_comparison"}, {"match", "mismatch"}),
    "led_report": ("led", {"student_report", "independent_observation"}, {"on", "off"}),
    "independent_led_observation": ("led", {"independent_observation"}, {"on", "off"}),
}
# Explicitly synthetic, NOT a course-approved production question directory.
QUESTIONS = {
    "observe_led": ("led", "led_report", "描述已观察到的发光现象；无法观察可答 unclear。"),
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Profile(Strict):
    selection_attempts: int = Field(default=3, ge=0, le=3)
    model_attempts: int = Field(default=5, ge=0, le=5)
    queries: int = Field(default=4, ge=0, le=4)
    questions: int = Field(default=1, ge=0, le=1)
    projection_bytes: int = Field(default=8192, ge=256, le=8192)
    active_seconds: float = Field(default=120.0, gt=0, le=120)
    input_tokens: int = Field(default=10000, gt=0, le=10000)


class TaskScope(Strict):
    task_id: str = Field(min_length=1, max_length=80)
    actor_id: str = Field(min_length=1, max_length=80)
    experiment: Literal["sensor", "led"]
    component: Literal["sensor", "led"]
    session_id: str = Field(min_length=1, max_length=80)
    diagnosis_id: str = Field(min_length=1, max_length=80)
    package_version: str = Field(min_length=1, max_length=80)
    input_revision: int = Field(default=1, ge=1)
    contract_version: Literal["query-task-v3"] = VERSION

    def identity(self):
        return self.model_dump(exclude={"input_revision"})


class Requirement(Strict):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal["configuration", "led_report", "independent_led_observation"]
    tools: list[str] = Field(default_factory=list, max_length=3)
    question: str | None = None
    question_version: Literal["synthetic-v1"] = "synthetic-v1"


class EvidenceRef(Strict):
    id: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=80)
    source_kind: str
    source_revision: int = Field(ge=1)
    requirement_id: str
    scope: dict
    input_revision: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=8000)
    value: str
    is_test_data: Literal[True] = True


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


class TaskContract(Strict):
    scope: TaskScope
    requirements: list[Requirement] = Field(min_length=1, max_length=10)
    profile: Profile = Field(default_factory=Profile)

    @model_validator(mode="after")
    def validate_contract(self):
        if len({r.id for r in self.requirements}) != len(self.requirements):
            raise ValueError("duplicate requirement")
        for req in self.requirements:
            experiment = KINDS[req.kind][0]
            if (self.scope.experiment, self.scope.component) != (experiment, experiment):
                raise ValueError("requirement scope mismatch")
            if set(req.tools) - TOOLS or len(set(req.tools)) != len(req.tools):
                raise ValueError("unlicensed tool")
            if req.question is not None and (
                req.question not in QUESTIONS
                or QUESTIONS[req.question][:2] != (experiment, req.kind)
            ):
                raise ValueError("unlicensed question")
        return self

    def merge(self, existing, incoming, requirement_id=None, revision=None):
        """Validate the ENTIRE batch, including omitted units, before adopting any row."""
        if not isinstance(incoming, list) or len(incoming) > 100:
            raise ValueError("invalid evidence batch")
        revision = revision or self.scope.input_revision
        reqs = {r.id: r for r in self.requirements}
        identities, ids, output = {}, {}, []
        for item in [*existing, *incoming]:
            row = EvidenceRef.model_validate(item).model_dump()
            req = reqs.get(row["requirement_id"])
            if req is None or (
                item in incoming
                and requirement_id is not None
                and row["requirement_id"] != requirement_id
            ):
                raise ValueError("unexpected requirement")
            if row["scope"] != self.scope.identity() or row["input_revision"] > revision:
                raise ValueError("source scope mismatch")
            _, sources, values = KINDS[req.kind]
            if row["source_kind"] not in sources or row["value"] not in values | {"unclear"}:
                raise ValueError("source type or value mismatch")
            canonical = {k: v for k, v in row.items() if k != "id"}
            identity = (row["source_id"], row["source_revision"], row["requirement_id"])
            if row["id"] in ids and ids[row["id"]] != row:
                raise ValueError("evidence ID conflict")
            ids[row["id"]] = row
            if identity in identities:
                if canonical != identities[identity]:
                    raise ValueError("source identity conflict")
                continue
            identities[identity] = canonical
            output.append(row)
        return output

    def view(self, task):
        material, queries, questions, gaps = [], [], [], []
        for req in self.requirements:
            rows = [r for r in task["records"] if r["requirement_id"] == req.id]
            known = {r["value"] for r in rows if r["value"] != "unclear"}
            checked = all(f"{req.id}:{tool}" in task["checked"] for tool in req.tools)
            state = (
                "conflicting"
                if len(known) > 1
                else "present"
                if known
                else "checked_empty"
                if rows or checked
                else "not_checked"
            )
            item = {
                "requirement_id": req.id,
                "state": state,
                "gap_reason": "observation_unknown" if rows and not known else None,
            }
            material.append(item)
            if state == "present":
                continue
            gaps.append(item)
            for tool in req.tools:
                if f"{req.id}:{tool}" not in task["checked"]:
                    queries.append({"kind": "query", "requirement_id": req.id, "tool": tool})
            if checked and req.question and not task["question"]:
                questions.append(
                    {
                        "kind": "ask",
                        "requirement_id": req.id,
                        "question_id": req.question,
                        "question_version": req.question_version,
                    }
                )
        if not gaps:
            actions = [{"kind": "finish_satisfied"}]
        elif queries:
            actions = queries  # All eligible archives before any question.
        elif task["question"] and task["question"]["status"] == "pending":
            actions = []
        elif questions:
            actions = questions
        else:
            actions = [{"kind": "finish_unknown"}]
        return {
            "contract_version": VERSION,
            "material": material,
            "gaps": gaps,
            "eligible_actions": actions,
            "evidence": deepcopy(task["records"]),
            "source_manifest": [
                {
                    "source_id": row["source_id"],
                    "revision": row["source_revision"],
                    "source_kind": row["source_kind"],
                    "unit_sha256": digest(row),
                }
                for row in task["records"]
            ],
            "root_cause": "unconfirmed",
        }


def choose_rule(view):
    return deepcopy(sorted(view["eligible_actions"], key=lambda a: encoded(a))[0])


def project_units(rows, limit):
    selected = set()
    # The serialized omission count is part of the 8 KiB limit. Revisit a
    # skipped unit when later inclusions shrink that count across a digit edge.
    while True:
        changed = False
        for index in range(len(rows)):
            if index in selected:
                continue
            candidate_indices = selected | {index}
            candidate = {
                "rows": [row for i, row in enumerate(rows) if i in candidate_indices],
                "omitted_count": len(rows) - len(candidate_indices),
            }
            if len(encoded(candidate)) <= limit:
                selected.add(index)
                changed = True
        if not changed:
            break
    return {
        "rows": [row for i, row in enumerate(rows) if i in selected],
        "omitted_count": len(rows) - len(selected),
    }
