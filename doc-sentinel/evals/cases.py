"""Labeled evaluation cases: deliberate code changes with ground-truth stale sections.

Each case mutates the fixture project and declares exactly which doc sections
(by heading path) become stale. An empty expectation means the change must NOT
implicate any documentation (false-positive probes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Mutation:
    file: str
    old: str
    new: str

    def apply(self, root: Path) -> None:
        path = root / self.file
        text = path.read_text()
        if self.old not in text:
            raise RuntimeError(f"Mutation drift: {self.old!r} not found in {self.file}")
        path.write_text(text.replace(self.old, self.new))


@dataclass
class EvalCase:
    name: str
    description: str
    mutations: list[Mutation]
    expected_stale: set[str] = field(default_factory=set)


DELETE_TASK_BLOCK = '''\
@app.delete("/tasks/{task_id}")
def delete_task(task_id: int) -> dict:
    """Permanently delete a task."""
    return {"deleted": task_id}


'''

UPDATE_TASK_BLOCK = '''\


@app.patch("/tasks/{task_id}")
def update_task(task_id: int, title: str | None = None) -> dict:
    """Update a task's title."""
    return {"id": task_id, "title": title}
'''

CASES: list[EvalCase] = [
    EvalCase(
        name="rename-param",
        description="get_task's include_history renamed to with_history",
        mutations=[Mutation("taskbox/api.py", "include_history", "with_history")],
        expected_stale={"API Reference > Get a task"},
    ),
    EvalCase(
        name="change-default-limit",
        description="list_tasks default limit 50 -> 100",
        mutations=[Mutation("taskbox/api.py", "limit: int = 50", "limit: int = 100")],
        expected_stale={"API Reference > List tasks"},
    ),
    EvalCase(
        name="change-default-page-size",
        description="TaskboxSettings.page_size 50 -> 25",
        mutations=[Mutation("taskbox/config.py", "page_size: int = 50", "page_size: int = 25")],
        expected_stale={"Configuration > Settings"},
    ),
    EvalCase(
        name="remove-endpoint",
        description="delete_task endpoint removed entirely",
        mutations=[Mutation("taskbox/api.py", DELETE_TASK_BLOCK, "")],
        expected_stale={"API Reference > Delete a task"},
    ),
    EvalCase(
        name="add-endpoint",
        description="new update_task endpoint added; docs never mentioned it",
        mutations=[
            Mutation(
                "taskbox/api.py",
                "    return archive_task(task_id)\n",
                "    return archive_task(task_id)\n" + UPDATE_TASK_BLOCK,
            )
        ],
        expected_stale=set(),
    ),
    EvalCase(
        name="cosmetic-docstring",
        description="docstring rewording and a new comment; behavior identical",
        mutations=[
            Mutation(
                "taskbox/service.py",
                '"""Move a task to the archive, keeping its history readable."""',
                '"""Archive a task while keeping its history readable."""\n    # tombstone',
            )
        ],
        expected_stale=set(),
    ),
    EvalCase(
        name="behavior-change-priority",
        description="compute_priority doubling changed to tripling for blocking tasks",
        mutations=[
            Mutation("taskbox/service.py", "base * 2 if is_blocking", "base * 3 if is_blocking")
        ],
        expected_stale={"API Reference > Priority computation"},
    ),
    EvalCase(
        name="rename-cli-option",
        description="export --format renamed to --output-format",
        mutations=[Mutation("taskbox/cli.py", '"--format"', '"--output-format"')],
        expected_stale={"CLI > Export"},
    ),
    EvalCase(
        name="change-retention-default",
        description="TaskboxSettings.retention_days 90 -> 30",
        mutations=[
            Mutation("taskbox/config.py", "retention_days: int = 90", "retention_days: int = 30")
        ],
        expected_stale={"Configuration > Retention"},
    ),
    EvalCase(
        name="rename-function",
        description="archive_task renamed to archive",
        mutations=[
            Mutation("taskbox/service.py", "def archive_task(", "def archive("),
            Mutation(
                "taskbox/api.py",
                "from taskbox.service import archive_task",
                "from taskbox.service import archive",
            ),
            Mutation("taskbox/api.py", "return archive_task(task_id)", "return archive(task_id)"),
        ],
        expected_stale={"API Reference > Archiving"},
    ),
    EvalCase(
        name="require-description",
        description="create_task grows a required description parameter",
        mutations=[
            Mutation(
                "taskbox/api.py",
                "def create_task(title: str, priority: int = 1)",
                "def create_task(title: str, description: str, priority: int = 1)",
            )
        ],
        expected_stale={"API Reference > Create a task"},
    ),
    EvalCase(
        name="rename-private-helper",
        description="internal _normalize helper renamed; nothing documented",
        mutations=[Mutation("taskbox/service.py", "_normalize", "_norm")],
        expected_stale=set(),
    ),
    EvalCase(
        name="remove-webhooks-setting",
        description="enable_webhooks setting deleted",
        mutations=[Mutation("taskbox/config.py", "    enable_webhooks: bool = False\n", "")],
        expected_stale={"Configuration > Webhooks"},
    ),
]
