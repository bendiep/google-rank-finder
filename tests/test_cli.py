import io
import json
import os
import shlex
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from rank_finder.cli import build_parser, build_rerun_command, main
from rank_finder.core import RankResult, SearchConfig
from rank_finder.terminal import banner, format_result, search_progress
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
        self.assertIn("Rank #2", stdout)
        self.assertRegex(stdout, r"Country\s+AU")
        self.assertRegex(stdout, r"Language\s+en")
        self.assertRegex(stdout, r"Device\s+Desktop")
        self.assertIn("Melbourne, Victoria, Australia", stdout)
        self.assertIn("Organic search results", stdout)
        self.assertNotIn("Organic Google results / SerpApi", stdout)
        self.assertRegex(stdout, r"Provider\s+SerpApi")
        self.assertIn("Run again", stdout)
        self.assertIn("python -m rank_finder", stdout)
        self.assertNotIn(API_KEY, stdout)
        self.assertEqual(session.get.call_args.kwargs["params"]["gl"], "au")
        session.close.assert_called_once()

    def test_named_search_terms_work_in_any_option_order(self):
        options = (
            ("--domain", "example.com"),
            ("--keyword", "example keyword"),
            ("--country", "US"),
            ("--json",),
        )
        for ordered in permutations(options):
            argv = [value for option in ordered for value in option]
            with self.subTest(argv=argv):
                code, stdout, stderr, session = self.run_cli(argv)
                config = json.loads(stdout)["config"]
                self.assertEqual(code, 0)
                self.assertIn("Run again", stderr)
                self.assertIn("--json", stderr)
                self.assertEqual(
                    (config["domain"], config["query"], config["country"]),
                    ("example.com", "example keyword", "us"),
                )
                self.assertEqual(session.get.call_args.kwargs["params"]["q"], "example keyword")

    def test_named_and_positional_search_terms_can_be_mixed(self):
        cases = [
            ["--domain", "example.com", "example keyword"],
            ["example keyword", "--domain", "example.com"],
            ["--keyword", "example keyword", "example.com"],
            ["example.com", "--keyword", "example keyword"],
            ["example.com", "--country", "AU", "example keyword"],
            ["--query", "example keyword", "--domain", "example.com"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                code, stdout, _, _ = self.run_cli([*argv, "--json"])
                config = json.loads(stdout)["config"]
                self.assertEqual(code, 0)
                self.assertEqual(
                    (config["domain"], config["query"]), ("example.com", "example keyword")
                )

    def test_named_keyword_can_look_like_a_domain(self):
        code, stdout, _, _ = self.run_cli(
            ["--keyword", "other.test", "--domain", "example.com", "--json"]
        )
        config = json.loads(stdout)["config"]
        self.assertEqual(code, 0)
        self.assertEqual((config["domain"], config["query"]), ("example.com", "other.test"))

    def test_missing_or_extra_search_terms_do_not_call_provider(self):
        cases = [
            ["example.com"],
            ["--domain", "example.com"],
            ["--keyword", "example keyword"],
            ["--country", "AU"],
            ["example.com", "example keyword", "extra"],
            ["example.com", "example keyword", "--domain", "other.test"],
            ["example.com", "example keyword", "--keyword", "other keyword"],
            ["extra", "--domain", "example.com", "--keyword", "example keyword"],
            ["--domain", "", "--keyword", "example keyword"],
            ["--domain", "example.com", "--keyword", ""],
        ]
        for argv in cases:
            with (
                self.subTest(argv=argv),
                patch("rank_finder.cli.SerpApiClient") as client,
                redirect_stderr(io.StringIO()) as stderr,
                self.assertRaises(SystemExit) as caught,
            ):
                main(argv)
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("error:", stderr.getvalue())
            client.assert_not_called()

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
        self.assertIn("Run again", stderr)
        self.assertIn("python -m rank_finder", stderr)
        self.assertEqual(
            (data["status"], data["rank"], data["config"]["device"]), ("found", 2, "mobile")
        )
        self.assertIn("checked_at", data)
        self.assertIn("created_at", data["searches"][0])
        self.assertNotIn(API_KEY, stdout + stderr)

    def test_rerun_command_preserves_settings_and_quotes_shell_characters(self):
        config = SearchConfig(
            "www.example.com",
            'plumber\'s tools; $(touch unwanted) & "repairs"',
            country="US",
            language="en-gb",
            location="New York, New York, United States",
            device="mobile",
            max_results=35,
            max_pages=2,
            include_subdomains=False,
            fresh=True,
        )
        with patch("rank_finder.cli.os", SimpleNamespace(name="posix")):
            command = build_rerun_command(
                config,
                json_output=True,
                history="my ranks/plumber's.sqlite3",
                timeout=12.5,
                retries=3,
            )
        arguments = shlex.split(command)
        self.assertEqual(arguments[:3], ["python", "-m", "rank_finder"])
        parsed = build_parser().parse_intermixed_args(arguments[3:])
        self.assertEqual(parsed.named_domain, config.domain)
        self.assertEqual(parsed.named_query, config.query)
        self.assertEqual(parsed.country, "US")
        self.assertEqual(parsed.language, config.language)
        self.assertEqual(parsed.location, config.location)
        self.assertEqual(parsed.device, config.device)
        self.assertEqual(parsed.max_results, config.max_results)
        self.assertEqual(parsed.max_pages, config.max_pages)
        self.assertEqual(parsed.history, "my ranks/plumber's.sqlite3")
        self.assertEqual((parsed.timeout, parsed.retries), (12.5, 3))
        self.assertTrue(parsed.exact_host)
        self.assertTrue(parsed.fresh)
        self.assertTrue(parsed.json)
        self.assertNotIn("\n", command)
        self.assertNotIn(API_KEY, command)

    def test_rerun_command_handles_values_starting_with_a_dash(self):
        config = SearchConfig("example.com", "-plumber", location="-Melbourne")
        with patch("rank_finder.cli.os", SimpleNamespace(name="posix")):
            command = build_rerun_command(config, history="-ranks.sqlite3")
        arguments = shlex.split(command)[3:]
        parsed = build_parser().parse_intermixed_args(arguments)
        self.assertEqual(parsed.named_query, "-plumber")
        self.assertEqual(parsed.location, "-Melbourne")
        self.assertEqual(parsed.history, "-ranks.sqlite3")

    def test_windows_rerun_command_quotes_powershell_values(self):
        config = SearchConfig("example.com", "plumber's tools; $env:PATH & repairs")
        with patch("rank_finder.cli.os", SimpleNamespace(name="nt")):
            command = build_rerun_command(config)
        self.assertTrue(command.startswith("python -m rank_finder "))
        self.assertIn("'--keyword' 'plumber''s tools; $env:PATH & repairs'", command)

    def test_printed_command_repeats_the_search_with_the_same_settings(self):
        arguments = [
            "--domain",
            "www.example.com",
            "--keyword=plumber's tools & repairs",
            "--country",
            "US",
            "--location",
            "New York, New York, United States",
            "--device",
            "mobile",
            "--max-results",
            "35",
            "--max-pages",
            "2",
            "--exact-host",
            "--fresh",
            "--timeout",
            "12.5",
            "--retries",
            "3",
            "--history",
            "my ranks.sqlite3",
        ]
        for json_output in (False, True):
            with (
                self.subTest(json_output=json_output),
                patch("rank_finder.cli.os", SimpleNamespace(name="posix", getenv=os.getenv)),
                patch("rank_finder.cli.save_result") as save,
            ):
                code, stdout, stderr, session = self.run_cli(
                    [*arguments, *(["--json"] if json_output else [])]
                )
                output = stderr if json_output else stdout
                command = next(
                    line.strip()
                    for line in output.splitlines()
                    if line.strip().startswith("python -m rank_finder ")
                )
                rerun_code, rerun_stdout, _, rerun_session = self.run_cli(shlex.split(command)[3:])
                self.assertEqual((code, rerun_code), (0, 0))
                self.assertEqual(save.call_count, 2)
                self.assertEqual(save.call_args_list[0].args[0], "my ranks.sqlite3")
                self.assertEqual(
                    save.call_args_list[0].args[1].config, save.call_args.args[1].config
                )
                self.assertEqual(
                    session.get.call_args.kwargs["params"],
                    rerun_session.get.call_args.kwargs["params"],
                )
                if json_output:
                    self.assertEqual(
                        json.loads(stdout)["config"], json.loads(rerun_stdout)["config"]
                    )
                else:
                    self.assertIn("Run again", rerun_stdout)

    def test_all_search_outcomes_include_a_rerun_command(self):
        cases = [
            ([], fixture(), 0),
            ([], fixture("empty_results"), 1),
            (
                ["--max-results", "100", "--max-pages", "1"],
                page([{"position": 1, "link": "https://other.test/"}], next_start=10),
                3,
            ),
        ]
        for options, data, expected_code in cases:
            with self.subTest(code=expected_code):
                code, stdout, _, _ = self.run_cli(
                    ["example.com", "keyword", *options], [response(data)]
                )
                self.assertEqual(code, expected_code)
                self.assertIn("Run again", stdout)
        code, stdout, _, _ = self.run_cli(["example.com", "keyword"], [response({}, 401)])
        self.assertEqual(code, 2)
        self.assertIn("Run again", stdout)

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
                        self.assertIn("Google Rank Finder", stderr)
                        self.assertIn("Setup Needed", stderr)
                        self.assertNotIn("Error:", stderr)
                        message = stderr
                    self.assertIn("SERPAPI_API_KEY environment variable is not set", message)
                    self.assertIn('export SERPAPI_API_KEY="your-serpapi-api-key"', message)
                    self.assertIn("replacing the placeholder with your API key", message)
                    self.assertIn("Exiting for now. Set your key, then run the app again.", message)
                    self.assertNotIn("guided setup", message)
                    self.assertNotIn("Traceback", message)
                    self.assertNotIn("\x1b[", message)
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
            ["--device", "all"],
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
            patch.dict(os.environ, {"SERPAPI_API_KEY": API_KEY}, clear=True),
            patch("sys.stdin.isatty", return_value=False),
            redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit) as caught,
        ):
            main([])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("Supply a domain and keyword", stderr.getvalue())

    def test_no_arguments_without_key_or_terminal_explains_key_setup(self):
        for value in (None, "", " \t "):
            environment = {} if value is None else {"SERPAPI_API_KEY": value}
            with (
                self.subTest(value=value),
                patch.dict(os.environ, environment, clear=True),
                patch("sys.stdin.isatty", return_value=False),
                patch("rank_finder.cli.SerpApiClient") as client,
                redirect_stdout(io.StringIO()) as stdout,
                redirect_stderr(io.StringIO()) as stderr,
            ):
                code = main([])
            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertNotIn("Guided setup needs a terminal", stderr.getvalue())
            self.assertIn("SERPAPI_API_KEY environment variable is not set", stderr.getvalue())
            self.assertIn('export SERPAPI_API_KEY="your-serpapi-api-key"', stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            client.assert_not_called()

    def test_interactive_missing_key_exits_before_first_prompt(self):
        for value in (None, "", " \t "):
            environment = {} if value is None else {"SERPAPI_API_KEY": value}
            with (
                self.subTest(value=value),
                patch("sys.stdin.isatty", return_value=True),
                patch(
                    "builtins.input", side_effect=AssertionError("Unexpected setup prompt")
                ) as prompt,
                patch(
                    "getpass.getpass", side_effect=AssertionError("Unexpected key prompt")
                ) as getpass,
                patch("rank_finder.cli.SerpApiClient") as client,
            ):
                code, stdout, stderr, session = self.run_cli([], environment=environment)
            self.assertEqual((code, stdout), (2, ""))
            self.assertIn("SERPAPI_API_KEY environment variable is not set", stderr)
            self.assertIn('export SERPAPI_API_KEY="your-serpapi-api-key"', stderr)
            self.assertIn("Exiting for now. Set your key, then run the app again.", stderr)
            self.assertNotIn("Traceback", stderr)
            self.assertIn("Setup Needed", stderr)
            self.assertNotIn("Error:", stderr)
            self.assertNotIn("Search terms", stderr)
            prompt.assert_not_called()
            getpass.assert_not_called()
            client.assert_not_called()
            session.get.assert_not_called()

    def test_interactive_defaults_use_environment_key(self):
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("builtins.input", side_effect=["example.com", "example keyword", *([""] * 9)]),
            patch("getpass.getpass") as getpass,
        ):
            code, stdout, stderr, session = self.run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("Rank #2", stdout)
        self.assertIn("[AU]", stderr)
        self.assertIn("https://serpapi.com/google-countries", stderr)
        self.assertIn("Language codes: https://serpapi.com/google-languages", stderr)
        self.assertEqual(session.get.call_args.kwargs["params"]["gl"], "au")
        self.assertIn("including retries", stderr)
        self.assertIn("Searching Google", stderr)
        self.assertNotIn("Starting search", stderr)
        for example in [
            "e.g. amazon.com.au | https://www.amazon.com.au",
            "e.g. shoes | running shoes",
            "e.g. AU for Australia",
            "e.g. en for English",
            "e.g. Melbourne | Victoria",
            "e.g. ranks.sqlite3",
        ]:
            self.assertIn("    " + example, stderr.splitlines())
        for example, reference in [
            ("e.g. AU for Australia", "Country codes: https://serpapi.com/google-countries"),
            ("e.g. en for English", "Language codes: https://serpapi.com/google-languages"),
        ]:
            self.assertIn(f"    {example}\n    {reference}\n", stderr)
        self.assertIn("City or region (optional)", stderr)
        self.assertIn("History file (optional)", stderr)
        self.assertIn(
            "  History file (optional)\n"
            "    e.g. ranks.sqlite3\n"
            "    Save this result to a local SQLite file.\n",
            stderr,
        )
        self.assertNotIn("[optional]", stderr)
        expected_hints = [
            ("Choose: desktop | mobile | tablet", "Only one device per search."),
            (
                "Choose: a whole number from 1 to 1000",
                "Set the highest organic position to check.",
            ),
            ("Choose: yes | no", "Include www and other subdomains."),
            ("Choose: yes | no", "Bypass cached results, which can use more search credits."),
            ("Choose: text | json", ""),
        ]
        self.assertEqual(
            [line.strip() for line in stderr.splitlines() if "Choose:" in line],
            [hint[0] for hint in expected_hints],
        )
        for choices, description in expected_hints:
            hint = f"    {choices}\n"
            if description:
                hint += f"    {description}\n"
            self.assertIn(hint, stderr)
        config = build_parser().parse_intermixed_args(shlex.split("example.com keyword"))
        self.assertEqual((config.country, config.language, config.device), ("au", "en", "desktop"))
        for default in ("[AU]", "[en]", "[desktop]", "[100]", "[yes]", "[no]", "[text]"):
            self.assertIn(default, stderr)
        params = session.get.call_args.kwargs["params"]
        self.assertEqual((params["gl"], params["hl"], params["device"]), ("au", "en", "desktop"))
        self.assertEqual(params["no_cache"], "false")
        self.assertNotIn("location", params)
        self.assertIn("Domain and subdomains", stdout)
        self.assertRegex(stdout, r"Search limit\s+Top 100 positions")
        for option in ("--exact-host", "--fresh", "--history"):
            self.assertNotIn(option, stdout)
        self.assertNotIn("For example", stderr)
        self.assertNotIn("such as", stderr)
        self.assertIn("Run again", stdout)
        getpass.assert_not_called()

    def test_language_help_links_to_supported_codes_without_changing_default(self):
        parser = build_parser()
        self.assertIn("https://serpapi.com/google-languages", parser.format_help())
        self.assertEqual(parser.parse_args(["example.com", "keyword"]).language, "en")

    def test_interactive_settings_use_environment_key(self):
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
        ):
            code, stdout, stderr, session = self.run_cli(
                [],
                [response(page([{"position": 1, "link": "https://example.com/"}]))],
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
        self.assertNotIn("SERPAPI_API_KEY environment variable is not set", stderr)

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
            "Choose: desktop | mobile | tablet.",
            "whole number",
            "Choose: yes | no | y | n.",
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

    def test_cancelling_during_a_search_closes_the_client(self):
        with patch("rank_finder.cli.find_rank", side_effect=KeyboardInterrupt):
            code, stdout, stderr, session = self.run_cli(["example.com", "keyword"])
        self.assertEqual((code, stdout), (130, ""))
        self.assertIn("Searching Google", stderr)
        self.assertIn("Cancelled.", stderr)
        self.assertNotIn("Traceback", stderr)
        session.close.assert_called_once()


class TerminalTests(unittest.TestCase):
    def test_found_result_shows_rank_directly_above_url(self):
        for rank in (1, 12, 100):
            with self.subTest(rank=rank), patch.dict(os.environ, {"NO_COLOR": "1"}):
                result = RankResult(
                    SearchConfig("example.com", "keyword"),
                    status="found",
                    rank=rank,
                    url="https://example.com/",
                )
                output = format_result(result)
            self.assertIn(f"  Rank #{rank}\n  https://example.com/\n", output)
            self.assertNotIn(f"#{rank}  Match found", output)

    def test_search_progress_is_static_for_redirected_or_dumb_output(self):
        for is_terminal, term in [(False, "xterm"), (True, "dumb")]:
            stream = io.StringIO()
            with (
                self.subTest(is_terminal=is_terminal, term=term),
                patch.object(stream, "isatty", return_value=is_terminal),
                patch.dict(os.environ, {"TERM": term}, clear=True),
                patch("rank_finder.terminal.Thread") as worker,
            ):
                with search_progress(
                    SearchConfig("example.com", "keyword", max_results=25, max_pages=3),
                    retries=2,
                    stream=stream,
                ):
                    self.assertIn("Searching Google", stream.getvalue())
            output = stream.getvalue()
            self.assertIn("up to 25 positions across up to 3 pages", output)
            self.assertIn("At most 9 HTTP requests including retries.", output)
            self.assertNotIn("\r", output)
            self.assertNotIn("\x1b[", output)
            worker.assert_not_called()

    def test_search_progress_animates_elapsed_time_without_colour(self):
        stream = io.StringIO()
        with (
            patch.object(stream, "isatty", return_value=True),
            patch.dict(os.environ, {"TERM": "xterm", "NO_COLOR": "1"}, clear=True),
            patch("rank_finder.terminal.Event") as stopped,
            patch("rank_finder.terminal.Thread") as worker,
            patch("rank_finder.terminal.monotonic", side_effect=[10.0, 10.0, 10.2]),
            patch(
                "rank_finder.terminal.shutil.get_terminal_size",
                return_value=os.terminal_size((80, 24)),
            ),
        ):
            stopped.return_value.wait.side_effect = [False, True]
            with search_progress(SearchConfig("example.com", "keyword"), 1, stream=stream):
                worker.call_args.kwargs["target"]()
            stopped.return_value.set.assert_called_once()
            worker.return_value.start.assert_called_once()
            worker.return_value.join.assert_called_once()
        output = stream.getvalue()
        self.assertIn("| Searching Google... 0.0s", output)
        self.assertIn("/ Searching Google... 0.2s", output)
        self.assertNotIn("\x1b[", output)
        self.assertTrue(output.endswith("\r" + " " * 79 + "\r"))

    def test_search_progress_keeps_animation_within_narrow_terminals(self):
        stream = io.StringIO()
        with (
            patch.object(stream, "isatty", return_value=True),
            patch.dict(os.environ, {"TERM": "xterm", "NO_COLOR": "1"}, clear=True),
            patch("rank_finder.terminal.Event") as stopped,
            patch("rank_finder.terminal.Thread") as worker,
            patch(
                "rank_finder.terminal.shutil.get_terminal_size",
                return_value=os.terminal_size((24, 24)),
            ),
        ):
            stopped.return_value.wait.return_value = True
            with search_progress(SearchConfig("example.com", "keyword"), 1, stream=stream):
                worker.call_args.kwargs["target"]()
        animation = stream.getvalue().split("\r")[1:]
        self.assertTrue(any("| Searching Google" in frame for frame in animation))
        self.assertTrue(all(len(frame) <= 23 for frame in animation))

    def test_search_progress_cleans_up_after_cancellation_or_failure(self):
        for error in (KeyboardInterrupt, RuntimeError):
            stream = io.StringIO()
            with (
                self.subTest(error=error),
                patch.object(stream, "isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm"}, clear=True),
                patch("rank_finder.terminal.Event") as stopped,
                patch("rank_finder.terminal.Thread") as worker,
            ):
                with self.assertRaises(error):
                    with search_progress(SearchConfig("example.com", "keyword"), 1, stream=stream):
                        raise error()
                stopped.return_value.set.assert_called_once()
                worker.return_value.join.assert_called_once()
                self.assertTrue(stream.getvalue().endswith("\r"))

    def test_coverage_separates_search_limit_progress_and_match_page(self):
        result = RankResult(
            SearchConfig("example.com", "keyword"),
            status="found",
            rank=11,
            url="https://example.com/",
            page=2,
            results_checked=11,
            deepest_rank_checked=11,
            pages_checked=2,
            stop_reason="match",
        )
        output = format_result(result)
        self.assertRegex(output, r"Search limit\s+Top 100 positions")
        self.assertRegex(output, r"Checked through\s+Position 11")
        self.assertRegex(output, r"Pages fetched\s+2\n")
        self.assertRegex(output, r"Match found on\s+Page 2")
        self.assertNotIn("of top", output)
        self.assertNotIn("; match on page", output)

    def test_coverage_without_a_match_omits_the_match_page(self):
        result = RankResult(
            SearchConfig("example.com", "keyword"),
            deepest_rank_checked=10,
            pages_checked=1,
        )
        output = format_result(result)
        self.assertRegex(output, r"Checked through\s+Position 10")
        self.assertRegex(output, r"Pages fetched\s+1\n")
        self.assertNotIn("Match found on", output)

    def test_coverage_without_results_does_not_claim_a_position_was_checked(self):
        result = RankResult(SearchConfig("example.com", "keyword"), status="error")
        output = format_result(result)
        self.assertRegex(output, r"Search limit\s+Top 100 positions")
        self.assertRegex(output, r"Checked through\s+No organic positions checked")
        self.assertRegex(output, r"Pages fetched\s+0\n")
        self.assertNotIn("Position 0", output)
        self.assertNotIn("Match found on", output)

    def test_banner_uses_one_aligned_heading_and_matching_divider(self):
        with patch(
            "rank_finder.terminal.shutil.get_terminal_size", return_value=os.terminal_size((80, 24))
        ):
            output = banner("Organic search results", stream=io.StringIO())
        heading = "  Google Rank Finder | Organic search results"
        self.assertEqual(output.splitlines(), ["", heading, "  " + "-" * (len(heading) - 2)])

    def test_banner_stacks_the_heading_in_a_narrow_terminal(self):
        with patch(
            "rank_finder.terminal.shutil.get_terminal_size", return_value=os.terminal_size((32, 24))
        ):
            output = banner("Organic search results", stream=io.StringIO())
        self.assertEqual(
            output.splitlines(),
            ["", "  Google Rank Finder", "  Organic search results", "  " + "-" * 28],
        )
        self.assertTrue(all(len(line) <= 32 for line in output.splitlines()))

    def test_prominent_setup_banner_keeps_its_separate_message(self):
        output = banner("Setup Needed", stream=io.StringIO(), prominent=True)
        self.assertEqual(
            output.splitlines()[:4], ["", "  Google Rank Finder", "", "  Setup Needed"]
        )
