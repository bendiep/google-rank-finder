# Google Rank Finder

A command-line tool for checking Google search rankings using [SerpApi](https://serpapi.com/).

Finds a website’s highest organic ranking for a given keyword or phrase and returns detailed search results.

## 📋 Requirements

- Python 3.10 or newer
- [SerpApi API key](https://serpapi.com/manage-api-key)

## 📦 Setup

```sh
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

### 2. Run with command-line arguments

```sh
python google-rank-finder.py --domain example.com --keyword "running shoes"
```

### 3. See all options

```sh
python google-rank-finder.py --help
```

## 📊 Results

Example output for `amazon.com.au` and `running shoes`.

```text
Google Rank Finder | Organic search results
-------------------------------------------

Rank #43
https://www.amazon.com.au/gp/bestsellers/sporting-goods/5044422051

Search
  Website           amazon.com.au
  Keyword           running shoes
  Country           AU
  Language          en
  Device            Desktop

Coverage
  Results checked   40
  Checked through   Position 43
  Pages fetched     5
  Stopped because   Match found
```

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
