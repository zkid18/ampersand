"""CLI entry point for Ampersand."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from ampersand import __version__
from ampersand.converter import save_markdown, to_markdown
from ampersand.extractor import extract_article, is_youtube_url
from ampersand.youtube import extract_youtube

app = typer.Typer(
    name="ampersand",
    help="Capture anything from the web as markdown you own.",
    add_completion=False,
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ampersand {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Ampersand — capture anything from the web as markdown you own."""


@app.command()
def capture(
    url: str = typer.Argument(help="URL to capture."),
    output: Path = typer.Option(
        Path("."),
        "--output",
        "-o",
        help="Output directory for the .md file.",
    ),
    filename: str | None = typer.Option(
        None,
        "--filename",
        "-f",
        help="Custom filename (without extension).",
    ),
    stdout: bool = typer.Option(
        False,
        "--stdout",
        help="Print markdown to stdout instead of saving a file.",
    ),
) -> None:
    """Capture a URL and save it as a markdown file."""
    try:
        if is_youtube_url(url):
            typer.echo(f"Extracting YouTube video...", err=True)
            content = extract_youtube(url)
        else:
            typer.echo(f"Extracting article...", err=True)
            content = extract_article(url)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    if stdout:
        typer.echo(to_markdown(content))
    else:
        filepath = save_markdown(content, output, filename)
        typer.echo(f"Saved: {filepath}", err=True)
