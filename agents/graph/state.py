from typing import TypedDict, Annotated
import operator


class NexusState(TypedDict):
    job_id: Annotated[str, lambda x, y: y if y else x]
    jira_issue: Annotated[str, lambda x, y: y if y else x]
    description: Annotated[str, lambda x, y: y if y else x]
    analyst_output: Annotated[dict, lambda x, y: {**x, **y}]
    developer_output: Annotated[dict, lambda x, y: {**x, **y}]
    designer_output: Annotated[dict, lambda x, y: {**x, **y}]
    reviewer_output: Annotated[dict, lambda x, y: {**x, **y}]
    current_agent: Annotated[str, lambda x, y: y if y else x]
    status: Annotated[str, lambda x, y: y if y else x]
    approval_required: Annotated[bool, lambda x, y: x or y]
    approval_type: Annotated[str, lambda x, y: y if y else x]
    error: Annotated[str | None, lambda x, y: y if y else x]
    phase: Annotated[str, lambda x, y: y if y else x]
