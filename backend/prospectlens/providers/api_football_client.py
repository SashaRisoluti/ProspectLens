"""Client HTTP per API-Football v3 con cache su disco, limite di frequenza e retry.

- La chiave arriva solo da API_FOOTBALL_KEY e non compare mai nei log o negli errori.
- Ogni risposta (anche gli errori di piano) è salvata in cache: ripetere uno script non
  consuma richieste. `refresh=True` ignora la cache.
- `budget` limita le richieste reali per esecuzione (il piano gratuito ne ha poche al giorno).
"""

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class ApiFootballError(RuntimeError):
    pass


class BudgetExhausted(ApiFootballError):
    """Raggiunto il budget di richieste di questa esecuzione o il limite giornaliero."""


def api_key_from_env() -> str:
    key = os.environ.get("API_FOOTBALL_KEY", "").strip().strip("'\"")
    if not key:
        raise ApiFootballError("API_FOOTBALL_KEY non impostata in .env")
    return key


def _errors(body: dict[str, Any]) -> dict[str, str]:
    err = body.get("errors") or {}
    return {str(k): str(v) for k, v in err.items()} if isinstance(err, dict) else {}


class ApiFootballClient:
    def __init__(
        self,
        key: str,
        cache_dir: Path,
        *,
        min_interval: float = 6.5,  # piano gratuito: circa 10 richieste al minuto
        budget: int | None = None,
        refresh: bool = False,
    ) -> None:
        self._key = key
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.budget = budget
        self.refresh = refresh
        self.used = 0
        self.remaining_today: int | None = None
        self._last = 0.0

    def _cache_path(self, endpoint: str, params: dict[str, Any]) -> Path:
        query = urllib.parse.urlencode(sorted(params.items()))
        digest = hashlib.sha1(query.encode()).hexdigest()[:16]
        return self.cache_dir / endpoint.strip("/").replace("/", "_") / f"{digest}.json"

    def get(
        self, endpoint: str, params: dict[str, Any] | None = None, ttl: timedelta | None = None
    ) -> dict[str, Any]:
        """GET con cache. ttl=None: la risposta in cache non scade (stagioni concluse)."""
        params = params or {}
        path = self._cache_path(endpoint, params)
        if path.exists() and not self.refresh:
            cached: dict[str, Any] = json.loads(path.read_text())
            age = datetime.now(UTC) - datetime.fromisoformat(cached["fetched_at"])
            if ttl is None or age < ttl:
                return dict(cached["body"])
        body = self._fetch(endpoint, params)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "endpoint": endpoint,
                    "params": params,
                    "body": body,
                }
            )
        )
        return body

    def _fetch(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{BASE_URL}/{endpoint.strip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(5):
            if self.budget is not None and self.used >= self.budget:
                raise BudgetExhausted(f"budget di {self.budget} richieste esaurito")
            if self.remaining_today == 0:
                raise BudgetExhausted("limite giornaliero del fornitore raggiunto")
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.used += 1
            request = urllib.request.Request(url, headers={"x-apisports-key": self._key})
            try:
                with urllib.request.urlopen(request, timeout=30) as resp:
                    remaining = resp.headers.get("x-ratelimit-requests-remaining")
                    if remaining is not None and remaining.isdigit():
                        self.remaining_today = int(remaining)
                    body: dict[str, Any] = json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                if exc.code not in _RETRYABLE_HTTP:
                    raise ApiFootballError(f"{endpoint}: HTTP {exc.code}") from None
                log.warning("%s: HTTP %s, nuovo tentativo", endpoint, exc.code)
            except (urllib.error.URLError, TimeoutError) as exc:
                log.warning("%s: errore di rete (%s), nuovo tentativo", endpoint, exc)
            else:
                errors = _errors(body)
                if "requests" in errors:
                    self.remaining_today = 0
                    raise BudgetExhausted(f"limite giornaliero: {errors['requests']}")
                if "rateLimit" not in errors:
                    return body
                log.warning("%s: limite al minuto, attendo", endpoint)
            time.sleep(min(60.0, 5.0 * 2**attempt))
        raise ApiFootballError(f"{endpoint}: troppi tentativi falliti")
