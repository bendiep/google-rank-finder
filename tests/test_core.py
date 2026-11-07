import unittest
from dataclasses import replace

from rank_finder.core import SearchConfig, matches_domain, normalize_domain


class DomainTests(unittest.TestCase):
    def test_normalizes_domains_and_urls(self):
        for value, expected in [
            (" EXAMPLE.COM. ", "example.com"),
            ("https://WWW.Example.com/path?q=value", "www.example.com"),
            ("bücher.de", "xn--bcher-kva.de"),
            ("https://example.com:443/path", "example.com"),
        ]:
            with self.subTest(value=value):
                self.assertEqual(normalize_domain(value), expected)

    def test_rejects_invalid_domain_inputs(self):
        for value in [
            "",
            "localhost",
            "bad domain.com",
            "-bad.com",
            "example..com",
            "ftp://example.com",
            "https://user:password@example.com",
            "example.com:bad",
            "example.com:0",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_domain(value)

    def test_matches_hostname_boundaries(self):
        for url in [
            "https://example.com/",
            "https://WWW.Example.com/path",
            "https://blog.example.com/",
        ]:
            with self.subTest(url=url):
                self.assertTrue(matches_domain(url, "example.com"))
        for url in [
            "https://notexample.com/",
            "https://example.com.other.test/",
            "https://other.test/?next=example.com",
            "https://other.test/example.com",
            "https://example.com@other.test/",
            "not a URL",
            "ftp://example.com/",
        ]:
            with self.subTest(url=url):
                self.assertFalse(matches_domain(url, "example.com"))

    def test_exact_host_excludes_subdomains(self):
        self.assertTrue(matches_domain("https://example.com/", "example.com", False))
        self.assertFalse(matches_domain("https://www.example.com/", "example.com", False))

    def test_unicode_result_matches_normalized_domain(self):
        self.assertTrue(matches_domain("https://bücher.de/books", normalize_domain("bücher.de")))


class ConfigTests(unittest.TestCase):
    def test_normalizes_search_context(self):
        config = SearchConfig(
            "Example.COM", " keyword ", country=" AU ", language="EN-GB", location=" Melbourne "
        )
        self.assertEqual(
            (config.domain, config.query, config.country, config.language, config.location),
            ("example.com", "keyword", "au", "en-gb", "Melbourne"),
        )

    def test_invalid_settings_fail_before_searching(self):
        config = SearchConfig("example.com", "keyword")
        for changes in [
            {"query": " "},
            {"country": "Australia"},
            {"language": "English"},
            {"device": "watch"},
            {"max_results": 0},
            {"max_results": 1001},
            {"max_pages": 0},
            {"max_pages": 101},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(config, **changes)
