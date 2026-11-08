"""The `bonneaffaire` command: a thin adapter over the core."""

import asyncio
from collections.abc import Callable
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import DEFAULT_LIMIT, SearchQuery, SearchRequest, SearchResult
from bonneaffaire.providers import ProviderError
from bonneaffaire.registry import default_core


def make_app(core_factory: Callable[[], Bonneaffaire] = default_core) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, add_completion=False)

    @app.callback()
    def main() -> None:
        """Search second-hand and retail marketplaces in one place."""

    @app.command()
    def search(
        keywords: Annotated[list[str], typer.Argument(help="What to look for.")],
        limit: Annotated[
            int, typer.Option(min=1, help="Maximum Listings per Provider.")
        ] = DEFAULT_LIMIT,
        as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    ) -> None:
        """Search for Listings."""
        request = SearchRequest(query=SearchQuery(keywords=" ".join(keywords)), limit=limit)
        try:
            result = asyncio.run(core_factory().search(request))
        except ProviderError as exc:
            typer.echo(f"Search failed: {exc}", err=True)
            raise typer.Exit(1) from exc
        if as_json:
            typer.echo(result.model_dump_json(indent=2))
        else:
            print_table(result)

    return app


def print_table(result: SearchResult) -> None:
    table = Table("Provider", "Price", "Condition", "Seller kind", "Title", "URL")
    for listing in result.listings:
        table.add_row(
            listing.provider,
            str(listing.price),
            listing.condition,
            listing.seller_kind,
            listing.title,
            listing.url,
        )
    console = Console()
    console.print(table)
    for outcome in result.outcomes:
        console.print(f"{outcome.provider}: {outcome.status} ({outcome.listing_count} Listings)")


def main() -> None:
    make_app()()
