"""Command-line and interactive entry points."""

import argparse
import getpass
import json
import math
import os
import sqlite3
import sys
from dataclasses import replace

from .core import DEFAULT_COUNTRY, SearchConfig, find_rank, normalize_domain, validate_transport
from .history import save_result
from .serpapi import SerpApiClient
from .terminal import banner, format_result, section, style

COUNTRY_CODES_URL = "https://serpapi.com/google-countries"
API_KEY_SETUP = (
    "The SERPAPI_API_KEY environment variable is not set or is empty.\n"
    "Set it in your terminal, replacing the placeholder with your API key:\n"
    '  export SERPAPI_API_KEY="your-serpapi-api-key"'
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check a domain's highest organic Google position using SerpApi. Run without arguments for guided setup.",
        allow_abbrev=False,
    )
    parser.add_argument("domain", help="Domain or URL, for example example.com")
    parser.add_argument("query", help="Search keyword or phrase")
    parser.add_argument(
        "--country",
        default=DEFAULT_COUNTRY,
        help=f"Two-letter search country code; default AU. Country codes: {COUNTRY_CODES_URL}",
    )
    parser.add_argument(
        "--location",
        help="Search origin, preferably a city, such as 'Melbourne, Victoria, Australia'",
    )
    parser.add_argument(
        "--language", default="en", help="Search interface language code; default en"
    )
    parser.add_argument(
        "--device",
        choices=("desktop", "mobile", "tablet"),
        default="desktop",
        help="Search device; default desktop",
    )
    parser.add_argument(
        "--max-results",
        "--depth",
        type=int,
        help="Highest organic position to check, 1-1000; default 100",
    )
    parser.add_argument(
        "--max-pages",
        "--max_pages",
        type=int,
        help="Page budget, 1-100; defaults to enough ten-position pages for the requested depth",
    )
    parser.add_argument(
        "--exact-host",
        action="store_true",
        help="Match only the supplied hostname, excluding its subdomains",
    )
    parser.add_argument(
        "--fresh", action="store_true", help="Bypass SerpApi's cache, which can increase usage"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="Timeout per HTTP request in seconds; default 30, at most 300",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retries per page for connection failures and HTTP 5xx errors; default 1, maximum 3",
    )
    parser.add_argument("--json", action="store_true", help="Write the structured result as JSON")
    parser.add_argument(
        "--history", metavar="FILE", help="Append the result to a local SQLite database"
    )
    return parser


def _prompt(label: str, default: str = "", validate=None, *, hint: str = "") -> str:
    question = "  " + style(label, "1", stream=sys.stderr)
    if default:
        question += style(f" [{default}]", "36", stream=sys.stderr)
    print("\n" + question, file=sys.stderr)
    if hint:
        print(style("    " + hint, "2", stream=sys.stderr), file=sys.stderr)
    while True:
        print(style("  > ", "36", stream=sys.stderr), end="", file=sys.stderr, flush=True)
        value = input().strip() or default
        try:
            if validate:
                validate(value)
            return value
        except ValueError as exc:
            print(style("    ! " + str(exc), "31", stream=sys.stderr), file=sys.stderr)


def _choice(*options):
    def validate(value):
        if value.lower() not in options:
            raise ValueError("Choose " + ", ".join(options) + ".")

    return validate


def interactive_config() -> tuple[SearchConfig, str, bool, str | None]:
    print(
        banner("Guided setup", stream=sys.stderr),
        file=sys.stderr,
    )
    print(
        style("  Enter accepts a default. Ctrl+C cancels.", "2", stream=sys.stderr), file=sys.stderr
    )
    print(section("Search terms", stream=sys.stderr), file=sys.stderr)
    domain = _prompt(
        "Website", validate=normalize_domain, hint="Enter a domain or URL, for example example.com."
    )

    def validate_query(value):
        if not value:
            raise ValueError("Enter a keyword or phrase.")

    query = _prompt("Keyword or phrase", validate=validate_query)
    config = SearchConfig(domain, query)
    print(section("Search settings", stream=sys.stderr), file=sys.stderr)
    country = _prompt(
        "Country code",
        config.country.upper(),
        lambda value: replace(config, country=value),
        hint=f"AU = Australia. Country codes: {COUNTRY_CODES_URL}",
    )
    language = _prompt(
        "Language",
        config.language,
        lambda value: replace(config, language=value),
        hint="Use a language code, such as en for English.",
    )
    location = _prompt(
        "City or region", hint="Optional. For example Melbourne, Victoria, Australia."
    )
    device = _prompt(
        "Device",
        config.device,
        _choice("desktop", "mobile", "tablet"),
        hint="desktop / mobile / tablet",
    ).lower()

    def validate_depth(value):
        try:
            replace(config, max_results=int(value))
        except ValueError:
            raise ValueError("Enter a whole number between 1 and 1000.") from None

    depth = int(
        _prompt(
            "Search depth",
            "100",
            validate_depth,
            hint="Highest organic position to check, between 1 and 1000.",
        )
    )
    include_subdomains = _prompt(
        "Include subdomains?",
        "yes",
        _choice("yes", "no", "y", "n"),
        hint="Includes www and other subdomains. Choose yes or no.",
    ).lower() in ("yes", "y")
    fresh = _prompt(
        "Fetch fresh results?",
        "no",
        _choice("yes", "no", "y", "n"),
        hint="Skip cached results. This can use more search credits.",
    ).lower() in ("yes", "y")
    print(section("Output", stream=sys.stderr), file=sys.stderr)
    json_output = (
        _prompt("Output format", "text", _choice("text", "json"), hint="text / json").lower()
        == "json"
    )
    history = (
        _prompt("History file", hint="Optional SQLite file, such as ranks.sqlite3. Enter to skip.")
        or None
    )
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key:
        print(section("API key", stream=sys.stderr), file=sys.stderr)
        print("  " + API_KEY_SETUP.replace("\n", "\n  "), file=sys.stderr)
        print(
            style("  Get a key: https://serpapi.com/manage-api-key", "2", stream=sys.stderr),
            file=sys.stderr,
        )
        print(
            style(
                "  Or enter a key below. Hidden while typing; used for this run only.\n",
                "2",
                stream=sys.stderr,
            ),
            file=sys.stderr,
        )
    while not api_key:
        api_key = getpass.getpass(style("  API key: ", "1", stream=sys.stderr)).strip()
        if not api_key:
            print(style("  ! An API key is required.", "31", stream=sys.stderr), file=sys.stderr)
    config = replace(
        config,
        country=country,
        language=language,
        location=location,
        device=device,
        max_results=depth,
        max_pages=math.ceil(depth / 10),
        include_subdomains=include_subdomains,
        fresh=fresh,
    )
    print(section("Starting search", stream=sys.stderr), file=sys.stderr)
    print(f"  Top {depth} positions / up to {config.max_pages} pages", file=sys.stderr)
    print(
        style(
            f"  At most {config.max_pages * 2} HTTP requests including retries.\n",
            "2",
            stream=sys.stderr,
        ),
        file=sys.stderr,
    )
    return config, api_key, json_output, history


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    try:
        if not argv:
            if not sys.stdin.isatty():
                parser.error(
                    "Guided setup needs a terminal. Supply a domain and keyword, or run --help."
                )
            config, api_key, json_output, history = interactive_config()
            timeout, retries = 30, 1
        else:
            args = parser.parse_args(argv)
            json_output = args.json
            try:
                depth = (
                    args.max_results
                    if args.max_results is not None
                    else (args.max_pages * 10 if args.max_pages is not None else 100)
                )
                config = SearchConfig(
                    domain=args.domain,
                    query=args.query,
                    country=args.country,
                    language=args.language,
                    location=args.location,
                    device=args.device,
                    max_results=depth,
                    max_pages=args.max_pages
                    if args.max_pages is not None
                    else math.ceil(depth / 10),
                    include_subdomains=not args.exact_host,
                    fresh=args.fresh,
                )
                validate_transport(args.timeout, args.retries)
            except ValueError as exc:
                parser.error(str(exc))
            timeout, retries, history = args.timeout, args.retries, args.history
            api_key = os.getenv("SERPAPI_API_KEY", "").strip()
            if not api_key:
                message = (
                    API_KEY_SETUP
                    + "\nThen rerun your search, or run without arguments for guided setup."
                )
                if json_output:
                    print(json.dumps({"status": "error", "error": message}))
                else:
                    print("Error: " + message, file=sys.stderr)
                return 2
        with SerpApiClient(api_key, timeout=timeout, retries=retries) as client:
            result = find_rank(config, client)
        print(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
            if json_output
            else format_result(result)
        )
        exit_code = {"found": 0, "not_found": 1, "error": 2, "incomplete": 3}[result.status]
        if history:
            try:
                save_result(history, result)
            except (OSError, sqlite3.Error):
                print(
                    "Error: Could not save history. Check the database path and permissions.",
                    file=sys.stderr,
                )
                return 2
        return exit_code
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except EOFError:
        print(
            "\nInput ended before setup was complete. Supply a domain and keyword to run without prompts.",
            file=sys.stderr,
        )
        return 2
