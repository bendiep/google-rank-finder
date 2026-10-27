import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from rank_finder.cli import main
from tests.support import API_KEY, fixture, page, response


class CliTests(unittest.TestCase):
    def run_cli(self, argv, responses=None, environment=None):
        session = Mock(spec=requests.Session)
        session.get.side_effect = responses or [response(fixture())]
        stdout, stderr = io.StringIO(), io.StringIO()
        environment = {"SERPAPI_API_KEY": API_KEY} if environment is None else environment
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("rank_finder.serpapi.requests.Session", return_value=session),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue(), session

    def test_existing_positional_usage_still_works(self):
        code, stdout, _, session = self.run_cli(["example.com", "example keyword"])
        self.assertEqual(code, 0)
        self.assertIn("#2  Match found", stdout)
        self.assertRegex(stdout, r"Country\s+AU")
        self.assertRegex(stdout, r"Language\s+en")
        self.assertRegex(stdout, r"Device\s+Desktop")
        self.assertIn("Melbourne, Victoria, Australia", stdout)
        self.assertEqual(session.get.call_args.kwargs["params"]["gl"], "au")
        session.close.assert_called_once()

    def test_json_output_is_only_json_and_has_search_context(self):
        code, stdout, stderr, _ = self.run_cli(
            [
                "example.com",
                "example keyword",
                "--country",
                "AU",
                "--language",
                "en",
                "--location",
                "Melbourne, Victoria, Australia",
                "--device",
                "mobile",
                "--json",
            ]
        )
        data = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            (data["status"], data["rank"], data["config"]["device"]), ("found", 2, "mobile")
        )
        self.assertIn("checked_at", data)
        self.assertIn("created_at", data["searches"][0])
        self.assertNotIn(API_KEY, stdout)

    def test_not_found_and_incomplete_have_different_exit_codes(self):
        code, stdout, _, _ = self.run_cli(
            ["example.com", "keyword", "--json"], [response(fixture("empty_results"))]
        )
        self.assertEqual((code, json.loads(stdout)["status"]), (1, "not_found"))
        code, stdout, _, _ = self.run_cli(
            ["example.com", "keyword", "--max-results", "100", "--max-pages", "1", "--json"],
            [response(page([{"position": 1, "link": "https://other.test/"}], next_start=10))],
        )
        self.assertEqual((code, json.loads(stdout)["status"]), (3, "incomplete"))

    def test_provider_error_is_json_and_nonzero(self):
        code, stdout, _, _ = self.run_cli(["example.com", "keyword", "--json"], [response({}, 401)])
        self.assertEqual((code, json.loads(stdout)["status"]), (2, "error"))

    def test_missing_api_key_is_actionable_without_a_traceback(self):
        for environment in ({}, {"SERPAPI_API_KEY": ""}, {"SERPAPI_API_KEY": " \t "}):
            for json_output in (False, True):
                with self.subTest(environment=environment, json_output=json_output):
                    argv = ["example.com", "keyword", *(["--json"] if json_output else [])]
                    code, stdout, stderr, session = self.run_cli(argv, environment=environment)
                    self.assertEqual(code, 2)
                    if json_output:
                        data = json.loads(stdout)
                        self.assertEqual(data["status"], "error")
                        self.assertEqual(stderr, "")
                        message = data["error"]
                    else:
                        self.assertEqual(stdout, "")
                        message = stderr
                    self.assertIn("SERPAPI_API_KEY environment variable is not set", message)
                    self.assertIn('export SERPAPI_API_KEY="your-serpapi-api-key"', message)
                    self.assertIn("replacing the placeholder with your API key", message)
                    self.assertNotIn("Traceback", message)
                    session.get.assert_not_called()

    def test_legacy_max_pages_alias_limits_depth(self):
        code, stdout, _, _ = self.run_cli(["example.com", "keyword", "--max_pages", "3", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(
            (
                json.loads(stdout)["config"]["max_results"],
                json.loads(stdout)["config"]["max_pages"],
            ),
            (30, 3),
        )

    def test_invalid_arguments_do_not_call_provider(self):
        for options in [
            ["--max-results", "0"],
            ["--max-pages", "-1"],
            ["--timeout", "nan"],
            ["--timeout", "inf"],
            ["--retries", "4"],
            ["--country", "Australia"],
            ["--language", "English"],
            ["--api", "SERPAPI"],
        ]:
            with (
                self.subTest(options=options),
                patch("rank_finder.cli.SerpApiClient") as client,
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as caught,
            ):
                main(["example.com", "keyword", *options])
            self.assertEqual(caught.exception.code, 2)
            client.assert_not_called()

    def test_no_arguments_without_a_terminal_explains_how_to_run(self):
        with (
            patch("sys.stdin.isatty", return_value=False),
            redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit) as caught,
        ):
            main([])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("Supply a domain and keyword", stderr.getvalue())

    def test_interactive_defaults_use_environment_key(self):
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("builtins.input", side_effect=["example.com", "example keyword", *([""] * 9)]),
            patch("getpass.getpass") as getpass,
        ):
            code, stdout, stderr, session = self.run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("#2  Match found", stdout)
        self.assertIn("[AU]", stderr)
        self.assertIn("https://serpapi.com/google-countries", stderr)
        self.assertEqual(session.get.call_args.kwargs["params"]["gl"], "au")
        self.assertIn("including retries", stderr)
        getpass.assert_not_called()

    def test_interactive_settings_and_hidden_key(self):
        inputs = [
            "https://example.com/page",
            "example keyword",
            "AU",
            "en-gb",
            "Melbourne, Victoria, Australia",
            "mobile",
            "25",
            "no",
            "yes",
            "json",
            "",
        ]
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("builtins.input", side_effect=inputs),
            patch("getpass.getpass", return_value=API_KEY) as getpass,
        ):
            code, stdout, stderr, session = self.run_cli(
                [],
                [response(page([{"position": 1, "link": "https://example.com/"}]))],
                environment={},
            )
        data = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(
            (data["config"]["country"], data["config"]["device"], data["config"]["max_pages"]),
            ("au", "mobile", 3),
        )
        self.assertFalse(data["config"]["include_subdomains"])
        self.assertTrue(data["config"]["fresh"])
        self.assertEqual(session.get.call_args.kwargs["params"]["api_key"], API_KEY)
        self.assertNotIn(API_KEY, stdout + stderr)
        self.assertIn("SERPAPI_API_KEY environment variable is not set", stderr)
        self.assertIn('export SERPAPI_API_KEY="your-serpapi-api-key"', stderr)
        getpass.assert_called_once()

    def test_interactive_invalid_entries_can_be_corrected(self):
        inputs = [
            "invalid",
            "example.com",
            "",
            "keyword",
            "Australia",
            "AU",
            "",
            "",
            "watch",
            "desktop",
            "zero",
            "10",
            "perhaps",
            "yes",
            "",
            "",
            "",
        ]
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("builtins.input", side_effect=inputs),
        ):
            code, _, stderr, _ = self.run_cli([])
        self.assertEqual(code, 0)
        for message in [
            "valid domain",
            "keyword or phrase",
            "two-letter",
            "Choose desktop",
            "whole number",
            "Choose yes",
        ]:
            self.assertIn(message, stderr)

    def test_interactive_cancel_and_end_of_input_are_clean(self):
        for exception, expected_code in [(KeyboardInterrupt, 130), (EOFError, 2)]:
            with (
                self.subTest(exception=exception),
                patch("sys.stdin.isatty", return_value=True),
                patch("builtins.input", side_effect=exception),
            ):
                code, _, stderr, _ = self.run_cli([])
            self.assertEqual(code, expected_code)
            self.assertNotIn("Traceback", stderr)

    def test_history_appends_observations_and_preserves_context(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "ranks.sqlite3"
            for _ in range(2):
                code, _, _, _ = self.run_cli(
                    [
                        "example.com",
                        "keyword'); DROP TABLE rank_checks; --",
                        "--country",
                        "AU",
                        "--history",
                        str(database),
                    ]
                )
                self.assertEqual(code, 0)
            with closing(sqlite3.connect(database)) as connection:
                rows = connection.execute(
                    "SELECT status, rank, result_json FROM rank_checks ORDER BY id"
                ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][:2], ("found", 2))
            self.assertEqual(json.loads(rows[0][2])["config"]["country"], "au")
            self.assertNotIn(API_KEY, rows[0][2])

    def test_history_failure_is_reported_without_losing_result(self):
        with patch("rank_finder.cli.save_result", side_effect=sqlite3.OperationalError):
            code, stdout, stderr, _ = self.run_cli(
                ["example.com", "keyword", "--json", "--history", "missing/ranks.sqlite3"]
            )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["status"], "found")
        self.assertIn("Could not save history", stderr)
