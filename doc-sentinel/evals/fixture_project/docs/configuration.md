# Configuration

## Settings

`TaskboxSettings` reads environment variables prefixed with `TASKBOX_`.
The default `page_size` is 50 and `database_url` points to a local
SQLite file.

## Retention

Archived tasks are kept for `retention_days` (default 90) before the
`purge` command may remove them.

## Webhooks

Set `enable_webhooks` to true to POST task events to your endpoint.
Webhooks are disabled by default.
