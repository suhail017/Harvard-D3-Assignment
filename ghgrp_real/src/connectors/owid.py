"""
connectors/owid.py — Our World in Data CO2 connector (REAL DATA)

Source: Our World in Data CO2 & GHG dataset (Global Carbon Project + others)
  URL:  https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv
  Repo: https://github.com/owid/co2-data
  License: CC-BY 4.0

This is a genuine live download and works from any network with GitHub access
(including the restricted authoring sandbox). No API key required.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd

from .base import BaseConnector, SourceUnavailableError

logger = logging.getLogger(__name__)

OWID_CO2_URL = "https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv"


class OwidConnector(BaseConnector):
    source_name = "Our World in Data (CO2)"
    source_url = OWID_CO2_URL

    def __init__(self, raw_dir: Path, country: str = "United States",
                 year_min: int = 1960, year_max: int = 2023, **kwargs):
        super().__init__(raw_dir, **kwargs)
        self.country = country
        self.year_min = year_min
        self.year_max = year_max

    def fetch(self) -> pd.DataFrame:
        resp = self._get(OWID_CO2_URL, expect="text")
        full = pd.read_csv(io.StringIO(resp.text), low_memory=False)

        raw_path = self.raw_dir / "owid_co2.csv"
        full.to_csv(raw_path, index=False)
        logger.info(f"[{self.source_name}] saved raw → {raw_path} "
                    f"({len(full):,} rows × {full.shape[1]} cols)")

        if "country" not in full.columns or "year" not in full.columns:
            raise SourceUnavailableError(
                f"[{self.source_name}] unexpected schema: {list(full.columns)[:10]}")

        sub = full[(full["country"] == self.country) &
                   full["year"].between(self.year_min, self.year_max)].copy()
        if sub.empty:
            raise SourceUnavailableError(
                f"[{self.source_name}] no rows for {self.country} "
                f"{self.year_min}-{self.year_max}")

        logger.info(f"[{self.source_name}] {self.country}: {len(sub)} years")
        return sub
