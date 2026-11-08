"""The `bonneaffaire` command: a thin adapter over the core."""

import asyncio
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import (
    DEFAULT_LIMIT,
    Condition,
    FilterReport,
    Location,
    Money,
    SearchQuery,
    SearchRequest,
    SearchResult,
    Sort,
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
        min_price: Annotated[
            str | None, typer.Option(help="Minimum Price in euros, e.g. 99.90.")
        ] = None,
        max_price: Annotated[
            str | None, typer.Option(help="Maximum Price in euros, e.g. 450.")
        ] = None,
        condition: Annotated[
            list[Condition] | None,
            typer.Option(help="Accepted Condition; repeat for several."),
        ] = None,
        near: Annotated[
            str | None, typer.Option(help="Search around this place (city or postcode).")
        ] = None,
        radius_km: Annotated[
            int | None, typer.Option(min=1, help="Radius around --near, in km.")
        ] = None,
        sort: Annotated[Sort | None, typer.Option(help="Order of the merged Listings.")] = None,
        extra: Annotated[
            list[str] | None,
            typer.Option(help="Provider-specific extra as provider.name=value; repeatable."),
        ] = None,
        as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    ) -> None:
        """Search for Listings."""
        if radius_km is not None and near is None:
            raise typer.BadParameter("needs --near", param_hint="--radius-km")
        query = SearchQuery(
            keywords=" ".join(keywords),
            price_min=parse_euros(min_price, "--min-price"),
            price_max=parse_euros(max_price, "--max-price"),
            conditions=frozenset(condition or ()),
            location=Location(place=near, radius_km=radius_km) if near else None,
            sort=sort,
            extras=parse_extras(extra or []),
        )
        request = SearchRequest(query=query, limit=limit)
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


def parse_euros(text: str | None, option: str) -> Money | None:
    if text is None:
        return None
    try:
        amount = Decimal(text.replace(",", "."))
    except InvalidOperation:
        raise typer.BadParameter(f"not an amount: {text!r}", param_hint=option) from None
    if amount < 0:
        raise typer.BadParameter("must not be negative", param_hint=option)
    return Money(cents=int((amount * 100).to_integral_value()), currency="EUR")


def parse_extras(values: list[str]) -> dict[str, dict[str, str]]:
    extras: dict[str, dict[str, str]] = {}
    for value in values:
        target, equals, setting = value.partition("=")
        provider, dot, name = target.partition(".")
        if not (equals and dot and provider and name):
            raise typer.BadParameter(f"{value!r} is not provider.name=value", param_hint="--extra")
        extras.setdefault(provider, {})[name] = setting
    return extras


def describe_filters(report: FilterReport) -> str | None:
    parts = [
        f"{label} {', '.join(names)}"
        for label, names in (
            ("native", report.native),
            ("local", report.local),
            ("not applied", report.unapplied),
            ("ignored extras", report.ignored_extras),
        )
        if names
    ]
    return f"{report.provider} Filters: {'; '.join(parts)}" if parts else None


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
    for report in result.filter_reports:
        if (line := describe_filters(report)) is not None:
            console.print(line, markup=False)


def main() -> None:
    make_app()()
