"""
utils.py — Shared utilities for the GHGRP Atmospheric Pipeline
"""

import logging
import os
import sys
import time
from pathlib import Path
from functools import wraps

import yaml
import numpy as np
import pandas as pd


# ── Config loader ─────────────────────────────────────────────────────────────

def load_config(config_path: str = "config/config.yaml") -> dict:
    """Load YAML config, resolving paths relative to project root."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return cfg


# ── Logger factory ────────────────────────────────────────────────────────────

def get_logger(name: str, config: dict = None) -> logging.Logger:
    """Return a named logger writing to both console and file."""
    logger = logging.getLogger(name)
    if logger.handlers:          # already configured
        return logger

    level_str = (config or {}).get("logging", {}).get("level", "INFO")
    level = getattr(logging, level_str, logging.INFO)
    fmt   = (config or {}).get("logging", {}).get("format",
             "%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    log_file = (config or {}).get("logging", {}).get("file", "logs/pipeline.log")

    os.makedirs(Path(log_file).parent, exist_ok=True)

    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)

    fh = logging.FileHandler(log_file, mode="a")
    fh.setFormatter(formatter)

    logger.setLevel(level)
    logger.addHandler(sh)
    logger.addHandler(fh)
    logger.propagate = False
    return logger


# ── Timing decorator ──────────────────────────────────────────────────────────

def timed(func):
    """Decorator: logs wall-clock time for each pipeline step."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        logger.info(f"▶ Starting  {func.__name__}")
        t0 = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        logger.info(f"✔ Completed {func.__name__} in {elapsed:.2f}s")
        return result
    return wrapper


# ── Path helpers ──────────────────────────────────────────────────────────────

def ensure_dirs(*paths):
    """Create directories if they don't exist."""
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


def project_root() -> Path:
    """Return the project root (parent of src/)."""
    return Path(__file__).resolve().parent.parent


# ── Data validation ───────────────────────────────────────────────────────────

def validate_dataframe(df: pd.DataFrame, required_cols: list, name: str = "DataFrame") -> None:
    """Raise ValueError if required columns are missing or all-null."""
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"[{name}] Missing columns: {missing}")
    for col in required_cols:
        if df[col].isna().all():
            raise ValueError(f"[{name}] Column '{col}' is entirely null")


def check_year_coverage(df: pd.DataFrame, expected_years: list, year_col: str = "year") -> None:
    """Warn if any expected years are absent from the dataframe."""
    logger = logging.getLogger(__name__)
    actual = set(df[year_col].tolist())
    missing = set(expected_years) - actual
    if missing:
        logger.warning(f"Missing years in data: {sorted(missing)}")
    else:
        logger.info(f"Year coverage complete: {min(expected_years)}–{max(expected_years)}")


# ── Numeric helpers ───────────────────────────────────────────────────────────

def pct_change(new: float, old: float) -> float:
    return (new - old) / old * 100 if old != 0 else float("nan")


def pearson_r(x, y) -> tuple:
    from scipy.stats import pearsonr
    mask = ~(np.isnan(x) | np.isnan(y))
    if mask.sum() < 3:
        return float("nan"), float("nan")
    return pearsonr(x[mask], y[mask])
