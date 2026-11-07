# Google Rank Finder

A command-line tool for checking Google search rankings using [SerpApi](https://serpapi.com/).

Finds a website’s highest organic ranking for a given keyword or phrase and returns detailed search results.

Supports configurable search settings, result depth, subdomain matching, and caching. Results can be exported as JSON or stored in a local SQLite database for historical tracking.

## 📋 Requirements

- Python 3.10 or newer
- [SerpApi API key](https://serpapi.com/manage-api-key)

## 📦 Setup

```sh
# Clone the repository and move into its directory.
git clone https://github.com/bendiep/google-rank-finder.git
cd google-rank-finder

# Create and activate a virtual environment.
python3 -m venv .venv
source .venv/bin/activate

# Install the project dependencies.
python -m pip install -r requirements.txt

# Set your API key:
export SERPAPI_API_KEY="your-serpapi-api-key"
```

## ▶️ Usage

### 1. Run the script and follow the prompts

```sh
python google-rank-finder.py
```

Enter your website and keyword. Press Enter to accept the default settings.

### 2. Pass the domain and keyword in the command

```sh
python google-rank-finder.py --domain example.com --keyword "running shoes"
```

The defaults are Australia, English, desktop and up to 100 organic positions.

Add `--json` to export JSON or `--history ranks.sqlite3` to save a local history.

Run `python google-rank-finder.py --help` for all flags and defaults.

## 🛠️ Development

### 1. Install development dependencies

```sh
python -m pip install -r requirements-dev.txt
```

### 2. Check the code

```sh
# Check for lint errors.
python -m ruff check .

# Check code formatting.
python -m ruff format --check .
```

### 3. Run the tests

```sh
python -m unittest discover -v
```

Note: Tests don't need an API key or make live searches.

## 📝 License

[MIT](LICENSE).
