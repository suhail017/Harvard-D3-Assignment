#!/usr/bin/env python3
"""
run_pipeline.py — Real-Data GHGRP Pipeline Runner
==================================================
Orchestrates ingestion and analysis using ONLY real public data sources.

Usage:
    python run_pipeline.py                  # ingest + analyze
    python run_pipeline.py --steps ingest   # just fetch real data
    python run_pipeline.py --steps analyze  # analyze what was fetched
    python run_pipeline.py --check-sources  # test reachability of each source

There are no fabricated data fallbacks. If a source is unreachable, it is
recorded in data/interim/provenance.json and omitted; the pipeline does not
invent values to fill the gap.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from utils import load_config, get_logger, ensure_dirs
import ingest as step_ingest
import analyze as step_analyze

STEPS = {"ingest": step_ingest.run, "analyze": step_analyze.run}


def check_sources(cfg, log):
    """Probe each configured source URL and report reachability."""
    import requests
    probes = {
        "owid": cfg["data"]["owid"]["url"],
        "epa":  f"{cfg['data']['epa']['base_url']}/{cfg['data']['epa']['facility_table']}/0:1/CSV",
        "eia":  f"{cfg['data']['eia']['base_url']}/",
        "noaa": (f"{cfg['data']['noaa']['base_url']}/national/time-series/"
                 f"110/cdd/ann/12/2020-2023.json"),
    }
    log.info("Probing real data sources for reachability...")
    for name, url in probes.items():
        try:
            r = requests.get(url, timeout=20)
            log.info(f"  {name:5s}: HTTP {r.status_code} — "
                     f"{'reachable' if r.status_code == 200 else 'NOT reachable'}")
        except Exception as e:
            log.info(f"  {name:5s}: unreachable ({type(e).__name__})")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", nargs="+", choices=list(STEPS), default=list(STEPS))
    ap.add_argument("--config", default="config/config.yaml")
    ap.add_argument("--check-sources", action="store_true",
                    help="Probe each source URL and exit")
    args = ap.parse_args()

    cfg = load_config(args.config)
    base = Path(__file__).resolve().parent
    log = get_logger("pipeline", cfg)
    ensure_dirs(base / "data/raw", base / "data/interim",
                base / "outputs/tables", base / "logs")

    if args.check_sources:
        check_sources(cfg, log)
        return 0

    log.info("=" * 64)
    log.info(f"GHGRP REAL-DATA PIPELINE v{cfg['project']['version']}")
    log.info(f"Steps: {args.steps}")
    log.info("=" * 64)

    t0 = time.perf_counter()
    for step in args.steps:
        STEPS[step](cfg, base)
    log.info(f"Done in {time.perf_counter() - t0:.1f}s. "
             f"See data/interim/provenance.json for source provenance.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
