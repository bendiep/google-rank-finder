"""A bounded SerpApi client. Pagination never changes the request destination."""

import re
import time
from urllib.parse import parse_qs, quote, quote_plus, urlsplit

import requests

from .core import OrganicResult, SearchConfig, SearchError, SearchPage, validate_transport

ENDPOINT = "https://serpapi.com/search.json"
TRANSIENT_STATUSES = {500, 502, 503, 504}


class SerpApiClient:
    def __init__(self, api_key: str, *, timeout: float = 30, retries: int = 1, session=None):
        validate_transport(timeout, retries)
        self.api_key = api_key.strip()
        if not self.api_key:
            raise ValueError("Set the SERPAPI_API_KEY environment variable before searching.")
        self.timeout, self.retries = timeout, retries
        self.session = session if session is not None else requests.Session()
        self._owns_session = session is None
        self.request_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self._owns_session:
            self.session.close()

    def _safe_message(self, message: str) -> str:
        for secret in {self.api_key, quote(self.api_key, safe=""), quote_plus(self.api_key)}:
            message = message.replace(secret, "[redacted]")
        message = re.sub(r"(?i)(api_key\s*[=:]\s*)[^\s&]+", r"\1[redacted]", message)
        return re.sub(r"[\x00-\x1f\x7f]", " ", message)[:500]

    def fetch(self, config: SearchConfig, start: int) -> SearchPage:
        params = {
            "api_key": self.api_key,
            "engine": "google",
            "q": config.query,
            "gl": config.country,
            "hl": config.language,
            "device": config.device,
            "start": start,
            "safe": "off",
            "nfpr": 1,
            "no_cache": "true" if config.fresh else "false",
        }
        if config.location:
            params["location"] = config.location
        for attempt in range(self.retries + 1):
            self.request_count += 1
            try:
                response = self.session.get(
                    ENDPOINT,
                    params=params,
                    timeout=self.timeout,
                    allow_redirects=False,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt < self.retries:
                    time.sleep(0.5 * 2**attempt)
                    continue
                message = (
                    "SerpApi timed out."
                    if isinstance(exc, requests.Timeout)
                    else "Could not connect to SerpApi."
                )
                raise SearchError(message + " Try again later.") from None
            except requests.RequestException:
                raise SearchError("The request to SerpApi failed.") from None
            if response.status_code in TRANSIENT_STATUSES and attempt < self.retries:
                response.close()
                time.sleep(0.5 * 2**attempt)
                continue
            try:
                if response.status_code != 200:
                    messages = {
                        400: "SerpApi rejected the search settings. Check the country, language and location.",
                        401: "SerpApi rejected the API key. Check SERPAPI_API_KEY.",
                        403: "This SerpApi account does not have permission to search.",
                        429: "SerpApi's rate limit or search quota has been reached. Check your account.",
                    }
                    raise SearchError(
                        messages.get(
                            response.status_code,
                            f"SerpApi returned HTTP {response.status_code}. Try again later.",
                        )
                    )
                try:
                    data = response.json()
                except ValueError:
                    raise SearchError("SerpApi returned invalid JSON.") from None
            finally:
                response.close()
            return self._parse_page(data, start)
        raise SearchError("SerpApi could not complete the search.")

    def _parse_page(self, data, start: int) -> SearchPage:
        if not isinstance(data, dict) or not isinstance(data.get("search_metadata"), dict):
            raise SearchError("SerpApi returned a malformed search response.")
        metadata = data["search_metadata"]
        if metadata.get("status") != "Success":
            detail = data.get("error")
            detail = (
                self._safe_message(detail)
                if isinstance(detail, str)
                else "The search did not complete successfully."
            )
            raise SearchError("SerpApi search failed: " + detail)
        information = data.get("search_information", {})
        parameters = data.get("search_parameters", {})
        if not isinstance(information, dict) or not isinstance(parameters, dict):
            raise SearchError("SerpApi returned malformed search metadata.")
        empty = str(information.get("organic_results_state", "")).lower() == "fully empty"
        if data.get("error") and not empty:
            raise SearchError("SerpApi search failed: " + self._safe_message(str(data["error"])))
        items = data.get("organic_results", [] if empty else None)
        if not isinstance(items, list):
            raise SearchError("SerpApi returned missing or malformed organic results.")
        results = []
        positions = set()
        for item in items:
            if not isinstance(item, dict):
                raise SearchError("SerpApi returned a malformed organic result.")
            position, link = item.get("position"), item.get("link")
            if type(position) is not int or position < 1 or position in positions:
                raise SearchError("SerpApi returned invalid or duplicate organic positions.")
            if link is not None and not isinstance(link, str):
                raise SearchError("SerpApi returned a malformed result URL.")
            positions.add(position)
            results.append(OrganicResult(position, link))
        observation = {
            "search_id": metadata.get("id"),
            "created_at": metadata.get("created_at"),
            "location_used": parameters.get("location_used"),
            "query_displayed": information.get("query_displayed"),
        }
        if any(value is not None and not isinstance(value, str) for value in observation.values()):
            raise SearchError("SerpApi returned malformed search metadata.")
        return SearchPage(results, self._next_start(data, start), observation)

    @staticmethod
    def _next_start(data: dict, start: int) -> int | None:
        pagination = data.get("serpapi_pagination", data.get("pagination", {}))
        if not isinstance(pagination, dict):
            raise SearchError("SerpApi returned malformed pagination.")
        next_url = pagination.get("next") or pagination.get("next_link")
        if not next_url:
            return None
        try:
            offsets = parse_qs(urlsplit(next_url).query).get("start", [])
            if len(offsets) != 1:
                raise ValueError
            offset = int(offsets[0])
            if offset <= start:
                raise ValueError
            return offset
        except (ValueError, TypeError, AttributeError):
            raise SearchError("SerpApi returned invalid or non-advancing pagination.") from None
