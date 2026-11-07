import json
import unittest
from dataclasses import replace
from unittest.mock import patch

import requests

from rank_finder.core import SearchConfig, find_rank
from tests.support import API_KEY, client_with, fixture, page, response


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.config = SearchConfig(
            "example.com",
            "example keyword",
            country="au",
            location="Melbourne, Victoria, Australia",
        )
        self.sleep = patch("rank_finder.serpapi.time.sleep").start()
        self.addCleanup(patch.stopall)

    def test_finds_domain_and_stops_early(self):
        client, session = client_with(response(fixture()))
        result = find_rank(self.config, client)
        self.assertEqual((result.status, result.rank, result.page), ("found", 2, 1))
        self.assertEqual((result.results_checked, result.requests_made), (2, 1))
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(result.searches[0]["location_used"], "Melbourne,Victoria,Australia")
        self.assertEqual(result.searches[0]["created_at"], "2026-10-24 00:00:00 UTC")

    def test_false_domain_matches_do_not_report_found(self):
        links = [
            "https://notexample.com/",
            "https://example.com.other.test/",
            "https://other.test/?q=example.com",
        ]
        client, _ = client_with(
            response(page([{"position": i, "link": url} for i, url in enumerate(links, 1)]))
        )
        result = find_rank(self.config, client)
        self.assertEqual(
            (result.status, result.rank, result.results_checked), ("not_found", None, 3)
        )

    def test_provider_positions_and_next_offset_determine_rank(self):
        first = page([{"position": 1, "link": "https://other.test/"}], next_start=10)
        client, session = client_with(response(first), response(fixture("second_page")))
        result = find_rank(self.config, client)
        self.assertEqual((result.rank, result.page, result.results_checked), (13, 2, 3))
        self.assertEqual(
            [call.kwargs["params"]["start"] for call in session.get.call_args_list], [0, 10]
        )

    def test_exact_host_excludes_www(self):
        client, _ = client_with(
            response(page([{"position": 1, "link": "https://www.example.com/"}]))
        )
        self.assertEqual(
            find_rank(replace(self.config, include_subdomains=False), client).status, "not_found"
        )

    def test_successful_empty_search_is_not_a_provider_error(self):
        client, _ = client_with(response(fixture("empty_results")))
        result = find_rank(self.config, client)
        self.assertEqual(
            (result.status, result.pages_checked, result.results_checked), ("not_found", 1, 0)
        )
        self.assertIsNone(result.error)

    def test_absent_pagination_stops_requests(self):
        client, session = client_with(
            response(page([{"position": 1, "link": "https://other.test/"}]))
        )
        result = find_rank(self.config, client)
        self.assertEqual(result.stop_reason, "end_of_results")
        self.assertEqual(session.get.call_count, 1)

    def test_depth_limit_does_not_accept_a_lower_ranked_match(self):
        client, _ = client_with(response(fixture()))
        result = find_rank(replace(self.config, max_results=1), client)
        self.assertEqual(
            (result.status, result.results_checked, result.stop_reason),
            ("not_found", 1, "depth_limit"),
        )

    def test_no_request_beyond_requested_depth(self):
        client, session = client_with(
            response(page([{"position": 1, "link": "https://other.test/"}], next_start=10))
        )
        result = find_rank(replace(self.config, max_results=10), client)
        self.assertEqual((result.stop_reason, session.get.call_count), ("depth_limit", 1))

    def test_page_budget_marks_search_incomplete(self):
        client, _ = client_with(
            response(page([{"position": 1, "link": "https://other.test/"}], next_start=10))
        )
        result = find_rank(replace(self.config, max_pages=1), client)
        self.assertEqual((result.status, result.stop_reason), ("incomplete", "page_limit"))

    def test_later_page_failure_preserves_partial_progress(self):
        client, _ = client_with(
            response(page([{"position": 1, "link": "https://other.test/"}], next_start=10)),
            response({}, 503),
        )
        result = find_rank(self.config, client)
        self.assertEqual(
            (result.status, result.pages_checked, result.results_checked, result.requests_made),
            ("incomplete", 1, 1, 2),
        )
        self.assertIn("503", result.error)

    def test_error_json_does_not_look_like_a_missing_site(self):
        client, _ = client_with(
            response({"search_metadata": {"status": "Error"}, "error": "Proxy failed"})
        )
        result = find_rank(self.config, client)
        self.assertEqual(result.status, "error")
        self.assertIn("Proxy failed", result.error)

    def test_malformed_payloads_fail_closed(self):
        for data in [
            [],
            {},
            {"search_metadata": {"status": "Success"}},
            page([{"position": "1", "link": "https://example.com/"}]),
            page([{"position": 1}, {"position": 1}]),
            page([{"position": 1, "link": {}}]),
            {"search_metadata": {"status": "Processing"}},
        ]:
            with self.subTest(data=data):
                client, _ = client_with(response(data))
                self.assertEqual(find_rank(self.config, client).status, "error")

    def test_invalid_json_is_a_controlled_error(self):
        invalid = response()
        invalid._content = b"<html>upstream error</html>"
        client, _ = client_with(invalid)
        self.assertIn("invalid JSON", find_rank(self.config, client).error)

    def test_retry_is_bounded_and_counted(self):
        client, session = client_with(response({}, 503), response(fixture()), retries=1)
        result = find_rank(self.config, client)
        self.assertEqual((result.status, result.requests_made), ("found", 2))
        self.assertEqual(session.get.call_count, 2)
        self.sleep.assert_called_once_with(0.5)

    def test_timeout_exhaustion_does_not_expose_request_url(self):
        error = requests.Timeout("https://serpapi.com/search?api_key=" + API_KEY)
        client, session = client_with(error, error, retries=1)
        result = find_rank(self.config, client)
        self.assertEqual((result.status, session.get.call_count), ("error", 2))
        self.assertIn("timed out", result.error)
        self.assertNotIn(API_KEY, json.dumps(result.to_dict()))

    def test_quota_and_authentication_errors_are_not_retried(self):
        for status, message in [
            (400, "settings"),
            (401, "API key"),
            (403, "permission"),
            (429, "quota"),
        ]:
            with self.subTest(status=status):
                client, session = client_with(response({}, status), retries=3)
                result = find_rank(self.config, client)
                self.assertIn(message, result.error)
                self.assertEqual(session.get.call_count, 1)

    def test_search_context_and_cache_choice_reach_provider(self):
        client, session = client_with(response(fixture()))
        find_rank(replace(self.config, device="mobile", language="en-gb", fresh=True), client)
        call = session.get.call_args
        self.assertEqual(call.args, ("https://serpapi.com/search.json",))
        self.assertEqual(
            {
                name: call.kwargs["params"][name]
                for name in ["gl", "hl", "device", "location", "no_cache"]
            },
            {
                "gl": "au",
                "hl": "en-gb",
                "device": "mobile",
                "location": "Melbourne, Victoria, Australia",
                "no_cache": "true",
            },
        )
        self.assertFalse(call.kwargs["allow_redirects"])
        self.assertNotIn("num", call.kwargs["params"])

    def test_bad_pagination_cannot_loop_or_redirect_credentials(self):
        for next_url in [
            "https://serpapi.com/search?start=0",
            "https://serpapi.com/search?start=oops",
        ]:
            with self.subTest(next_url=next_url):
                data = page([], next_start=10)
                data["serpapi_pagination"]["next"] = next_url
                client, session = client_with(response(data))
                self.assertEqual(find_rank(self.config, client).status, "error")
                self.assertEqual(session.get.call_count, 1)
        data = page([], next_start=10)
        data["serpapi_pagination"]["next"] = "https://untrusted.test/?start=10"
        client, session = client_with(response(data), response(fixture("second_page")))
        self.assertEqual(find_rank(self.config, client).rank, 13)
        self.assertTrue(
            all(
                call.args[0] == "https://serpapi.com/search.json"
                for call in session.get.call_args_list
            )
        )

    def test_overlapping_pages_do_not_produce_a_false_rank(self):
        client, _ = client_with(
            response(page([{"position": 10, "link": "https://other.test/"}], next_start=5))
        )
        result = find_rank(self.config, client)
        self.assertEqual(result.status, "incomplete")
        self.assertIn("overlapping", result.error)

    def test_error_messages_redact_credentials(self):
        client, _ = client_with(
            response(
                {"search_metadata": {"status": "Error"}, "error": f"Failed with api_key={API_KEY}"}
            )
        )
        serialized = json.dumps(find_rank(self.config, client).to_dict())
        self.assertNotIn(API_KEY, serialized)
        self.assertIn("[redacted]", serialized)

    def test_generic_request_failure_is_controlled(self):
        client, _ = client_with(requests.RequestException(API_KEY))
        result = find_rank(self.config, client)
        self.assertEqual(result.status, "error")
        self.assertNotIn(API_KEY, result.error)

    def test_missing_link_is_counted_without_matching(self):
        client, _ = client_with(response(page([{"position": 1}])))
        result = find_rank(self.config, client)
        self.assertEqual((result.status, result.results_checked), ("not_found", 1))
