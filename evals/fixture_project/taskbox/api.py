from fastapi import FastAPI
from taskbox.service import archive_task

app = FastAPI()


@app.post("/tasks")
def create_task(title: str, priority: int = 1) -> dict:
    """Create a new task.

    priority defaults to 1 (lowest). Higher numbers are more urgent.
    """
    return {"title": title, "priority": priority}


@app.get("/tasks")
def list_tasks(status: str = "open", limit: int = 50) -> list:
    """List tasks filtered by status. Returns at most `limit` tasks (default 50)."""
    return []


@app.get("/tasks/{task_id}")
def get_task(task_id: int, include_history: bool = False) -> dict:
    """Fetch a single task. include_history embeds the full change history."""
    return {"id": task_id, "history": [] if include_history else None}


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int) -> dict:
    """Permanently delete a task."""
    return {"deleted": task_id}


@app.post("/tasks/{task_id}/archive")
def archive_endpoint(task_id: int) -> dict:
    """Archive a task instead of deleting it."""
    return archive_task(task_id)
