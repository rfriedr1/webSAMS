# Transfer Target-to-Sample uses correct radiocarbon math, with opt-in legacy mode

When aggregating one or more **Target** measurements into a **Sample**-level result, the new app will average **Fraction Modern (FM)** values across the operator-selected targets and *derive* `c14_age` from the averaged FM, with sigmas combined in quadrature. The legacy Delphi app instead averaged ages and sigmas arithmetically (`SAMS_Main.pas:3911` `btnCalculateMeanClick`), which is mathematically incorrect but produced the historical results in the database. We will offer an opt-in legacy-math mode so operators can re-run historical transfers and reproduce prior numbers exactly.

We will **not** persist which targets contributed to a sample-level aggregate — operators rely on out-of-band records, and the field set on `sample_t` is fixed by the legacy schema we are not migrating.

## Update 2026-11: as built (`sams_web/sample_transfer.py`)

- The mean is the **inverse-variance weighted** FM mean (FM = Σ(f/σ²)/Σ(1/σ²), σ = 1/√Σ(1/σ²)), not a plain average with sigmas in quadrature; the age and its sigma are derived from it (−8033·ln FM, 8033·σ/FM). δ¹³C is the plain mean. The Ward & Wilson agreement test is shown, not enforced.
- A mean **clears the calibrated ranges** on the sample (they belong to one target; calibration is BATS's, ADR-0003). One chosen target is copied with its ranges.
- A sample with several measured targets has **nothing chosen by default**; the operator ticks. One measured target is chosen automatically.
- The legacy **lower-limit rule** is kept (FM < 2σ, σ ≥ 0.0005 → −8033·ln(FM + 2σ) rounded to 100, sigma 99999).
- The **opt-in legacy-math mode is not built** (the lab chose the weighted mean); add it if historical transfers must be reproduced.

