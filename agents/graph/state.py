from __future__ import annotations

from typing import TypedDict


class NexusState(TypedDict):
    job_id: str
    jira_issue: str
    description: str
    analyst_output: dict
    developer_output: dict
    designer_output: dict
    reviewer_output: dict
    current_agent: str
    status: str
    approval_required: bool
    approval_type: str
    error: str | None
