# References

Real, verifiable sources. Where a field was not confirmable at authoring time it is marked
*(verify at source)*; no authors, years or DOIs are invented. Peer-reviewed and INPE/CPTEC
material is preferred, per the study brief.

## Spin-up — peer-reviewed

- **Liu, Y., Zhuo, L., & Han, D. (2023).** Developing spin-up time framework for WRF extreme
  precipitation simulations. *Journal of Hydrology*, **620**, 129443.
  https://doi.org/10.1016/j.jhydrol.2023.129443
  — Proposes the OSTI framework; finds required spin-up is weather-situation dependent (disturbed
  weather needs more). *(Full text robots-blocked at authoring; cited for framework/qualitative
  finding, no specific hour count quoted.)*
- **Jerez, S., et al. (2020).** On the Spin-Up Period in WRF Simulations Over Europe: Trade-Offs
  Between Length and Seasonality. *Journal of Advances in Modeling Earth Systems (JAMES)*, **12**(4),
  e2019MS001945. https://doi.org/10.1029/2019MS001945
  — Peer-reviewed treatment of spin-up length vs seasonality. *(Co-author list to confirm at
  source.)*
- **Examining spin-up behaviour within WRF dynamical downscaling applications (2026).**
  *Geoscientific Model Development*, **19**, 579-…  https://gmd.copernicus.org/articles/19/579/2026/
  — Land-surface/soil-moisture spin-up (≥ 1 yr; soil moisture 1–4 yr). Cited to *exclude* it as
  irrelevant to a per-cycle re-initialised forecast. *(Authors to confirm at source.)*

## Spin-up — developer/community guidance (not peer-reviewed)

- **WRF & MPAS-A Support Forum (NCAR/MMM),** thread *"How do use model spin up for forecast data."*
  https://forum.mmm.ucar.edu/threads/how-do-use-model-spin-up-for-forecast-data.18794/
  — Common practice: discard the first ~6 h; length depends on resolution/timestep.

## Forecast verification metrics (definitions used in `verif_core.py` and here)

- **Roberts, N. M., & Lean, H. W. (2008).** Scale-Selective Verification of Rainfall Accumulations
  from High-Resolution Forecasts of Convective Events. *Monthly Weather Review*, **136** — FSS /
  neighbourhood verification, double-penalty.
- **Roebber, P. J. (2009).** Visualizing Multiple Measures of Forecast Quality. *Weather and
  Forecasting*, **24**(2) — POD/SR/CSI/BIAS performance diagram.
- **Stephenson, D. B., Casati, B., Ferro, C. A. T., & Wilson, C. A. (2008).** The extreme
  dependency score. *Meteorological Applications*, **15**, 41–50.
- **Ferro, C. A. T., & Stephenson, D. B. (2011).** Extremal Dependence Indices (EDI/SEDI).
  *Weather and Forecasting*, **26**, 699–713.
- **WWRP/WGNE Joint Working Group on Forecast Verification Research** — categorical-score
  definitions. https://www.cawcr.gov.au/projects/verification/
- **Jolliffe, I. T., & Stephenson, D. B.** *Forecast Verification: A Practitioner's Guide*
  (Wiley). — **Wilks, D. S.** *Statistical Methods in the Atmospheric Sciences* (Academic Press).

## WRF precipitation / GRIB accumulation (used to justify de-accumulation)

- **WRF Users' Guide** — `RAINC`/`RAINNC` accumulated from init; total = RAINC + RAINNC.
  https://www2.mmm.ucar.edu/wrf/users/
- **ECMWF** — "Conversion table for accumulated variables (total precipitation/fluxes)",
  Copernicus Knowledge Base (confluence.ecmwf.int); **cfgrib** issue #321 (github.com/ecmwf/cfgrib)
  — GRIB accumulation/de-accumulation conventions.

## INPE / CPTEC (model provenance; DA-vs-cold-start still to confirm)

- **INPE CPTEC-WRF (CPT-WRF) Version 1.1 (2020).** Workshop da Divisão de Modelagem Numérica do
  Sistema Terrestre, CPTEC/INPE, Cachoeira Paulista, 30 Nov 2020.
  https://www.researchgate.net/publication/349641316 *(ResearchGate returned HTTP 429 at authoring;
  not fully parsed — consult directly to confirm the AMS 7 km assimilation/initialisation setup.)*
- **INPE Eta Model — Publications.** https://www3.cptec.inpe.br/eta/publications/
- **Frassoni, A. (2024).** Model development overview at INPE/CPTEC (WGNE-39 center update).
  WCRP-ESMO. https://www.wcrp-esmo.org/ *(center-update slide deck; for operational-config
  context.)*
- **CPTEC/INPE dataserver** — WRF AMS 7 km "brutos":
  https://dataserver.cptec.inpe.br/dataserver_modelos/wrf/ams_07km/brutos/  (source of the archive).

## Project-internal (this repository / claude.ai project)

- **`verif_core.py`** — validated verification metrics (categorical, extremal, FSS); the categorical
  definitions here are transcribed from it.
- **`TUPANN_vs_WRF_methodology.md`** — §B.3 estimates atmospheric spin-up at "roughly the first
  1–6 h" and states it is largely past by 9–12 h; §E **confirms** the from-init accumulation
  convention for these CPTEC files (basis for `fetch_wrf.py` de-accumulation).
- **`scripts/fetch_wrf.py`, `scripts/build_wrf_basins.py`, `scripts/archive_wrf_grid.py`** — the
  fetch → process → archive chain that produces `wrf_grid_archive.csv`.
- **Catão, A., Poveda, G., Voltarelli, R., Orenstein, P. (2025).** Precipitation nowcasting of
  satellite data using physically-aligned neural networks. arXiv:2511.05471. *(TUPANN — context for
  the project's verification framing.)*
