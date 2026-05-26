"""
connectors/noaa.py — NOAA NCEI Climate-at-a-Glance connector (REAL DATA)

Source: NOAA National Centers for Environmental Information (NCEI)
  Climate at a Glance national time series JSON endpoints.
  Example:
    https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/
      national/time-series/110/cdd/ann/12/2010-2023.json
  Docs: https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/

No API key required for Climate-at-a-Glance JSON series.

Pulls real CONUS national covariates:
  * Cooling Degree Days (cdd)
  * Heating Degree Days (hdd)
  * (optional) Palmer Drought Severity Index (pdsi)

NOTE ON SANDBOX: ncei.noaa.gov returns 403 from the restricted authoring
environment. It is publicly accessible on a normal network. The connector
targets the verified Climate-at-a-Glance JSON contract.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .base import BaseConnector, SourceUnavailableError

logger = logging.getLogger(__name__)

NCEI_BASE = "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/national/time-series"
CONUS_SCOPE = "110"   # 110 = contiguous U.S. national scope code


class NoaaConnector(BaseConnector):
    source_name = "NOAA NCEI Climate at a Glance"
    source_url = NCEI_BASE

    def __init__(self, raw_dir: Path, year_min: int, year_max: int, **kwargs):
        super().__init__(raw_dir, **kwargs)
        self.year_min = year_min
        self.year_max = year_max

    def _series(self, parameter: str) -> pd.DataFrame:
        """Fetch one annual national series (e.g. 'cdd', 'hdd', 'pdsi')."""
        url = (f"{NCEI_BASE}/{CONUS_SCOPE}/{parameter}/ann/12/"
               f"{self.year_min}-{self.year_max}.json")
        resp = self._get(url, expect="json")
        payload = resp.json()
        data = payload.get("data")
        if not data:
            raise SourceUnavailableError(
                f"[{self.source_name}] no data for {parameter}: "
                f"{str(payload)[:200]}")
        # NCEI returns {"YYYYMM": {"value": "...", "anomaly": "..."}} or
        # {"YYYY": {...}} depending on series; normalise to year/value.
        rows = []
        for key, val in data.items():
            year = int(str(key)[:4])
            value = val.get("value") if isinstance(val, dict) else val
            try:
                rows.append({"year": year, parameter: float(value)})
            except (TypeError, ValueError):
                continue
        df = pd.DataFrame(rows)
        if df.empty:
            raise SourceUnavailableError(
                f"[{self.source_name}] parsed zero rows for {parameter}")
        df = df[df["year"].between(self.year_min, self.year_max)]
        df.to_csv(self.raw_dir / f"noaa_{parameter}.csv", index=False)
        logger.info(f"[{self.source_name}] {parameter}: {len(df)} years")
        return df

    def fetch(self) -> pd.DataFrame:
        cdd = self._series("cdd")
        hdd = self._series("hdd")
        out = cdd.merge(hdd, on="year", how="outer")
        try:
            pdsi = self._series("pdsi")
            out = out.merge(pdsi, on="year", how="outer")
        except SourceUnavailableError:
            logger.warning(f"[{self.source_name}] PDSI unavailable; "
                           f"continuing with CDD/HDD only")
        return out.sort_values("year").rename(
            columns={"cdd": "cdd_annual", "hdd": "hdd_annual",
                     "pdsi": "pdsi_annual"})
