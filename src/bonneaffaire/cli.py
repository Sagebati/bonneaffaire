"""The `bonneaffaire` command: a thin adapter over the core."""

import asyncio
from collections.abc import Callable
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import (
    DEFAULT_LIMIT,
    ListingDetails,
    ListingRequest,
    ListingStatus,
    SearchQuery,
    SearchRequest,
    SearchResult,
)
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

    @app.command()
    def listing(
        target: Annotated[str, typer.Argument(help="A Listing URL, or a Provider name.")],
        provider_id: Annotated[
            str | None, typer.Argument(help="The Provider ID, when TARGET is a Provider.")
        ] = None,
        as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    ) -> None:
        """Get one Listing's full details."""
        if target.startswith(("http://", "https://")):
            request = ListingRequest(url=target)
        elif provider_id is None:
            raise typer.BadParameter("give a Provider ID after the Provider name")
        else:
            request = ListingRequest(provider=target, provider_id=provider_id)
        result = asyncio.run(core_factory().get_listing(request))
        if as_json:
            typer.echo(result.model_dump_json(indent=2))
        elif result.listing is not None:
            print_details(result.listing)
        if result.status != ListingStatus.OK:
            reason = "Listing not found" if result.status == ListingStatus.NOT_FOUND else "Failed"
            typer.echo(f"{reason} ({result.status}): {result.message}", err=True)
            raise typer.Exit(1)

    return app


def print_details(details: ListingDetails) -> None:
    table = Table(show_header=False, box=None)
    rows = {
        "Provider": f"{details.provider} {details.provider_id}",
        "Title": details.title,
        "URL": details.url,
        "Price": str(details.price),
        "Condition": f"{details.condition} ({details.condition_label or '-'})",
        "Seller": f"{details.seller.name if details.seller else '-'} ({details.seller_kind})",
        "Availability": details.availability or "-",
        "Description": details.description or "-",
        "Photos": "\n".join(details.photos) or "-",
        **{key: str(value) for key, value in details.attributes.items()},
    }
    for key, value in rows.items():
        table.add_row(key, value)
    Console().print(table)


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
