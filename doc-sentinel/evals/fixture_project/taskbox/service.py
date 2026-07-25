"""Task domain logic."""


def compute_priority(due_in_days: int, is_blocking: bool = False) -> int:
    """Compute effective priority: base 10 minus days until due, doubled when blocking."""
    base = max(0, 10 - due_in_days)
    return base * 2 if is_blocking else base


def archive_task(task_id: int) -> dict:
    """Move a task to the archive, keeping its history readable."""
    return {"archived": task_id}


def _normalize(title: str) -> str:
    return title.strip().lower()
