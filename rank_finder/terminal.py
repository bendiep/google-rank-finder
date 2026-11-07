"""Terminal presentation. Redirected output remains plain text."""

import os
import shutil
import sys
import textwrap
from contextlib import contextmanager
from datetime import datetime
from itertools import cycle
from threading import Event, Thread
from time import monotonic

from .core import RankResult, SearchConfig


def style(text: str, code: str, *, stream=None) -> str:
    stream = sys.stdout if stream is None else stream
    if not stream.isatty() or "NO_COLOR" in os.environ or os.getenv("TERM") == "dumb":
        return text
    return f"\033[{code}m{text}\033[0m"


def banner(subtitle: str, *, stream=None, prominent: bool = False) -> str:
    title = "Google Rank Finder"
    heading = f"{title} | {subtitle}"
    width = max(20, min(shutil.get_terminal_size((80, 24)).columns - 4, len(heading), 64))
    lines = [""]
    if prominent:
        lines.extend(
            [
                style("  " + title, "1;36", stream=stream),
                "",
                style("  " + subtitle, "1;33", stream=stream),
            ]
        )
    elif len(heading) <= width:
        lines.append(
            style("  " + title, "1;36", stream=stream) + style(" | " + subtitle, "2", stream=stream)
        )
    else:
        lines.extend(
            [style("  " + title, "1;36", stream=stream), style("  " + subtitle, "2", stream=stream)]
        )
    lines.append(style("  " + "-" * width, "2", stream=stream))
    return "\n".join(lines)


def format_setup_required(message: str, *, stream=None) -> str:
    return "\n".join(
        [
            banner("Setup Needed", stream=stream, prominent=True),
            "",
            textwrap.indent(message, "  "),
            "",
        ]
    )


def section(title: str, *, stream=None) -> str:
    return "\n" + style("  " + title, "1;36", stream=stream)


@contextmanager
def search_progress(config: SearchConfig, retries: int, *, stream=None):
    stream = sys.stderr if stream is None else stream
    print(section("Searching Google", stream=stream), file=stream)
    print(
        f"    Checking up to {config.max_results} positions across up to {config.max_pages} pages.",
        file=stream,
    )
    print(
        style(
            f"    At most {config.max_pages * (retries + 1)} HTTP requests including retries.",
            "2",
            stream=stream,
        ),
        file=stream,
        flush=True,
    )
    if not stream.isatty() or os.getenv("TERM") == "dumb":
        yield
        return

    stopped = Event()
    started = monotonic()
    width = max(1, shutil.get_terminal_size((80, 24)).columns - 1)

    def animate():
        for frame in cycle("|/-\\"):
            elapsed = monotonic() - started
            message = f"  {frame} Searching Google... {elapsed:.1f}s"[:width]
            print(
                "\r" + style(message.ljust(width), "1;36", stream=stream),
                end="",
                file=stream,
                flush=True,
            )
            if stopped.wait(0.1):
                break

    worker = Thread(target=animate, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join()
        print("\r" + " " * width + "\r", end="", file=stream, flush=True)


def _row(label: str, value: str) -> list[str]:
    prefix = f"    {label:<16}  "
    width = max(20, min(shutil.get_terminal_size((80, 24)).columns, 100) - len(prefix))
    values = textwrap.wrap(value, width=width, break_long_words=False, break_on_hyphens=False) or [
        ""
    ]
    return [style(prefix, "2") + values[0], *(" " * len(prefix) + part for part in values[1:])]


def format_run_again(command: str, *, stream=None) -> str:
    instruction = (
        "Copy into PowerShell, or edit the options for your next search."
        if os.name == "nt"
        else "Copy and paste this command, or edit the options for your next search."
    )
    return "\n".join(
        [
            section("Run again", stream=stream),
            "    " + instruction,
            "",
            "    " + command,
        ]
    )


def format_result(result: RankResult, *, command: str | None = None) -> str:
    config = result.config
    lines = [banner("Organic search results"), ""]
    if result.status == "found":
        lines.append(style(f"  Rank #{result.rank}", "1;32"))
        lines.append("  " + style(result.url or "", "4;36"))
    elif result.status == "not_found":
        lines.append(style("  No match found", "1;33"))
        lines.append("  Your website did not appear in the positions checked.")
    elif result.status == "incomplete":
        lines.append(style("  Search incomplete", "1;33"))
        lines.append("  The full requested depth was not checked.")
    else:
        lines.append(style("  Search failed", "1;31"))
        lines.append("  No ranking conclusion is available.")
    if result.error:
        lines.extend(_row("Error", result.error))

    lines.append(section("Search"))
    for label, value in [
        ("Provider", "SerpApi"),
        ("Website", config.domain),
        ("Keyword", config.query),
        ("Country", config.country.upper()),
        ("Language", config.language),
        ("Device", config.device.capitalize()),
        ("Location", config.location or "Provider-selected"),
    ]:
        lines.extend(_row(label, value))
    locations = list(
        dict.fromkeys(
            ", ".join(part.strip() for part in item["location_used"].split(","))
            for item in result.searches
            if item.get("location_used")
        )
    )
    if locations:
        lines.extend(_row("Location used", "; ".join(locations)))
    lines.extend(
        _row("Matching", "Domain and subdomains" if config.include_subdomains else "Exact hostname")
    )
    for observation in result.searches:
        displayed = observation.get("query_displayed")
        if displayed and displayed != config.query:
            lines.extend(_row("Query shown", displayed))
            break

    lines.append(section("Coverage"))
    lines.extend(_row("Results checked", str(result.results_checked)))
    lines.extend(_row("Search limit", f"Top {config.max_results} positions"))
    lines.extend(
        _row(
            "Checked through",
            f"Position {result.deepest_rank_checked}"
            if result.deepest_rank_checked
            else "No organic positions checked",
        )
    )
    lines.extend(_row("Pages fetched", str(result.pages_checked)))
    if result.page:
        lines.extend(_row("Match found on", f"Page {result.page}"))
    lines.extend(_row("HTTP requests", str(result.requests_made)))
    stop_reasons = {
        "match": "Match found",
        "end_of_results": "End of available results",
        "depth_limit": "Requested depth reached",
        "page_limit": "Page budget reached",
        "provider_error": "Provider error",
    }
    lines.extend(_row("Stopped because", stop_reasons.get(result.stop_reason, result.stop_reason)))
    try:
        checked_at = datetime.fromisoformat(result.checked_at).strftime("%d %b %Y, %H:%M:%S %Z")
    except ValueError:
        checked_at = result.checked_at
    lines.append(section("Timing"))
    lines.extend(_row("Retrieved", checked_at))
    lines.extend(_row("Cache", "Bypassed" if config.fresh else "Allowed"))
    if command:
        lines.append(format_run_again(command))
    return "\n".join(lines) + "\n"
