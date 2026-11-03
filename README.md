# Google Rank Finder

Check where a website ranks in Google's organic results for a keyword or phrase.
Search by country, city, language and device using [SerpApi](https://serpapi.com/).

Run a guided setup in your terminal, use command-line arguments in scripts, or
save results as JSON and SQLite history.

[Quick start](#quick-start) · [Examples](#examples) · [Understanding results](#understanding-results)

## Quick start

You'll need Python 3.10 or newer and a [SerpApi API key](https://serpapi.com/manage-api-key).

### 1. Install

```sh
git clone https://github.com/bendiep/python-google-rank-finder.git
cd python-google-rank-finder
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2. Run your first check

Set your key and start the guided setup:

```sh
export SERPAPI_API_KEY="your-serpapi-api-key"
python google-rank-finder.py
```

Enter your website and keyword, then choose your search settings. Press Enter
to accept a default. If `SERPAPI_API_KEY` is missing or empty, the app shows
the setup command and exits with code `2` before asking any questions.

For command-line use, set your key and supply the website and keyword:

```sh
export SERPAPI_API_KEY="your-serpapi-api-key"
python google-rank-finder.py --domain example.com --keyword "example keyword"
```

Named options can go in any order, including `--domain` and `--keyword`:

```sh
python google-rank-finder.py --keyword "example keyword" --country AU --domain example.com
```

The positional form, `python google-rank-finder.py example.com "example keyword"`,
also works. Without names, the domain must come before the keyword.

You can also use `python -m rank_finder` in place of `python google-rank-finder.py`.

By default, a check uses AU, English, desktop and a maximum depth of 100 organic
positions. It includes subdomains and lets SerpApi choose the location.
Use `--country` to change the country. See
[SerpApi's country codes](https://serpapi.com/google-countries) for supported values.

## Examples

### Check a location and device

```sh
python google-rank-finder.py --keyword "example keyword" --domain example.com \
  --country AU \
  --location "Melbourne, Victoria, Australia" \
  --language en \
  --device mobile \
  --max-results 100
```

### Match one hostname

```sh
python google-rank-finder.py www.example.com "example keyword" --exact-host
```

Normally, `example.com` also matches `www.example.com` and other subdomains.
`--exact-host` matches only the hostname you supply. You can supply a full HTTP
URL, but its path does not restrict the search to that page.

### Export JSON or keep a history

```sh
python google-rank-finder.py example.com "example keyword" --json > result.json
python google-rank-finder.py example.com "example keyword" --history ranks.sqlite3
```

JSON includes the rank, matched URL, search settings, timestamps and search
status. History appends each check to a local SQLite file. API keys are excluded
from both. For recurring checks, run the same command from your scheduler.

Run `python google-rank-finder.py --help` for all flags and defaults.

## Understanding results

A successful check shows the highest matching organic position and URL. For
example, the beginning of the output might look like this:

```text
  Google Rank Finder | Organic search results
  -------------------------------------------

  Rank #2
  https://www.example.com/about

  Search
    Provider          SerpApi
    Website           example.com
    Keyword           example keyword
    Country           AU
    Language          en
    Device            Mobile
    Location          Melbourne, Victoria, Australia
```

The coverage and timing sections report the results and pages checked, deepest
position examined, HTTP requests, stop reason and retrieval time. Terminal
colours highlight headings and the outcome. Redirected text has no colour codes;
set `NO_COLOR=1` to disable colours in a terminal too.

Each check ends with a **Run again** command you can copy, paste and edit for
your next search. It preserves your search, output, history and request settings
without including your API key. On Windows, use PowerShell for this command.
With JSON output, the command goes to stderr so stdout stays valid JSON and
the JSON format remains unchanged.

| Status | Meaning | Exit code |
| --- | --- | --- |
| `found` | A matching organic result was found | `0` |
| `not_found` | No match in the successfully checked positions | `1` |
| `error` | The search failed before any page was checked | `2` |
| `incomplete` | A page limit or later failure stopped the search | `3` |

A depth of 100 is a ceiling. Google may return fewer results. Check the actual
depth and status before treating a missing match as a ranking drop.

Rank is a snapshot for the chosen search settings. Keep the city, country,
language and device consistent when comparing checks. Ads, Maps listings,
AI Overview citations and nested sitelinks are outside this measurement.

## Development

```sh
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m unittest discover -v
```

Tests use local fixtures and mocked HTTP responses. They need no API key and
make no live searches. GitHub Actions runs these checks on Linux with Python
3.10, 3.12 and 3.14, and on Windows with Python 3.12.

## License

[MIT](LICENSE).
