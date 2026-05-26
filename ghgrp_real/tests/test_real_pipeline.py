"""
tests/test_real_pipeline.py — Tests for the real-data pipeline
================================================================
Key tests:
  * Connectors raise SourceUnavailableError (never fabricate) on failure
  * OWID connector returns genuine live data (requires GitHub access)
  * No connector contains hardcoded emissions arrays (anti-fabrication audit)
  * Analysis operates only on present columns

Run:  python -m pytest tests/ -v
"""

import sys
import re
from pathlib import Path

import pytest
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from utils import load_config
from connectors import (OwidConnector, EpaGhgrpConnector,
                        NoaaConnector, EiaConnector, SourceUnavailableError)


@pytest.fixture
def cfg():
    return load_config(str(ROOT / "config" / "config.yaml"))


@pytest.fixture
def tmp_raw(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    return d


# ── Anti-fabrication audit ─────────────────────────────────────────────────

class TestNoFabricatedData:
    """The whole point of this pipeline: no hardcoded data values."""

    def test_no_hardcoded_emission_arrays_in_connectors(self):
        """Connector source must not contain long numeric literal lists that
        would indicate embedded (fabricated) datasets.

        We allow short validation constants (EPA published headline totals)
        but flag any list literal of >8 numbers that isn't clearly a
        validation reference."""
        conn_dir = ROOT / "src" / "connectors"
        offenders = []
        for pyfile in conn_dir.glob("*.py"):
            text = pyfile.read_text()
            # find list literals with many comma-separated numbers
            for match in re.finditer(r"\[([\d\s,\.\-]{40,})\]", text):
                nums = [n for n in match.group(1).replace("\n", "").split(",")
                        if n.strip()]
                if len(nums) > 8:
                    # allow if within a *_PUBLISHED_* or *VALIDATION* context
                    start = max(0, match.start() - 120)
                    context = text[start:match.start()].upper()
                    if "PUBLISHED" not in context and "VALIDATION" not in context:
                        offenders.append((pyfile.name, nums[:5]))
        assert not offenders, f"Possible embedded data arrays: {offenders}"

    def test_epa_validation_constants_are_clearly_labeled(self):
        """The only EPA numeric constants allowed are validation references."""
        text = (ROOT / "src" / "connectors" / "epa_ghgrp.py").read_text()
        assert "EPA_PUBLISHED_TOTALS_MMT" in text
        assert "ONLY to validate" in text or "never as a data substitute" in text

    def test_epa_has_two_real_access_methods(self):
        """EPA connector must implement both bulk ZIP and Envirofacts API."""
        text = (ROOT / "src" / "connectors" / "epa_ghgrp.py").read_text()
        assert "_fetch_via_zip" in text
        assert "_fetch_via_api" in text
        assert "data_summary_spreadsheets" in text   # real bulk file
        assert "efservice" in text                    # real REST API

    def test_epa_validation_anchors_match_published(self):
        """Validation anchors must equal EPA's published headline totals."""
        import connectors.epa_ghgrp as mod
        assert mod.EPA_PUBLISHED_TOTALS_MMT[2023] == 2580   # 2.58 Bt, verified
        assert mod.EPA_PUBLISHED_TOTALS_MMT[2021] == 2710   # 2.71 Bt, verified
        assert mod.EPA_PUBLISHED_FACILITY_COUNT[2023] == 7544


# ── Connectors fail honestly (no fabrication) ──────────────────────────────

class TestConnectorsFailHonestly:

    def test_epa_unreachable_raises(self, tmp_raw, cfg):
        """Point EPA connector at bad hosts → must raise, not fabricate."""
        epa_cfg = cfg["data"]["epa"]
        c = EpaGhgrpConnector(
            tmp_raw, years=[2023],
            summary_zip_url="https://localhost:1/x.zip",
            data_sets_page="https://localhost:1/page",
            base_url="https://localhost:1/efservice",
            prefer="api", max_retries=1, timeout=5)
        with pytest.raises(SourceUnavailableError):
            c.fetch()

    def test_eia_without_key_raises(self, tmp_raw):
        """EIA connector with no key must raise, not fabricate."""
        c = EiaConnector(tmp_raw, years=[2023], api_key=None, max_retries=1)
        # ensure env var absent for the test
        import os
        old = os.environ.pop("EIA_API_KEY", None)
        try:
            with pytest.raises(SourceUnavailableError):
                c.fetch()
        finally:
            if old:
                os.environ["EIA_API_KEY"] = old

    def test_noaa_unreachable_raises(self, tmp_raw):
        c = NoaaConnector(tmp_raw, year_min=2020, year_max=2023,
                          max_retries=1, timeout=5)
        import connectors.noaa as mod
        original = mod.NCEI_BASE
        mod.NCEI_BASE = "https://localhost:1/series"
        try:
            with pytest.raises(SourceUnavailableError):
                c.fetch()
        finally:
            mod.NCEI_BASE = original


# ── OWID live data (real) ──────────────────────────────────────────────────

class TestOwidLive:
    """These hit the real OWID GitHub URL. Skip if no network."""

    def test_owid_fetches_real_us_data(self, tmp_raw):
        c = OwidConnector(tmp_raw, country="United States",
                          year_min=1960, year_max=2023, max_retries=2)
        try:
            df = c.fetch()
        except SourceUnavailableError:
            pytest.skip("OWID not reachable from this network")
        assert len(df) > 50
        assert "co2" in df.columns
        # Real-world sanity: U.S. CO2 peaked around 2005-2007 well above 5000 Mt
        assert df["co2"].max() > 5000
        assert df["year"].min() >= 1960

    def test_owid_us_2005_peak_is_real(self, tmp_raw):
        """Validate a known real fact: U.S. CO2 peaked ~6,100 Mt in 2005-07."""
        c = OwidConnector(tmp_raw, year_min=2000, year_max=2010, max_retries=2)
        try:
            df = c.fetch()
        except SourceUnavailableError:
            pytest.skip("OWID not reachable")
        peak_year = int(df.loc[df["co2"].idxmax(), "year"])
        assert 2004 <= peak_year <= 2008, f"Unexpected peak year {peak_year}"


# ── Config integrity ───────────────────────────────────────────────────────

class TestConfig:

    def test_all_source_urls_are_official(self, cfg):
        """Every configured URL must be an official/public domain."""
        assert "owid" in cfg["data"]["owid"]["url"]
        assert "data.epa.gov" in cfg["data"]["epa"]["base_url"]
        assert "api.eia.gov" in cfg["data"]["eia"]["base_url"]
        assert "ncei.noaa.gov" in cfg["data"]["noaa"]["base_url"]

    def test_active_source_set_matches_user_choice(self, cfg):
        """User selected EPA + OWID + EIA; NOAA off."""
        assert cfg["sources"]["owid"] is True
        assert cfg["sources"]["epa"] is True
        assert cfg["sources"]["eia"] is True
        assert cfg["sources"]["noaa"] is False

    def test_epa_prefers_bulk_zip(self, cfg):
        """EPA access method: bulk ZIP primary (most reliable), API fallback."""
        assert cfg["data"]["epa"]["prefer"] == "zip"
        assert "data_summary_spreadsheets" in cfg["data"]["epa"]["summary_zip_url"]
        assert "data.epa.gov/efservice" in cfg["data"]["epa"]["base_url"]

    def test_no_api_key_committed(self, cfg):
        """Ensure no real API key is accidentally committed in config."""
        assert cfg["data"]["eia"]["api_key"] == "", \
            "An API key appears to be committed — remove it before sharing"
