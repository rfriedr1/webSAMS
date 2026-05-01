# BATS owns measurement evaluation; webSAMS treats those fields as read-only

The data-evaluation software **BATS** (separate application sharing the same MySQL database) owns the post-measurement processing and writes the following `target_t` fields, which webSAMS displays but **must never write or recompute**:

- `fm`, `fm_sig`, `dc13`, `dc13_sig` — derived from raw AMS counts
- `c14_age`, `c14_age_sig` — derived from FM
- `cal1sMin`, `cal1sMax`, `cal2sMin`, `cal2sMax`, `cal_curve`, `calib` — calibration outputs
- `calcset` — pointer to BATS' evaluation run (`calc_set_t` / `calc_corr_t` / `calc_sample_t`)
- `editallowed` (`target_t`) — tri-state: `0` = not yet evaluated, `1` = evaluated but edit still possible, `2` = evaluated and frozen
- `editable` (`sample_t`) — sample-level lock with the same tri-state convention, also written by BATS

A second upstream system, **`db_dc14`**, holds the raw measurement currents (`le_curr`, `he_curr`). webSAMS will need to pull these into `target_t` eventually but does not yet.

webSAMS' Transfer-to-Sample workflow (see [ADR-0002](0002-sample-aggregation-math.md)) reads BATS-owned target fields and writes them to corresponding `sample_t` columns — this is allowed because the write target is sample-level, not target-level.

Adding calibration code to webSAMS (e.g. an OxCal / Calib integration), or any path that recomputes the BATS-owned target fields, is explicitly out of scope. This boundary explains why webSAMS' detail pages show those values without any "recalculate" affordance and why no Python calibration libraries are pulled in.
