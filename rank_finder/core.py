"""Search settings, hostname matching, and ranking independent of HTTP or the CLI."""

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit

DEFAULT_COUNTRY = "au"


def normalize_domain(value: str) -> str:
    """Accept a hostname or HTTP URL, retaining an explicitly supplied www prefix."""
    value = value.strip()
    try:
        parsed = urlsplit(value if "://" in value else "//" + value)
        if parsed.scheme not in ("", "http", "https"):
            raise ValueError
        if parsed.username is not None or parsed.password is not None:
            raise ValueError
        if parsed.port is not None and parsed.port < 1:
            raise ValueError
        hostname = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        labels = hostname.split(".")
        if len(hostname) > 253 or len(labels) < 2:
            raise ValueError
        if any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
        ):
            raise ValueError
        return hostname
    except (ValueError, UnicodeError):
        raise ValueError(
            "Enter a valid domain or HTTP URL, such as example.com, without credentials."
        ) from None


def matches_domain(url: str, domain: str, include_subdomains: bool = True) -> bool:
    try:
        if urlsplit(url).scheme not in ("http", "https"):
            return False
        hostname = normalize_domain(url)
    except (ValueError, AttributeError):
        return False
    return hostname == domain or (include_subdomains and hostname.endswith("." + domain))


@dataclass(frozen=True)
class SearchConfig:
    domain: str
    query: str
    country: str = DEFAULT_COUNTRY
    language: str = "en"
    location: str | None = None
    device: str = "desktop"
    max_results: int = 100
    max_pages: int = 10
    include_subdomains: bool = True
    fresh: bool = False

    def __post_init__(self):
        object.__setattr__(self, "domain", normalize_domain(self.domain))
        object.__setattr__(self, "query", self.query.strip())
        object.__setattr__(self, "country", self.country.strip().lower())
        object.__setattr__(self, "language", self.language.strip().lower())
        object.__setattr__(
            self, "location", (self.location.strip() or None) if self.location else None
        )
        if not self.query:
            raise ValueError("The search keyword or phrase cannot be empty.")
        if not re.fullmatch(r"[a-z]{2}", self.country):
            raise ValueError("Country must be a two-letter code, such as AU or US.")
        if not re.fullmatch(r"[a-z]{2,3}(?:-(?:[a-z]{2}|[0-9]{3}))?", self.language):
            raise ValueError("Language must be a code such as en, en-gb or es-419.")
        if self.device not in ("desktop", "mobile", "tablet"):
            raise ValueError("Device must be desktop, mobile or tablet.")
        if type(self.max_results) is not int or not 1 <= self.max_results <= 1000:
            raise ValueError("Search depth must be between 1 and 1000.")
        if type(self.max_pages) is not int or not 1 <= self.max_pages <= 100:
            raise ValueError("Maximum pages must be between 1 and 100.")


class SearchError(Exception):
    """A search failed or the provider returned data we cannot safely interpret."""


@dataclass(frozen=True)
class OrganicResult:
    position: int
    url: str | None


@dataclass(frozen=True)
class SearchPage:
    results: list[OrganicResult]
    next_start: int | None
    observation: dict = field(default_factory=dict)


class SearchProvider(Protocol):
    request_count: int

    def fetch(self, config: SearchConfig, start: int) -> SearchPage: ...


@dataclass
class RankResult:
    config: SearchConfig
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "not_found"
    rank: int | None = None
    url: str | None = None
    page: int | None = None
    results_checked: int = 0
    deepest_rank_checked: int = 0
    pages_checked: int = 0
    requests_made: int = 0
    stop_reason: str = "end_of_results"
    error: str | None = None
    searches: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"provider": "serpapi", "measurement": "organic_position", **asdict(self)}


def find_rank(config: SearchConfig, provider: SearchProvider) -> RankResult:
    result = RankResult(config)
    initial_requests = provider.request_count
    start = 0
    try:
        for page_number in range(1, config.max_pages + 1):
            page = provider.fetch(config, start)
            result.pages_checked += 1
            result.searches.append({"start": start, **page.observation})
            for item in sorted(page.results, key=lambda item: item.position):
                rank = start + item.position
                if rank > config.max_results:
                    result.stop_reason = "depth_limit"
                    return result
                result.results_checked += 1
                result.deepest_rank_checked = rank
                if item.url and matches_domain(item.url, config.domain, config.include_subdomains):
                    result.status = "found"
                    result.rank, result.url, result.page = rank, item.url, page_number
                    result.stop_reason = "match"
                    return result
            if page.next_start is None:
                return result
            if page.next_start >= config.max_results:
                result.stop_reason = "depth_limit"
                return result
            if page.next_start <= max(start, result.deepest_rank_checked - 1):
                raise SearchError("SerpApi returned overlapping or non-advancing pagination.")
            start = page.next_start
        result.status = "incomplete"
        result.stop_reason = "page_limit"
    except SearchError as exc:
        result.status = "incomplete" if result.pages_checked else "error"
        result.stop_reason = "provider_error"
        result.error = str(exc)
    finally:
        result.requests_made = provider.request_count - initial_requests
        result.checked_at = datetime.now(timezone.utc).isoformat()
    return result


def validate_transport(timeout: float, retries: int) -> None:
    if not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("Timeout must be greater than 0 and no more than 300 seconds.")
    if type(retries) is not int or not 0 <= retries <= 3:
        raise ValueError("Retries must be between 0 and 3.")
