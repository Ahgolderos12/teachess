"""Command-line entry point."""

from typing import Annotated

import typer

from teachess import __version__

app = typer.Typer(
    help="Teachess: entrenador de ajedrez que aprende del jugador.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Muestra la versión."
        ),
    ] = False,
) -> None:
    """Teachess: entrenador de ajedrez que aprende del jugador."""
