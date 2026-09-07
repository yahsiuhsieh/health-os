from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class HttpError(RuntimeError):
    status_code: int
    body: str
    url: str

    def __str__(self) -> str:
        return f"HTTP {self.status_code} for {self.url}: {self.body[:500]}"


class JsonHttpClient:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str | int] | None = None,
        json_body: Any | None = None,
        form_body: dict[str, str] | None = None,
        timeout: int = 30,
        retries: int = 2,
    ) -> Any:
        if params:
            query = urllib.parse.urlencode(params)
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{query}"

        body: bytes | None = None
        request_headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":"), sort_keys=True).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif form_body is not None:
            body = urllib.parse.urlencode(form_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

        request = urllib.request.Request(url=url, method=method.upper(), data=body)
        for key, value in request_headers.items():
            request.add_header(key, value)

        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8")
                    if raw == "":
                        return {}
                    return json.loads(raw)
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                    time.sleep(2**attempt)
                    continue
                raise HttpError(exc.code, raw, url) from exc
            except urllib.error.URLError:
                if attempt < retries:
                    time.sleep(2**attempt)
                    continue
                raise

