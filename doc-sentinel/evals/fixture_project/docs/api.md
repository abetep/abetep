# API Reference

All endpoints are served under `/tasks`.

## Create a task

`POST /tasks` calls `create_task(title, priority=1)`. The `priority`
defaults to 1, the lowest urgency.

## List tasks

`GET /tasks` calls `list_tasks`. Results are filtered by `status`
(default `open`) and capped at `limit=50` tasks per request.

## Get a task

`GET /tasks/{task_id}` calls `get_task`. Pass `include_history=True`
to embed the task's full change history in the response.

## Delete a task

`DELETE /tasks/{task_id}` calls `delete_task` and permanently removes
the task. This cannot be undone.

## Archiving

`POST /tasks/{task_id}/archive` calls `archive_task`, which keeps the
task's history readable instead of destroying it.

## Priority computation

`compute_priority(due_in_days, is_blocking=False)` returns base
priority 10 minus the days until due; blocking tasks score double.
