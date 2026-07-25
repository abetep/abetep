from pydantic_settings import BaseSettings


class TaskboxSettings(BaseSettings):
    """Configuration read from environment variables prefixed with TASKBOX_."""

    database_url: str = "sqlite:///taskbox.db"
    page_size: int = 50
    retention_days: int = 90
    enable_webhooks: bool = False
