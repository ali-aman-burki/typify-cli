"""Type4Py REST API client."""

from __future__ import annotations

import requests

DEFAULT_API_URL = "https://type4py.ali-aman.ca/api/predict?tc=0"


def predict(source: str, api_url: str = DEFAULT_API_URL, timeout: int = 60) -> dict | None:
    """POST Python source to the Type4Py API and return the response dict, or None on error."""
    try:
        r = requests.post(api_url, data=source.encode("utf-8"), timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            return None
        return data.get("response")
    except Exception:
        return None
