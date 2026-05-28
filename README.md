# What Really Drives U.S. Industrial GHG Emissions?

**A four-stage analysis of structural change vs. atmospheric forcing**
- Harvard D³ Institute Assessment · Suhail Mahmud, PhD

EPA GHGRP (2010–2023) · ERA5 Reanalysis · OWID / Global Carbon Project 
---

## TL;DR

U.S. industrial greenhouse-gas emissions fell **22% from 2011 to 2023**, and the decline is
**structural** (power-sector decarbonization: −34.5%), **not** driven by weather. This holds at
four progressively stronger levels of analysis:

| Stage | Test | Result | Climate's role |
|---|---|---|---|
| 1. National trend | Spearman, linear, ADF, ARIMA | ρ=−0.93, p<0.0001, −740 MMt | structural |
| 2. Atmospheric OLS | 7 ERA5 variables, LOO-CV | in-sample R²=0.38, **LOO R²=−4.67** | no out-of-sample skill |
| 3. Facility panel (FE) | two-way fixed effects, 86k obs | power-plant temp β=+0.111 (p=0.0003) | real but tiny (within-R² 0.5%) |
| 4. Predictive ML | GBM, temporal split | structural R²=0.88 | marginal Δ=−0.003 (noise) |

The single genuine weather signal — a small power-plant cooling-demand response — is
specification-sensitive and explains <1% of variance. The EPA totals validate to **0.05%** of
EPA's published 2023 headline.

---

## Repository structure

```
ghgrp_project_repo/
├── README.md                       ← this file
├── notebooks/                      ← analysis notebooks (executed, with outputs)
│   ├── GHGRP_ERA5_Real_Analysis.ipynb        Stage 1–2: national trend + atmospheric tests
│   ├── Facility_Weather_Sensitivity_2023.ipynb  Stage 3a: 2023 cross-sectional join
│   ├── Facility_Panel_FixedEffects.ipynb     Stage 3b: facility-year fixed-effects panel
│   └── ML_Emissions_Structural_Model.ipynb   Stage 4: staged ML with climate null test
├── ghgrp_real/                       ← real-data ingestion pipeline (no fabricated data)
│   ├── config/             EPA, OWID, EIA, NOAA connectors
│   ├── src/ingest.py, analyze.py   orchestration
│   ├── run_pipeline.py             CLI entry point
│   ├── data/                      incl. anti-fabrication audit
│   ├── config/config.yaml
│   └── README.md                   pipeline-specific docs
├── data/                           ← processed/validated datasets (CSV)
├── deliverables/                   ← presentation + 2-page summary
│   ├── GHGRP_Full_Project_Presentation.pptx
│   └── GHGRP_Full_Project_Summary.docx
