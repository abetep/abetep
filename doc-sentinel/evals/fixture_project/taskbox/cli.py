import click


@click.command()
@click.option("--format", "fmt", default="json", help="Output format")
def export(fmt: str) -> None:
    """Export all tasks to stdout in the chosen format (default json)."""
    click.echo(f"exporting as {fmt}")


@click.command()
@click.option("--days", default=30, help="Purge tasks older than this many days")
def purge(days: int) -> None:
    """Delete archived tasks older than the cutoff."""
    click.echo(f"purging older than {days} days")
