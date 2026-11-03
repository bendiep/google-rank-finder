"""Command-line and interactive entry points."""

import argparse
import json
import math
import os
import shlex
import sqlite3
import sys
from dataclasses import replace

from .core import DEFAULT_COUNTRY, SearchConfig, find_rank, normalize_domain, validate_transport
from .history import save_result
from .serpapi import SerpApiClient
from .terminal import (
    banner,
    format_result,
    format_run_again,
    format_setup_required,
    search_progress,
    section,
    style,
)

COUNTRY_CODES_URL = "https://serpapi.com/google-countries"
LANGUAGE_CODES_URL = "https://serpapi.com/google-languages"
API_KEY_SETUP = (
    "The SERPAPI_API_KEY environment variable is not set or is empty.\n\n"
    "Set it in your terminal, replacing the placeholder with your API key:\n\n"
    '  export SERPAPI_API_KEY="your-serpapi-api-key"\n\n'
    "Exiting for now. Set your key, then run the app again."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check a domain's highest organic Google position using SerpApi. Run without arguments for guided setup.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "domain", nargs="?", metavar="DOMAIN", help="Domain or URL, e.g. amazon.com"
    )
    parser.add_argument("query", nargs="?", metavar="KEYWORD", help="Search keyword or phrase")
    parser.add_argument(
        "--domain",
        dest="named_domain",
        metavar="DOMAIN",
        help="Domain or URL, in any argument order",
    )
    parser.add_argument(
        "--keyword",
        "--query",
        dest="named_query",
        metavar="KEYWORD",
        help="Search keyword or phrase, in any argument order",
    )
    parser.add_argument(
        "--country",
        default=DEFAULT_COUNTRY,
        help=f"Two-letter search country code; default AU. Country codes: {COUNTRY_CODES_URL}",
    )
    parser.add_argument(
        "--location",
        help="Search origin, e.g. 'Melbourne, Victoria, Australia'",
    )
    parser.add_argument(
        "--language",
        default="en",
        help=f"Search interface language code; default en. Language codes: {LANGUAGE_CODES_URL}",
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


def build_rerun_command(
    config: SearchConfig,
    *,
    json_output: bool = False,
    history: str | None = None,
    timeout: float = 30,
    retries: int = 1,
) -> str:
    arguments = ["python", "-m", "rank_finder"]
    options = [
        ("--domain", config.domain),
        ("--keyword", config.query),
        ("--country", config.country.upper()),
        ("--language", config.language),
        ("--device", config.device),
        ("--max-results", str(config.max_results)),
    ]
    if config.location:
        options.append(("--location", config.location))
    if config.max_pages != math.ceil(config.max_results / 10):
        options.append(("--max-pages", str(config.max_pages)))
    if timeout != 30:
        options.append(("--timeout", str(timeout)))
    if retries != 1:
        options.append(("--retries", str(retries)))
    if history:
        options.append(("--history", history))
    for option, value in options:
        if value.startswith("-"):
            arguments.append(f"{option}={value}")
        else:
            arguments.extend((option, value))
    if not config.include_subdomains:
        arguments.append("--exact-host")
    if config.fresh:
        arguments.append("--fresh")
    if json_output:
        arguments.append("--json")
    if os.name == "nt":
        return "python -m rank_finder " + " ".join(
            "'" + argument.replace("'", "''") + "'" for argument in arguments[3:]
        )
    return shlex.join(arguments)


def _prompt(label: str, default: str = "", validate=None, *, hint: str = "") -> str:
    question = "  " + style(label, "1", stream=sys.stderr)
    if default:
        question += style(f" [{default}]", "36", stream=sys.stderr)
    print("\n" + question, file=sys.stderr)
    for hint_line in hint.splitlines():
        print(style("    " + hint_line, "2", stream=sys.stderr), file=sys.stderr)
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
            raise ValueError("Choose: " + " | ".join(options) + ".")

    return validate


def interactive_config() -> tuple[SearchConfig, bool, str | None]:
    print(
        banner("Guided setup", stream=sys.stderr),
        file=sys.stderr,
    )
    print(
        style(
            "  Enter accepts a default or skips an optional field. Ctrl+C cancels.",
            "2",
            stream=sys.stderr,
        ),
        file=sys.stderr,
    )
    print(section("Search terms", stream=sys.stderr), file=sys.stderr)
    domain = _prompt(
        "Website",
        validate=normalize_domain,
        hint="e.g. amazon.com.au | https://www.amazon.com.au",
    )

    def validate_query(value):
        if not value:
            raise ValueError("Enter a keyword or phrase.")

    query = _prompt(
        "Keyword or phrase",
        validate=validate_query,
        hint="e.g. shoes | running shoes",
    )
    config = SearchConfig(domain, query)
    print(section("Search settings", stream=sys.stderr), file=sys.stderr)
    country = _prompt(
        "Country code",
        config.country.upper(),
        lambda value: replace(config, country=value),
        hint=f"e.g. AU for Australia\nCountry codes: {COUNTRY_CODES_URL}",
    )
    language = _prompt(
        "Language",
        config.language,
        lambda value: replace(config, language=value),
        hint=f"e.g. en for English\nLanguage codes: {LANGUAGE_CODES_URL}",
    )
    location = _prompt("City or region (optional)", hint="e.g. Melbourne | Victoria")
    device = _prompt(
        "Device",
        config.device,
        _choice("desktop", "mobile", "tablet"),
        hint="Choose: desktop | mobile | tablet\nOnly one device per search.",
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
            hint="Choose: a whole number from 1 to 1000\nSet the highest organic position to check.",
        )
    )
    include_subdomains = _prompt(
        "Include subdomains?",
        "yes",
        _choice("yes", "no", "y", "n"),
        hint="Choose: yes | no\nInclude www and other subdomains.",
    ).lower() in ("yes", "y")
    fresh = _prompt(
        "Fetch fresh results?",
        "no",
        _choice("yes", "no", "y", "n"),
        hint="Choose: yes | no\nBypass cached results, which can use more search credits.",
    ).lower() in ("yes", "y")
    print(section("Output", stream=sys.stderr), file=sys.stderr)
    json_output = (
        _prompt(
            "Output format",
            "text",
            _choice("text", "json"),
            hint="Choose: text | json",
        ).lower()
        == "json"
    )
    history = (
        _prompt(
            "History file (optional)",
            hint="e.g. ranks.sqlite3\nSave this result to a local SQLite file.",
        )
        or None
    )
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
    return config, json_output, history


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    try:
        if not argv:
            if not api_key:
                print(format_setup_required(API_KEY_SETUP, stream=sys.stderr), file=sys.stderr)
                return 2
            if not sys.stdin.isatty():
                parser.error(
                    "Guided setup needs a terminal. Supply a domain and keyword, or run --help."
                )
            config, json_output, history = interactive_config()
            timeout, retries = 30, 1
        else:
            args = parser.parse_intermixed_args(argv)
            positional = [value for value in (args.domain, args.query) if value is not None]
            domain, query = args.named_domain, args.named_query
            if domain is None and positional:
                domain = positional.pop(0)
            if query is None and positional:
                query = positional.pop(0)
            if positional:
                parser.error(
                    "Supply each search term only once, using positionals or named options."
                )
            if domain is None or query is None:
                parser.error(
                    "Supply a domain and keyword, either as DOMAIN KEYWORD or with --domain and --keyword."
                )
            json_output = args.json
            try:
                depth = (
                    args.max_results
                    if args.max_results is not None
                    else (args.max_pages * 10 if args.max_pages is not None else 100)
                )
                config = SearchConfig(
                    domain=domain,
                    query=query,
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
            if not api_key:
                if json_output:
                    print(json.dumps({"status": "error", "error": API_KEY_SETUP}))
                else:
                    print(format_setup_required(API_KEY_SETUP, stream=sys.stderr), file=sys.stderr)
                return 2
        with SerpApiClient(api_key, timeout=timeout, retries=retries) as client:
            with search_progress(config, retries):
                result = find_rank(config, client)
        command = build_rerun_command(
            config, json_output=json_output, history=history, timeout=timeout, retries=retries
        )
        print(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
            if json_output
            else format_result(result, command=command)
        )
        if json_output:
            print(format_run_again(command, stream=sys.stderr), file=sys.stderr)
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
