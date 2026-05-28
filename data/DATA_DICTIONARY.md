# Data Dictionary

| File | Description | Key columns |
|---|---|---|
| `epa_ghgrp_validated_panel.csv` | National annual emissions 2010–2023 | year, total_mmtco2e, n_facilities |
| `epa_sectors_real.csv` | Sector-level emissions 2011 vs 2023 | primary_sector, mmtco2e_2023, mmtco2e_2011, pct_change |
| `epa_states_real.csv` | State-level emissions 2011 vs 2023 | State, mmtco2e_2023, pct_change |
| `era5_annual_full.csv` | ERA5 CONUS annual atmospheric variables | year, t2m_mean_c, vpd_annual_kpa, rh_mean_pct, wind_mean_ms, sp_mean_hpa, sst_mean_c, precip_rate_idx |
| `era5_monthly_full.csv` | ERA5 monthly CONUS area-means | year, month, t2m_c, vpd_kpa, rh_pct, wind_ms, sp_hpa, sst_c, precip |
| `master_real_dataset_full.csv` | Merged national EPA + ERA5 + OWID | year + all above + co2, total_ghg |
| `facility_panel.csv` | Facility-year panel (86k rows) | fid, year, lat, lon, state, primary_sector, emis, log_emis, t2m_jja_c, vpd_jja_kpa, ... |
| `ml_dataset.csv` | ML modeling table | + naics2, subpart1, log_emis_lag1, years_reporting |
| `ml_results.csv` | Staged ML test R² results | model, r2, block |
| `fe_results.csv` | Fixed-effects coefficients | sector, var, beta, se, p |
| `epa_forecast_real.csv` | ARIMA(1,1,1) forecast 2024–2030 | year, forecast, ci_lower, ci_upper |
| `owid_us_2010_2023.csv` | OWID U.S. context | year, co2, total_ghg, co2_per_gdp |

**Units:** emissions in metric tons CO₂e (facility) or million metric tons (national, `total_mmtco2e`);
temperature °C; VPD kPa; wind m/s; pressure hPa; precipitation = ERA5 monthly-mean rate index.
