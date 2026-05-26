"""
ingest.py — Real-data ingestion orchestrator
==============================================
Pulls data ONLY from real public sources via the connectors package.
Writes raw pulls to data/raw/ and an assembled annual panel to data/interim/.

Behaviour by design:
  * Each enabled source is fetched live. There are NO hardcoded numeric
    fallbacks. If an enabled source fails, the step records the failure.
  * OWID is enabled by default and works from any GitHub-reachable network.
  * EPA/EIA/NOAA reach real government APIs. They are unreachable from the
    restricted authoring sandbox (403) but work on a normal network.
  * A provenance record is written for every source actually used.

Run:
    python src/ingest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from utils import load_config, get_logger, ensure_dirs
from connectors import (
    OwidConnector, EpaGhgrpConnector, EiaConnector, NoaaConnector,
    SourceUnavailableError,
)


def run(cfg: dict, base_dir: Path) -> dict:
    log = get_logger("ingest", cfg)
    raw_dir = base_dir / "data" / "raw"
    interim_dir = base_dir / "data" / "interim"
    ensure_dirs(raw_dir, interim_dir)

    years = cfg["data"]["years"]
    http = cfg.get("http", {})
    common = dict(
        timeout=http.get("timeout_seconds", 60),
        max_retries=http.get("max_retries", 3),
        backoff=http.get("backoff_base", 2.0),
    )

    log.info("=" * 64)
    log.info("REAL-DATA INGESTION — live sources only, no fabricated values")
    log.info("=" * 64)

    provenance: list[dict] = []
    failures: list[tuple[str, str]] = []
    panel_parts: dict[str, pd.DataFrame] = {}
    owid_us = None

    # ── OWID (always-on, GitHub) ───────────────────────────────────────────
    if cfg["sources"].get("owid", True):
        try:
            oc = OwidConnector(
                raw_dir, country=cfg["data"]["owid"]["country"],
                year_min=cfg["data"]["owid"]["year_min"],
                year_max=cfg["data"]["owid"]["year_max"], **common)
            owid_us = oc.fetch()
            owid_us.to_csv(interim_dir / "owid_us.csv", index=False)
            provenance.append(oc.provenance())
            log.info(f"OWID ✓ ({len(owid_us)} US rows)")
        except SourceUnavailableError as e:
            failures.append(("owid", str(e)))
            log.error(f"OWID failed: {e}")

    # ── EPA GHGRP (bulk ZIP primary, Envirofacts API fallback) ──────────────
    if cfg["sources"].get("epa", True):
        try:
            epa_cfg = cfg["data"]["epa"]
            ec = EpaGhgrpConnector(
                raw_dir, years=years,
                summary_zip_url=epa_cfg["summary_zip_url"],
                data_sets_page=epa_cfg["data_sets_page"],
                base_url=epa_cfg["base_url"],
                facility_table=epa_cfg.get("facility_table", "PUB_DIM_FACILITY"),
                page_size=epa_cfg.get("page_size", 10000),
                prefer=epa_cfg.get("prefer", "zip"),
                **common)
            epa_panel = ec.fetch()
            epa_panel.to_csv(interim_dir / "epa_ghgrp_panel.csv", index=False)
            panel_parts["epa"] = epa_panel
            provenance.append(ec.provenance())
            log.info(f"EPA GHGRP ✓ ({len(epa_panel)} years)")
        except SourceUnavailableError as e:
            failures.append(("epa", str(e)))
            log.error(f"EPA GHGRP failed (expected in restricted sandbox): {e}")

    # ── EIA (optional, needs key) ───────────────────────────────────────────
    if cfg["sources"].get("eia", False):
        try:
            ei = EiaConnector(
                raw_dir, years=years,
                api_key=cfg["data"]["eia"].get("api_key") or None, **common)
            eia_panel = ei.fetch()
            eia_panel.to_csv(interim_dir / "eia_panel.csv", index=False)
            panel_parts["eia"] = eia_panel
            provenance.append(ei.provenance())
            log.info(f"EIA ✓ ({len(eia_panel)} years)")
        except SourceUnavailableError as e:
            failures.append(("eia", str(e)))
            log.error(f"EIA failed: {e}")
    else:
        log.info("EIA disabled in config (set sources.eia=true + key to enable)")

    # ── NOAA NCEI ───────────────────────────────────────────────────────────
    if cfg["sources"].get("noaa", True):
        try:
            nc = NoaaConnector(
                raw_dir, year_min=cfg["data"]["noaa"]["year_min"],
                year_max=cfg["data"]["noaa"]["year_max"], **common)
            noaa_panel = nc.fetch()
            noaa_panel.to_csv(interim_dir / "noaa_panel.csv", index=False)
            panel_parts["noaa"] = noaa_panel
            provenance.append(nc.provenance())
            log.info(f"NOAA ✓ ({len(noaa_panel)} years)")
        except SourceUnavailableError as e:
            failures.append(("noaa", str(e)))
            log.error(f"NOAA failed (expected in restricted sandbox): {e}")

    # ── Assemble merged annual panel from whatever real sources succeeded ───
    merged = None
    for name, part in panel_parts.items():
        if "year" not in part.columns:
            continue
        merged = part if merged is None else merged.merge(part, on="year", how="outer")
    if merged is not None:
        merged = merged.sort_values("year")
        merged.to_csv(interim_dir / "annual_panel.csv", index=False)
        log.info(f"Assembled annual panel: {merged.shape} → annual_panel.csv")

    # ── Write provenance + failure manifest (full transparency) ─────────────
    manifest = {
        "sources_used": provenance,
        "sources_failed": [{"source": s, "error": e[:300]} for s, e in failures],
        "note": ("No fabricated data is used anywhere. Failed sources are "
                 "recorded here and simply absent from the panel."),
    }
    with open(interim_dir / "provenance.json", "w") as f:
        json.dump(manifest, f, indent=2)
    log.info(f"Provenance manifest → {interim_dir / 'provenance.json'}")

    if failures:
        log.warning(f"{len(failures)} source(s) unavailable: "
                    f"{[f[0] for f in failures]}")
    if not panel_parts and owid_us is None:
        log.error("No real source succeeded. Nothing was written. "
                  "Check network access to the source APIs.")

    return {"merged": merged, "owid_us": owid_us,
            "provenance": manifest, "failures": failures}


if __name__ == "__main__":
    cfg = load_config("config/config.yaml")
    base = Path(__file__).resolve().parent.parent
    run(cfg, base)
