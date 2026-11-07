import copy
import json
from pathlib import Path
from unittest.mock import Mock

import requests

from rank_finder.serpapi import SerpApiClient

API_KEY = "review-secret-key"


def fixture(name="first_page"):
    return json.loads((Path(__file__).parent / "fixtures" / (name + ".json")).read_text())


def response(data=None, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode()
    result._content_consumed = True
    return result


def client_with(*responses, retries=0):
    session = Mock(spec=requests.Session)
    session.get.side_effect = list(responses)
    return SerpApiClient(API_KEY, session=session, retries=retries), session


def page(items, next_start=None):
    data = copy.deepcopy(fixture())
    data["organic_results"] = items
    data.pop("serpapi_pagination", None)
    if next_start is not None:
        data["serpapi_pagination"] = {
            "next": f"https://serpapi.com/search.json?start={next_start}&api_key={API_KEY}"
        }
    return data
