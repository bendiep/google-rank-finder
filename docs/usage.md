# Usage guide

[Back to the README](../README.md)

[Guided setup](#guided-setup) · [Options](#options) · [How ranking works](#how-ranking-works) · [JSON and exit codes](#json-and-exit-codes) · [History](#history) · [Request usage](#request-usage)

## Guided setup

Run `python google-rank-finder.py` without arguments in a terminal. Setup asks
for the website, keyword, country, language, city or region, device and search
depth. It also offers exact-host matching, fresh results, JSON output and an
optional SQLite history file.

Press Enter to accept a default or Ctrl+C to cancel. You can correct invalid
entries at the prompt. Setup uses `SERPAPI_API_KEY` if set. Otherwise, it prompts
privately for a key, uses it for the current run and does not save it.

If the variable is missing or empty, the app explains this and shows:

```sh
export SERPAPI_API_KEY="your-serpapi-api-key"
```

Replace the placeholder with your key and rerun your search. Guided setup also
lets you enter a key privately for the current run.

Defaults are AU, English, desktop, subdomains included and a maximum depth of
100. SerpApi chooses the location unless you supply one. For comparable checks,
use the same city, country, language and device each time. Give a precise
location such as `Melbourne, Victoria, Australia`.

Questions are grouped into search terms, search settings and output, with
defaults in brackets and hints beneath each question. The country question links
to [SerpApi's supported country codes](https://serpapi.com/google-countries).

Text results show the rank and matched URL first, followed by aligned search,
coverage and timing details. Headings and outcomes use colour in terminals.
Redirected output stays plain text. Set `NO_COLOR=1` to disable terminal colours.

## Options

```sh
python google-rank-finder.py DOMAIN "KEYWORD" [OPTIONS]
```

`DOMAIN` accepts a hostname or full HTTP URL. Matching uses the hostname only,
so a URL path does not restrict the check to that page.

### Search settings

| Option | What it controls | Default |
| --- | --- | --- |
| `--country` | Two-letter [search country code](https://serpapi.com/google-countries), such as `AU` or `US` | `au` |
| `--location` | Search origin, preferably a city and region | Provider-selected |
| `--language` | Interface language, such as `en` or `en-gb` | `en` |
| `--device` | `desktop`, `mobile` or `tablet` | `desktop` |
| `--max-results`, `--depth` | Highest organic position to examine, from 1 to 1000 | `100` |
| `--max-pages`, `--max_pages` | Maximum pages to fetch, from 1 to 100 | Depth divided by 10, rounded up |
| `--exact-host` | Match only the supplied hostname | Subdomains included |
| `--fresh` | Bypass SerpApi's cache | Cache allowed |

Checking `example.com` includes `www.example.com` and other subdomains by
default. With `--exact-host`, only `example.com` matches. To check only
`www.example.com`, supply that hostname and `--exact-host`.

When you supply only `--max-pages`, the depth is ten times the page budget.
For example, `--max_pages 3` searches up to position 30. When you supply both
limits, the search stops at the first one reached.

### Output and requests

| Option | What it controls | Default |
| --- | --- | --- |
| `--json` | Write a structured JSON result to stdout | Text output |
| `--history FILE` | Append the observation to a local SQLite file | Disabled |
| `--timeout` | Timeout per HTTP request in seconds, greater than 0 and at most 300 | `30` |
| `--retries` | Retries per page for connection failures and HTTP 500, 502, 503 or 504, from 0 to 3 | `1` |

Run `python google-rank-finder.py --help` for built-in help. You can also run
the package with `python -m rank_finder`.

## How ranking works

The checker examines SerpApi's top-level `organic_results` in position order
and returns the first matching hostname. Rank is the provider's page-local
organic position plus that page's result offset. Pagination follows the
provider's next-page metadata, so pages do not have to contain ten results.
Results without a usable link count toward the checked positions but cannot
match a domain.

The result measures an organic search snapshot under the requested conditions.
It excludes ads, Maps listings, AI Overview citations, nested sitelinks and
pixel visibility. It also differs from Search Console's average position
across impressions. Google users can see different positions for the same query.

The output reports the actual number of organic results checked and the deepest
position examined. A depth of 100 is a ceiling. Google may return fewer results
or stop pagination earlier. If the page budget runs out while more eligible
pages remain, the status is `incomplete`.

Text output identifies the location SerpApi used when available and notes if
Google displayed a different query. The client requests no spelling correction,
but Google can still substitute a query when the original has no results.
Review these observations when interpreting a rank.

## JSON and exit codes

```sh
python google-rank-finder.py example.com "example keyword" --country AU --json > result.json
```

Search output on stdout is one JSON object. Interactive prompts and setup
errors use stderr, except that a missing API key with `--json` returns a short
JSON error object on stdout.

| Fields | Contents |
| --- | --- |
| `provider`, `measurement` | `serpapi` and `organic_position` |
| `status`, `rank`, `url`, `page` | Outcome, matched position, URL and fetched page number |
| `config` | Domain, query and search settings |
| `checked_at` | UTC retrieval time |
| `results_checked`, `deepest_rank_checked` | Actual coverage of the search |
| `pages_checked`, `requests_made` | Successful pages checked and HTTP requests made |
| `stop_reason`, `error` | Why the search stopped and any provider error |
| `searches` | Per-page offsets, search IDs, provider timestamps, locations and displayed queries |

API keys and pagination URLs are excluded. `searches[].created_at` is the
provider's search time. It can be earlier than `checked_at` when results are
cached.

| Exit code | Meaning |
| --- | --- |
| `0` | A matching organic result was found |
| `1` | No match in the successfully checked positions |
| `2` | Invalid setup, provider failure, or failure to save requested history |
| `3` | Incomplete search due to a page limit or failure after partial progress |
| `130` | Cancelled with Ctrl+C |

Argument errors use argparse's normal stderr output, including with `--json`.
If saving history fails, the measured result is still printed and the process
exits with code 2. Scripts should check both the exit code and result status.

## History

```sh
python google-rank-finder.py example.com "example keyword" \
  --country AU --location "Melbourne, Victoria, Australia" \
  --history ranks.sqlite3
```

The SQLite file contains an append-only `rank_checks` table with `checked_at`,
`domain`, `query`, `status`, `rank` and the complete `result_json`. Its parent
directory must already exist. API keys are not saved.

Failed and incomplete searches retain their statuses. Inspect them before
treating a missing rank as a ranking drop. For recurring checks, run the same
command from your scheduler and keep the search settings consistent.

## Request usage

The checker stops after a match, the depth limit, the page limit or the end of
pagination. Each page can make at most `1 + retries` HTTP requests. With the
defaults, one lookup makes at most 20 requests across ten pages.

Authentication and quota errors are not retried. Retries use a bounded
exponential delay and can increase usage.

For planning, 100 keywords checked daily at ten pages each is up to 30,000
requests in a 30-day month before retries, devices or additional locations.
HTTP request counts differ from billed searches. `--fresh` bypasses the cache.
See [SerpApi's documentation](https://serpapi.com/search-api) for cache and
billing rules.

## Code layout

| File | Responsibility |
| --- | --- |
| [`core.py`](../rank_finder/core.py) | Search settings, hostname matching and ranking |
| [`serpapi.py`](../rank_finder/serpapi.py) | HTTP requests and response parsing |
| [`cli.py`](../rank_finder/cli.py) | Arguments and guided setup |
| [`terminal.py`](../rank_finder/terminal.py) | Terminal styles and result formatting |
| [`history.py`](../rank_finder/history.py) | Optional SQLite persistence |
