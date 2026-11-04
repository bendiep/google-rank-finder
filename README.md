# Google Rank Finder

Check Google rankings with [SerpApi](https://serpapi.com/).

## 🔍 What it does

- Finds your website's highest organic position for a keyword.
- Lets you choose the country, location, language and device.
- Exports results as JSON or saves a local search history.

---

## 📦 Installation

You'll need Python 3.10 or newer and a [SerpApi API key](https://serpapi.com/manage-api-key).

```sh
git clone https://github.com/bendiep/google-rank-finder.git
cd google-rank-finder
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## ▶️ Usage

Set your API key:

```sh
export SERPAPI_API_KEY="your-serpapi-api-key"
```

Start the guided setup:

```sh
python google-rank-finder.py
```

Enter your website and keyword. Press Enter to accept the default settings.

Or run a search directly:

```sh
python google-rank-finder.py --domain example.com --keyword "running shoes"
```

The defaults are Australia, English, desktop and up to 100 organic positions.

Add `--json` to export JSON or `--history ranks.sqlite3` to save a local history.

Run `python google-rank-finder.py --help` for all flags and defaults.

## 🛠️ Development

```sh
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m unittest discover -v
```

Tests don't need an API key or make live searches.

## 📝 License

[MIT](LICENSE).
