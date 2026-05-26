"""
connectors/base.py — Base class for all real-data source connectors.

Design principle: NEVER fabricate data. If a source is unreachable or
returns unexpected content, the connector raises an exception. There are
no hardcoded numeric fallbacks anywhere in this package.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd
import requests


logger = logging.getLogger(__name__)


class SourceUnavailableError(RuntimeError):
    """Raised when a real data source cannot be reached or returns bad data.

    The pipeline deliberately fails rather than substituting fabricated values.
    """


class BaseConnector(ABC):
    """Abstract connector. Subclasses implement fetch() to return a DataFrame
    sourced entirely from a real, public endpoint."""

    #: Human-readable source name, e.g. "EPA Envirofacts GHGRP"
    source_name: str = "unnamed source"
    #: The canonical public URL the data originates from (for provenance logging)
    source_url: str = ""

    def __init__(self, raw_dir: Path, timeout: int = 60,
                 max_retries: int = 3, backoff: float = 2.0):
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff

    # -- HTTP helper with retry/backoff -------------------------------------

    def _get(self, url: str, params: dict | None = None,
             expect: str = "text") -> requests.Response:
        """GET with retries. Raises SourceUnavailableError on persistent failure.

        No silent fallback: a failure here stops the pipeline.
        """
        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"[{self.source_name}] GET {url} (attempt {attempt}/{self.max_retries})")
                resp = requests.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                if not resp.content:
                    raise SourceUnavailableError(f"Empty response body from {url}")
                return resp
            except (requests.RequestException, SourceUnavailableError) as exc:
                last_exc = exc
                logger.warning(f"[{self.source_name}] attempt {attempt} failed: {exc}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff ** attempt)
        raise SourceUnavailableError(
            f"[{self.source_name}] could not fetch {url} after "
            f"{self.max_retries} attempts. Last error: {last_exc}. "
            f"This source must be reachable; no fabricated fallback is used."
        )

    # -- Provenance ----------------------------------------------------------

    def provenance(self) -> dict:
        """Return a dict documenting where this data came from."""
        return {
            "source_name": self.source_name,
            "source_url": self.source_url,
            "retrieved_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }

    # -- Interface -----------------------------------------------------------

    @abstractmethod
    def fetch(self) -> pd.DataFrame:
        """Fetch real data and return as a DataFrame. Must raise on failure."""
        raise NotImplementedError
