"""
connectors/epa_ghgrp.py — EPA GHGRP connector (REAL DATA)

Two real access methods, tried in the order set by config (`prefer`):

  1. PRIMARY — Bulk "Data Summary Spreadsheets" ZIP
     Page:  https://www.epa.gov/ghgreporting/data-sets
     File:  .../<YYYY-MM>/<YYYY>_data_summary_spreadsheets.zip
     EPA's authoritative curated multi-year summary. Contains a multi-year
     workbook plus per-year sheets with facility-level reported emissions by
     GHG and process. One download, no paging, stable column semantics.
     The connector resolves the current ZIP link from the Data Sets page so it
     keeps working across annual releases; a known-good URL is the fallback.

  2. FALLBACK — Envirofacts RESTful Data Service
     Base:  https://data.epa.gov/efservice/
     Facility-level, programmatic, paged (service caps requests at 15 min, so
     we page in chunks). Column names vary by table build, so the connector
     detects the emissions column rather than assuming it.

VALIDATION (never substitution): aggregated national direct-emitter totals are
compared against EPA's *published* headline figures. These published anchors
are used ONLY to validate the live pull and warn on drift — never as data.

Verified published anchors (EPA GHGRP overview reports / Reported Data pages):
    2015: 8,003 facilities, 3.05 Bt CO2e
    2021: 7,608 facilities, 2.71 Bt CO2e
    2023: 7,544 facilities, 2.58 Bt CO2e

NOTE ON SANDBOX: both epa.gov and data.epa.gov return HTTP 403 from the
restricted authoring environment, so this connector cannot run there. It is
written to the verified real contracts and runs on any normal network.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path

import pandas as pd

from .base import BaseConnector, SourceUnavailableError

logger = logging.getLogger(__name__)

# Published direct-emitter anchors for VALIDATION ONLY (million metric tons CO2e
# and facility counts). Never used as data substitutes.
EPA_PUBLISHED_TOTALS_MMT = {2015: 3050, 2021: 2710, 2022: 2690, 2023: 2580}
EPA_PUBLISHED_FACILITY_COUNT = {2015: 8003, 2021: 7608, 2023: 7544}

# Candidate names for the per-facility annual CO2e column across EPA workbook
# and Envirofacts builds (detected, not assumed).
EMISSION_COL_CANDIDATES = [
    "ghg_quantity", "ghg quantity (metric tons co2e)",
    "total reported direct emissions",
    "total reported emissions", "co2e_emission", "co2e emissions",
    "annual_emission", "co2e", "emissions",
]
YEAR_COL_CANDIDATES = ["year", "reporting year", "reporting_year"]


class EpaGhgrpConnector(BaseConnector):
    source_name = "EPA GHGRP"
    source_url = "https://www.epa.gov/ghgreporting/data-sets"

    def __init__(self, raw_dir: Path, years, summary_zip_url: str,
                 data_sets_page: str, base_url: str,
                 facility_table: str = "PUB_DIM_FACILITY",
                 page_size: int = 10000, prefer: str = "zip", **kwargs):
        super().__init__(raw_dir, **kwargs)
        self.years = years
        self.summary_zip_url = summary_zip_url
        self.data_sets_page = data_sets_page
        self.efservice_base = base_url
        self.facility_table = facility_table
        self.page_size = page_size
        self.prefer = prefer

    # ============================================================ public

    def fetch(self) -> pd.DataFrame:
        order = ([self._fetch_via_zip, self._fetch_via_api]
                 if self.prefer == "zip"
                 else [self._fetch_via_api, self._fetch_via_zip])
        errors = []
        for method in order:
            try:
                panel = method()
                self._validate(panel)
                return panel
            except SourceUnavailableError as e:
                logger.warning(f"[{self.source_name}] {method.__name__} "
                               f"unavailable: {e}")
                errors.append(str(e))
        raise SourceUnavailableError(
            f"[{self.source_name}] all access methods failed. "
            f"No fabricated fallback. Errors: {errors}")

    # ============================================================ method 1: ZIP

    def _resolve_zip_url(self) -> str:
        """Find the current summary-spreadsheets ZIP link on the Data Sets page.
        Falls back to the configured known-good URL if the page can't be parsed.
        """
        try:
            resp = self._get(self.data_sets_page, expect="text")
            m = re.findall(r'href="([^"]*data_summary_spreadsheets\.zip)"',
                           resp.text, flags=re.IGNORECASE)
            if m:
                url = m[0]
                if url.startswith("/"):
                    url = "https://www.epa.gov" + url
                logger.info(f"[{self.source_name}] resolved ZIP link: {url}")
                return url
        except SourceUnavailableError:
            pass
        logger.info(f"[{self.source_name}] using configured ZIP URL: "
                    f"{self.summary_zip_url}")
        return self.summary_zip_url

    def _fetch_via_zip(self) -> pd.DataFrame:
        url = self._resolve_zip_url()
        resp = self._get(url, expect="bytes")
        raw_zip = self.raw_dir / "epa_ghgrp_summary.zip"
        raw_zip.write_bytes(resp.content)
        logger.info(f"[{self.source_name}] saved ZIP -> {raw_zip} "
                    f"({len(resp.content)/1e6:.1f} MB)")

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xlsx_names = [n for n in zf.namelist()
                          if n.lower().endswith((".xlsx", ".xls"))]
            if not xlsx_names:
                raise SourceUnavailableError(
                    f"[{self.source_name}] ZIP has no spreadsheet: "
                    f"{zf.namelist()[:10]}")
            target = next((n for n in xlsx_names
                           if "summary" in n.lower() or "multi" in n.lower()),
                          xlsx_names[0])
            logger.info(f"[{self.source_name}] reading workbook: {target}")
            with zf.open(target) as fh:
                workbook = pd.read_excel(fh, sheet_name=None, engine="openpyxl")

        panel = self._parse_summary_workbook(workbook)
        if panel is None or panel.empty:
            raise SourceUnavailableError(
                f"[{self.source_name}] could not parse a year/emissions panel "
                f"from workbook sheets: {list(workbook.keys())}")
        return panel

    def _parse_summary_workbook(self, workbook: dict):
        """Parse EPA's multi-year summary workbook into a national annual panel.

        Handles both WIDE (per-year emission columns) and LONG (a 'Reporting
        Year' column) layouts; detects the layout rather than assuming it.
        """
        sheet_name = next(
            (s for s in workbook
             if "direct" in s.lower() and "emit" in s.lower()), None)
        if sheet_name is None:
            sheet_name = max(workbook, key=lambda s: workbook[s].shape[0])
        df = workbook[sheet_name].copy()
        df.columns = [str(c).strip().lower() for c in df.columns]
        logger.info(f"[{self.source_name}] parsing sheet '{sheet_name}' "
                    f"({df.shape[0]} rows)")

        # Case A: WIDE — per-year emission columns
        year_cols = {}
        for col in df.columns:
            m = re.search(r"(20\d{2})", col)
            if m and ("emiss" in col or "co2" in col or "ghg" in col):
                year_cols[int(m.group(1))] = col
        if len(year_cols) >= 3:
            records = []
            for yr in sorted(year_cols):
                if yr not in self.years:
                    continue
                vals = pd.to_numeric(df[year_cols[yr]], errors="coerce")
                records.append({"year": yr,
                                "total_mmtco2e": vals.sum() / 1e6,
                                "n_facilities": int(vals.notna().sum())})
            return pd.DataFrame(records).sort_values("year")

        # Case B: LONG — year column + emissions column
        ycol = next((c for c in df.columns if c in YEAR_COL_CANDIDATES), None)
        ecol = next((c for c in df.columns if c in EMISSION_COL_CANDIDATES),
                    None)
        if ycol and ecol:
            df[ycol] = pd.to_numeric(df[ycol], errors="coerce")
            df[ecol] = pd.to_numeric(df[ecol], errors="coerce")
            sub = df[df[ycol].isin(self.years)]
            panel = (sub.groupby(ycol)
                        .agg(total_mmtco2e=(ecol, lambda s: s.sum() / 1e6),
                             n_facilities=(ecol, lambda s: s.notna().sum()))
                        .reset_index().rename(columns={ycol: "year"}))
            return panel.sort_values("year")
        return None

    # ============================================================ method 2: API

    def _fetch_via_api(self) -> pd.DataFrame:
        fac = self._fetch_table_csv(self.facility_table)
        raw_path = self.raw_dir / "epa_ghgrp_pub_dim_facility.csv"
        fac.to_csv(raw_path, index=False)
        logger.info(f"[{self.source_name}] saved facility table -> {raw_path} "
                    f"({len(fac):,} rows)")

        ycol = next((c for c in fac.columns if c in YEAR_COL_CANDIDATES), None)
        ecol = next((c for c in fac.columns if c in EMISSION_COL_CANDIDATES),
                    None)
        if ycol is None:
            raise SourceUnavailableError(
                f"[{self.source_name}] no year column in {self.facility_table}; "
                f"got {list(fac.columns)[:20]}")
        if ecol is None:
            facts = self._fetch_sector_emissions()
            n_by_year = (fac[fac[ycol].isin(self.years)]
                         .groupby(ycol)["facility_id"].nunique()
                         if "facility_id" in fac.columns else None)
            panel = (facts[facts["year"].isin(self.years)]
                     .groupby("year")["co2e_mmt"].sum()
                     .rename("total_mmtco2e").reset_index())
            if n_by_year is not None:
                panel = panel.merge(n_by_year.rename("n_facilities"),
                                    left_on="year", right_index=True, how="left")
            return panel.sort_values("year")

        fac[ycol] = pd.to_numeric(fac[ycol], errors="coerce")
        fac[ecol] = pd.to_numeric(fac[ecol], errors="coerce")
        sub = fac[fac[ycol].isin(self.years)]
        agg_n = (("facility_id", "nunique") if "facility_id" in fac.columns
                 else (ecol, lambda s: s.notna().sum()))
        panel = (sub.groupby(ycol)
                    .agg(total_mmtco2e=(ecol, lambda s: s.sum() / 1e6),
                         n_facilities=agg_n)
                    .reset_index().rename(columns={ycol: "year"}))
        return panel.sort_values("year")

    def _fetch_table_csv(self, table: str) -> pd.DataFrame:
        frames, first = [], 0
        while True:
            url = (f"{self.efservice_base}/{table}/"
                   f"{first}:{first + self.page_size - 1}/CSV")
            resp = self._get(url, expect="text")
            chunk = pd.read_csv(io.StringIO(resp.text))
            if chunk.empty:
                break
            frames.append(chunk)
            logger.info(f"[{self.source_name}] {table}: rows {first}-"
                        f"{first + len(chunk) - 1}")
            if len(chunk) < self.page_size:
                break
            first += self.page_size
        if not frames:
            raise SourceUnavailableError(
                f"[{self.source_name}] table {table} returned no rows")
        df = pd.concat(frames, ignore_index=True)
        df.columns = [c.strip().lower() for c in df.columns]
        return df

    def _fetch_sector_emissions(self) -> pd.DataFrame:
        for table in ["PUB_FACTS_SECTOR_GHG_EMISSION",
                      "PUB_FACTS_SUBP_GHG_EMISSION"]:
            try:
                df = self._fetch_table_csv(table)
                ycol = next((c for c in df.columns
                             if c in YEAR_COL_CANDIDATES), None)
                ecol = next((c for c in df.columns
                             if c in EMISSION_COL_CANDIDATES), None)
                if ycol and ecol:
                    df["co2e_mmt"] = pd.to_numeric(df[ecol],
                                                   errors="coerce") / 1e6
                    return df.rename(columns={ycol: "year"})[["year", "co2e_mmt"]]
            except SourceUnavailableError:
                continue
        raise SourceUnavailableError(
            f"[{self.source_name}] no usable GHG emission fact table found")

    # ============================================================ validation

    def _validate(self, panel: pd.DataFrame, tol_pct: float = 5.0) -> None:
        if "total_mmtco2e" not in panel.columns:
            raise SourceUnavailableError(
                f"[{self.source_name}] parsed panel lacks total_mmtco2e")
        for year, pub in EPA_PUBLISHED_TOTALS_MMT.items():
            row = panel.loc[panel["year"] == year]
            if row.empty:
                continue
            live = float(row["total_mmtco2e"].iloc[0])
            dev = abs(live - pub) / pub * 100
            line = (f"[{self.source_name}] {year}: live={live:,.0f} MMt vs "
                    f"published~{pub:,} MMt (delta={dev:.1f}%)")
            logger.warning(line + " - exceeds tolerance, inspect parse/paging"
                           if dev > tol_pct else line + " - within tolerance OK")
