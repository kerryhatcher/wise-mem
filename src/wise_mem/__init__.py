import typer
from loguru import logger

from .api import HealthResponse

cli = typer.Typer(help="wise-mem command-line interface")


@cli.command()
def health() -> None:
    logger.info("CLI health command called")
    typer.echo(HealthResponse().model_dump_json())


def main() -> None:
    cli()
