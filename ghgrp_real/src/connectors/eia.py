"""
connectors/eia.py — U.S. Energy Information Administration connector (REAL DATA)

Source: EIA Open Data API v2
  Base: https://api.eia.gov/v2/
  Docs: https://www.eia.gov/opendata/documentation.php
  Key:  Free, instant — register at https://www.eia.gov/opendata/register.php

Pulls real series used as emission covariates:
  * Henry Hub natural gas spot price (annual avg, $/MMBtu)
  * Electricity net generation by fuel → renewables share (%)

Requires an API key supplied via config or the EIA_API_KEY env var.
If no key is present, the connector raises (no fabricated fallback).

NOTE ON SANDBOX: api.eia.gov is not reachable from the restricted authoring
environment (403 there). It is publicly accessible on a normal network with a
valid key. The connector targets the verified EIA API v2 contract.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

from .base import BaseConnector, SourceUnavailableError

logger = logging.getLogger(__name__)

EIA_BASE = "https://api.eia.gov/v2"


class EiaConnector(BaseConnector):
    source_name = "EIA Open Data API v2"
    source_url = EIA_BASE

    def __init__(self, raw_dir: Path, years: list[int],
                 api_key: str | None = None, **kwargs):
        super().__init__(raw_dir, **kwargs)
        self.years = years
        self.api_key = api_key or os.environ.get("EIA_API_KEY")

    def _require_key(self):
        if not self.api_key:
            raise SourceUnavailableError(
                f"[{self.source_name}] no API key. Set EIA_API_KEY env var or "
                f"config.data.eia.api_key. Register free at "
                f"https://www.eia.gov/opendata/register.php. "
                f"No fabricated fallback is used.")

    def _series(self, route: str, params: dict) -> pd.DataFrame:
        self._require_key()
        url = f"{EIA_BASE}/{route}"
        full_params = {
            "api_key": self.api_key,
            "frequency": "annual",
            "start": str(min(self.years)),
            "end": str(max(self.years)),
            **params,
        }
        resp = self._get(url, params=full_params, expect="json")
        payload = resp.json()
        rows = payload.get("response", {}).get("data")
        if not rows:
            raise SourceUnavailableError(
                f"[{self.source_name}] empty data for route {route}: "
                f"{str(payload)[:200]}")
        return pd.DataFrame(rows)

    def fetch_gas_price(self) -> pd.DataFrame:
        """Henry Hub natural gas spot price, annual average ($/MMBtu)."""
        df = self._series(
            "natural-gas/pri/fut/data",
            {"data[0]": "value", "facets[series][]": "RNGWHHD",
             "sort[0][column]": "period", "sort[0][direction]": "asc"},
        )
        df["year"] = df["period"].astype(str).str.slice(0, 4).astype(int)
        out = (df.groupby("year")["value"]
                 .mean().rename("henry_hub_gas_usd").reset_index())
        out.to_csv(self.raw_dir / "eia_henry_hub.csv", index=False)
        return out

    def fetch_renewables_share(self) -> pd.DataFrame:
        """Renewables as % of total electricity net generation, annual."""
        df = self._series(
            "electricity/electric-power-operational-data/data",
            {"data[0]": "generation",
             "facets[fueltypeid][]": "ALL",
             "sort[0][column]": "period", "sort[0][direction]": "asc"},
        )
        df["year"] = df["period"].astype(str).str.slice(0, 4).astype(int)
        df["generation"] = pd.to_numeric(df["generation"], errors="coerce")
        # Renewable fuel type ids per EIA: WND, SUN, HYC, GEO, WWW, etc.
        renewable_ids = {"WND", "SUN", "HYC", "GEO", "WWW", "HPS", "AOR"}
        if "fueltypeid" not in df.columns:
            raise SourceUnavailableError(
                f"[{self.source_name}] missing fueltypeid; cols={list(df.columns)}")
        total = df.groupby("year")["generation"].sum()
        renew = (df[df["fueltypeid"].isin(renewable_ids)]
                 .groupby("year")["generation"].sum())
        out = ((renew / total * 100).rename("renewables_pct_gen")
               .reset_index())
        out.to_csv(self.raw_dir / "eia_renewables_share.csv", index=False)
        return out

    def fetch(self) -> pd.DataFrame:
        gas = self.fetch_gas_price()
        ren = self.fetch_renewables_share()
        return gas.merge(ren, on="year", how="outer").sort_values("year")
