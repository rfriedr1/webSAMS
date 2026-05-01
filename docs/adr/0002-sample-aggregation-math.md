# Transfer Target-to-Sample uses correct radiocarbon math, with opt-in legacy mode

When aggregating one or more **Target** measurements into a **Sample**-level result, the new app will average **Fraction Modern (FM)** values across the operator-selected targets and *derive* `c14_age` from the averaged FM, with sigmas combined in quadrature. The legacy Delphi app instead averaged ages and sigmas arithmetically (`SAMS_Main.pas:3911` `btnCalculateMeanClick`), which is mathematically incorrect but produced the historical results in the database. We will offer an opt-in legacy-math mode so operators can re-run historical transfers and reproduce prior numbers exactly.

We will **not** persist which targets contributed to a sample-level aggregate — operators rely on out-of-band records, and the field set on `sample_t` is fixed by the legacy schema we are not migrating.
