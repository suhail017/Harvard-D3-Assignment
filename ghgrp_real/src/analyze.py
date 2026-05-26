"""
analyze.py — Analysis on REAL ingested data only
==================================================
Operates strictly on whatever real sources succeeded in the ingest step.
It inspects which columns are actually present and runs only the analyses
those columns support. It never invents missing covariates.

Possible analyses (each gated on real data availability):
  * OWID long-run U.S. CO2 trend: ADF stationarity, Spearman trend,
    linear slope, carbon intensity decomposition.
  * EPA GHGRP annual panel (if EPA reachable): trend + ARIMA forecast.
  * Covariate regression (if EPA + EIA/NOAA all present): OLS of GHGRP
    emissions on real energy/climate covariates.

Run:
    python src/analyze.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.stattools import adfuller

from utils import load_config, get_logger, ensure_dirs


def _load_interim(base_dir: Path, log):
    interim = base_dir / "data" / "interim"
    out = {}
    for name in ["owid_us", "annual_panel", "epa_ghgrp_panel",
                 "eia_panel", "noaa_panel"]:
        p = interim / f"{name}.csv"
        if p.exists():
            out[name] = pd.read_csv(p)
            log.info(f"Loaded {name}: {out[name].shape}")
    return out


def analyze_owid(owid: pd.DataFrame, log) -> dict:
    """Trend analysis on the real OWID U.S. CO2 series."""
    df = owid.dropna(subset=["co2"]).sort_values("year")
    y = df["co2"].values
    yr = df["year"].values

    adf_stat, p_adf, *_ = adfuller(y, autolag="AIC")
    rho, p_sp = stats.spearmanr(yr, y)
    slope, intercept, r, p_lin, se = stats.linregress(yr, y)

    # Recent-decade carbon-intensity change (real co2_per_gdp where present)
    intensity = None
    sub = df.dropna(subset=["co2_per_gdp"])
    if len(sub) >= 2:
        first, last = sub.iloc[0], sub.iloc[-1]
        intensity = {
            "from_year": int(first["year"]),
            "to_year": int(last["year"]),
            "co2_per_gdp_first": round(float(first["co2_per_gdp"]), 4),
            "co2_per_gdp_last": round(float(last["co2_per_gdp"]), 4),
            "pct_change": round((last["co2_per_gdp"] - first["co2_per_gdp"])
                                / first["co2_per_gdp"] * 100, 1),
        }

    res = {
        "series": "OWID U.S. total CO2 (Mt)",
        "n_years": int(len(df)),
        "year_range": [int(yr.min()), int(yr.max())],
        "latest_value_mt": round(float(y[-1]), 1),
        "peak_year": int(yr[np.argmax(y)]),
        "peak_value_mt": round(float(y.max()), 1),
        "adf_stat": round(float(adf_stat), 4),
        "adf_pvalue": round(float(p_adf), 4),
        "spearman_rho": round(float(rho), 4),
        "spearman_pvalue": round(float(p_sp), 4),
        "linear_slope_mt_per_yr": round(float(slope), 2),
        "linear_r2": round(float(r ** 2), 4),
        "carbon_intensity_change": intensity,
    }
    log.info(f"OWID CO2: latest {res['latest_value_mt']} Mt "
             f"({res['year_range'][0]}–{res['year_range'][1]}), "
             f"peak {res['peak_value_mt']} Mt in {res['peak_year']}")
    log.info(f"OWID trend: Spearman rho={rho:.3f} (p={p_sp:.4f}), "
             f"linear slope={slope:.1f} Mt/yr")
    return res


def analyze_epa(epa: pd.DataFrame, cfg, log) -> dict:
    """Trend + ARIMA forecast on the real EPA GHGRP panel (if present)."""
    if "total_mmtco2e" not in epa.columns:
        log.warning("EPA panel lacks total_mmtco2e; skipping EPA analysis")
        return {}
    df = epa.dropna(subset=["total_mmtco2e"]).sort_values("year")
    y = df["total_mmtco2e"].values
    rho, p_sp = stats.spearmanr(df["year"], y)
    adf_stat, p_adf, *_ = adfuller(y, autolag="AIC")

    forecast = None
    try:
        from statsmodels.tsa.arima.model import ARIMA
        fit = ARIMA(y, order=(1, 1, 1)).fit()
        steps = 7
        fc = fit.get_forecast(steps=steps)
        mean = np.array(fc.predicted_mean)
        ci = np.array(fc.conf_int(alpha=0.05))
        last_year = int(df["year"].max())
        forecast = [
            {"year": last_year + 1 + i,
             "forecast_mmtco2e": round(float(mean[i]), 1),
             "ci_lower": round(float(ci[i, 0]), 1),
             "ci_upper": round(float(ci[i, 1]), 1)}
            for i in range(steps)
        ]
        log.info(f"EPA ARIMA(1,1,1) AIC={fit.aic:.1f}; "
                 f"{last_year+1} forecast={forecast[0]['forecast_mmtco2e']} MMt")
    except Exception as e:
        log.warning(f"ARIMA skipped: {e}")

    return {
        "series": "EPA GHGRP total direct emissions (MMt CO2e)",
        "n_years": int(len(df)),
        "spearman_rho": round(float(rho), 4),
        "spearman_pvalue": round(float(p_sp), 4),
        "adf_pvalue": round(float(p_adf), 4),
        "arima_forecast": forecast,
    }


def analyze_covariate_regression(panel: pd.DataFrame, log) -> dict:
    """OLS of GHGRP emissions on real covariates — only if all present."""
    if panel is None or "total_mmtco2e" not in panel.columns:
        return {}
    candidate = ["henry_hub_gas_usd", "renewables_pct_gen",
                 "cdd_annual", "hdd_annual", "pdsi_annual"]
    present = [c for c in candidate if c in panel.columns
               and panel[c].notna().sum() >= 5]
    if len(present) < 2:
        log.info("Covariate regression skipped: need >=2 real covariates, "
                 f"have {present}")
        return {}
    import statsmodels.api as sm
    from sklearn.preprocessing import StandardScaler
    df = panel.dropna(subset=["total_mmtco2e"] + present)
    if len(df) < len(present) + 2:
        log.info("Covariate regression skipped: insufficient overlapping years")
        return {}
    X = StandardScaler().fit_transform(df[present].values)
    model = sm.OLS(df["total_mmtco2e"].values, sm.add_constant(X)).fit()
    log.info(f"Covariate OLS on REAL data: R²={model.rsquared:.3f}, "
             f"features={present}")
    return {
        "features_used": present,
        "n_obs": int(len(df)),
        "r2": round(float(model.rsquared), 4),
        "adj_r2": round(float(model.rsquared_adj), 4),
        "coefficients": dict(zip(["const"] + present,
                                 [round(float(c), 2) for c in model.params])),
    }


def run(cfg: dict, base_dir: Path) -> dict:
    log = get_logger("analyze", cfg)
    tables_dir = base_dir / "outputs" / "tables"
    ensure_dirs(tables_dir)

    log.info("=" * 64)
    log.info("ANALYSIS — real data only; analyses gated on available columns")
    log.info("=" * 64)

    data = _load_interim(base_dir, log)
    results = {"note": "All results derived solely from real fetched data. "
                       "Analyses absent below mean the required real source "
                       "was not reachable at ingest time."}

    if "owid_us" in data:
        results["owid"] = analyze_owid(data["owid_us"], log)
    else:
        log.warning("No OWID data; skipping OWID analysis")

    if "epa_ghgrp_panel" in data:
        results["epa"] = analyze_epa(data["epa_ghgrp_panel"], cfg, log)
    else:
        log.warning("No EPA GHGRP panel (source was unreachable at ingest); "
                    "skipping EPA trend/forecast")

    panel = data.get("annual_panel")
    cov = analyze_covariate_regression(panel, log)
    if cov:
        results["covariate_regression"] = cov

    out_path = tables_dir / "analysis_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    log.info(f"Analysis results → {out_path}")
    return results


if __name__ == "__main__":
    cfg = load_config("config/config.yaml")
    base = Path(__file__).resolve().parent.parent
    run(cfg, base)
