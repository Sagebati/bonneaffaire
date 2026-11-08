"""The `bonneaffaire` command: a thin adapter over the core."""

import asyncio
import json
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bonneaffaire.core import Bonneaffaire, UnknownProvider, UnrecognisedNativeUrl
from bonneaffaire.models import (
    DEFAULT_LIMIT,
    Condition,
    FilterReport,
    ListingDetails,
    ListingRequest,
    ListingStatus,
    Location,
    Money,
    ProviderInfo,
    SearchQuery,
    SearchRequest,
    SearchResult,
    Sort,
)
from bonneaffaire.registry import default_core
from bonneaffaire.server import DEFAULT_HOST, DEFAULT_PORT
from bonneaffaire.server import serve as serve_mcp


def make_app(
    core_factory: Callable[[], Bonneaffaire] = default_core,
    serve: Callable[[str, int, Callable[[], Bonneaffaire]], None] = serve_mcp,
) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, add_completion=False)

    @app.callback()
    def main() -> None:
        """Search second-hand and retail marketplaces in one place."""

    @app.command()
    def search(
        keywords: Annotated[
            list[str],
            typer.Argument(help="What to look for, or a Native URL copied from a Provider."),
        ],
        limit: Annotated[
            int, typer.Option(min=1, help="Maximum Listings per Provider.")
        ] = DEFAULT_LIMIT,
        providers: Annotated[
            list[str] | None,
            typer.Option(
                "--provider", "-p", help="Ask only this Provider (repeatable). Default: all."
            ),
        ] = None,
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
        sort: Annotated[
            Sort | None, typer.Option(help="Sort merged Listings by price or recency.")
        ] = None,
        extra: Annotated[
            list[str] | None,
            typer.Option(help="Provider-specific extra as provider.name=value; repeatable."),
        ] = None,
        as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    ) -> None:
        """Search for Listings by keywords, or by a Native URL from a Provider's website."""
        if radius_km is not None and near is None:
            raise typer.BadParameter("needs --near", param_hint="--radius-km")
        filters = {
            "price_min": parse_euros(min_price, "--min-price"),
            "price_max": parse_euros(max_price, "--max-price"),
            "conditions": frozenset(condition or ()),
            "location": Location(place=near, radius_km=radius_km) if near else None,
            "sort": sort,
            "extras": parse_extras(extra or []),
        }
        request = SearchRequest(
            query=query_from_arguments(keywords).model_copy(update=filters),
            limit=limit,
            providers=frozenset(providers) if providers else None,
        )
        try:
            result = asyncio.run(core_factory().search(request))
        except UnknownProvider as exc:
            raise typer.BadParameter(str(exc), param_hint="--provider") from exc
        except UnrecognisedNativeUrl as exc:
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

    @app.command()
    def providers(
        as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    ) -> None:
        """List Providers and what each supports."""
        infos = core_factory().list_providers()
        if as_json:
            typer.echo(json.dumps([info.model_dump(mode="json") for info in infos], indent=2))
        else:
            print_providers(infos)

    @app.command("serve")
    def serve_command(
        host: Annotated[
            str, typer.Option(envvar="BONNEAFFAIRE_HOST", help="Address to listen on.")
        ] = DEFAULT_HOST,
        port: Annotated[
            int, typer.Option(envvar="BONNEAFFAIRE_PORT", min=1, max=65535, help="Port.")
        ] = DEFAULT_PORT,
    ) -> None:
        """Run the MCP server over Streamable HTTP at http://HOST:PORT/mcp."""
        serve(host, port, core_factory)

    return app


def print_providers(infos: list[ProviderInfo]) -> None:
    table = Table(
        "Provider",
        "Country",
        "Status",
        "Native Filters",
        "Native URLs",
        "Listing details",
        "Extras",
        box=None,
    )
    for info in infos:
        table.add_row(
            info.name,
            info.country,
            "enabled" if info.enabled else "disabled",
            ", ".join(info.native_filters) or "-",
            "yes" if info.native_urls else "no",
            "yes" if info.listing_details else "no",
            ", ".join(info.extras) or "-",
        )
    Console().print(table)


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


def query_from_arguments(arguments: list[str]) -> SearchQuery:
    """A single http(s) argument is a Native URL; anything else is keywords."""
    if len(arguments) == 1 and arguments[0].startswith(("http://", "https://")):
        return SearchQuery(native_url=arguments[0])
    return SearchQuery(keywords=" ".join(arguments))


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
        line = f"{outcome.provider}: {outcome.status} ({outcome.listing_count} Listings)"
        if outcome.message:
            line += f" {outcome.message}"
        console.print(line, markup=False, highlight=False)
    for report in result.filter_reports:
        if (line := describe_filters(report)) is not None:
            console.print(line, markup=False, highlight=False)


def main() -> None:
    make_app()()
