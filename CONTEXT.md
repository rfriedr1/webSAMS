# webSAMS

LIMS for a radiocarbon (C14) dating laboratory. Tracks work from sample submission through chemical preparation, graphitization, AMS measurement, and reporting. Shares its MySQL database (`db_dmams`) with **BATS**, a separate data-evaluation application that owns the calibration step (see [ADR-0003](docs/adr/0003-calibration-owned-by-bats.md)).

## Language

**Submitter**:
A person or organisation that submits samples to the laboratory for radiocarbon dating. Holds contact, organisational, and invoicing details.
_Avoid_: User, Client, Customer.

**Project**:
A lab work order from a **Submitter**, comprising one or more **Samples** to be dated. Distinct from the submitter's broader research project, which is captured separately by the `research` field.
_Avoid_: Job, Order.

**Project status**:
A fixed vocabulary describing where a **Project** sits in its lifecycle. Stored in `projectstatus_t`. Workflow values: `planned` → `running` → `closed`. The transition to `closed` is auto-derived from `out_date` (see [ADR-0004](docs/adr/0004-project-auto-close-on-out-date.md)). Plus `prepaid`, which is a billing flag riding in the same field by legacy convention — see below.

**Sample**:
A submitted physical material to be dated, *or* a reference material (see **Standard**). Stored in `sample_t`. For submitter samples: belongs to one **Project** and carries reported sample-level C14 results, manually aggregated by an operator from a chosen subset of the sample's measured **Targets**.
_Avoid_: Specimen, Material.

**Standard**:
A reference material (oxalic acid, IAEA-C, blanks, etc.) used to calibrate AMS measurements. Stored as a row in `sample_t` whose `type` matches a `sampletype_t` row flagged as a standard (certified `f14c`, `d13c_nom`, or `blank` values populated). Standards travel through **Prep batches**, **Graph batches**, and **Magazines** alongside submitter samples but have no meaningful **Submitter** or **Project**.
_Avoid_: Reference, Calibrator, Standard sample (verbose).

**Pre-submission treatment**:
Free-text record of any treatment the submitter performed on the material before sending it to the lab (e.g., rinsed, sieved, dried). Stored on `sample_t.pre_sub_treat`. Recorded by the lab at sample intake; never represents lab-side preparation work.
_Avoid_: Pretreatment (ambiguous with Preparation), Pre-treatment.

**Sample type**:
Highest-level **Sample** classification, with statistical/calibration semantics. Stored on `sample_t.type` → `sampletype_t`. Distinguishes real submitter samples from **Standards** and blanks; carries certified `f14c`, `d13c_nom`, and `blank` reference values. The only one of the three Sample classifications (type/material/fraction) with workflow consequences.
_Avoid_: Type (bare — too generic in software speak).

**Material**:
The physical material submitted for dating (bone, charcoal, wood, shell, peat, etc.). A property of the sample as received and stays fixed. Stored on `sample_t.material` → `material_t`. Descriptive only; no workflow branching.
_Avoid_: Substance.

**Fraction**:
The chemical fraction extracted during preparation that actually gets dated (collagen from bone, cellulose from wood, humic acids vs. humins from peat, carbonate from shell). A choice of the lab's preparation protocol. Stored on `sample_t.fraction` → `fraction_t`. Descriptive only; no workflow branching.
_Avoid_: Extract, Component.

**Preparation EA**:
Bulk Elemental Analyser reading of the prepared material before graphitization — used as prep-level QC (was the prep successful enough to commit to graphitization). Stored on `preparation_t.c_percent`, `n_percent`, `cn_ratio`. One reading per **Preparation**.

**Target EA**:
Per-**Target** elemental yields measured during graphitization, from the actual aliquot that became this target. Stored on `target_t.conc_c`, `conc_n`. The displayed sample/target C/N ratio is calculated from these as `(conc_c/12.011)/(conc_n/14.007)`. Distinct from **Preparation EA** — not a copy.

**BATS**:
A separate data-evaluation application that shares the `db_dmams` MySQL database with webSAMS. Owns post-measurement processing: writes `fm`, `dc13`, `c14_age`, calibration ranges, `cal_curve`, `calib`, and `calcset` on `target_t`, plus the `calc_*_t` tables. webSAMS displays these values but never writes them. See [ADR-0003](docs/adr/0003-calibration-owned-by-bats.md).
_Avoid_: Calibration tool, Eval app.

**db_dc14**:
A third upstream database (separate from `db_dmams`) that holds the raw AMS measurement currents. webSAMS will eventually pull `le_curr` / `he_curr` from it into `target_t`. Not integrated yet.

**Preparation**:
A chemical pre-treatment run on a **Sample**, executed as up to five sequential method steps. One sample may have multiple preparations (different protocols, replicates, or re-runs).
_Avoid_: Pretreatment, Prep run.

**Target**:
A graphitized specimen produced from a **Preparation**, pressed into a cathode and loaded into the AMS for measurement. Carries the raw AMS measurement values (FM, δ¹³C, C14 age, calibration ranges) for that specific specimen.
_Avoid_: Cathode, Specimen.

**Prep batch**:
A cohort of **Samples** and **Standards** chemically pre-treated together in a single preparation run. Recorded on `preparation_t.batch`.
_Avoid_: Batch (bare).

**Graph batch**:
A cohort of pre-treated material (samples and standards) graphitized together in one graphitization unit/instrument. Recorded on `target_t.graph_batch`.
_Avoid_: Batch (bare).

**Magazine**:
A cohort of graphitized **Targets** (samples and standards) measured together in one run on the AMS (radiocarbon accelerator). Holds 40 positions; position 1 is always empty, so a magazine carries up to 39 targets. Magazine names encode the instrument, year, month, and day of the measurement run (e.g. `MA251030` = AMS instrument `MA`, 2025-10-30). Created and populated in webSAMS (planned); handed off to BATS after measurement.
_Avoid_: Batch (bare).

**Position**:
The physical slot of a **Target** in a **Magazine** (1–40, with 1 always empty). Stored on `target_t.position` and `measprog_t.position`.

**Preparation bench**:
The operator's workspace for executing one **Preparation** at a time, advancing through the planned-samples queue. Captures weights, pre-treatment method steps, and prep timestamps. Owns bench-specific chemistry: derives `weight_end` from the two intermediate weighings when the operator hasn't entered it directly, auto-stamps `prep_start` / `prep_end` from today's date when the corresponding weight has just been entered, and validates `prep_end >= prep_start`.
_Avoid_: Prep workflow, Prep page.

**Graphitization bench**:
The operator's workspace for graphitizing one **Target** at a time, advancing through the waiting-for-graph queue. Captures combustion weight, target comments, and the prep/sample logistics flags that go with shipping a target into graphitization. Hosts the **Graph batch** assignment workflow as a sibling operation on the same page.
_Avoid_: Graph workflow, Graph page.

**Sequence**:
The measurement order of a **Target** within a **Magazine**, as stored in `measprog_t.sequence`. Independent of **Position** — operators may measure in a different order than the physical layout (e.g. interleaving standards regardless of slot).

## Relationships

- A **Submitter** owns one or more **Projects**.
- A **Project** has exactly one **Project status** at any time.
- A **Project** contains one or more **Samples** (submitter samples only — **Standards** do not belong to a Project).
- A **Sample** has one or more **Preparations**.
- A **Preparation** produces one or more **Targets**.
- A **Target** carries the raw AMS measurement results for its specimen.
- A **Sample** carries reported C14 results, manually aggregated from a chosen subset of its **Targets** (math: see [ADR-0002](docs/adr/0002-sample-aggregation-math.md)).
- The `return_to_sender` / `returned_to_sender` flags on **Project** are orthogonal to **Project status** (a project can be `running` or `closed` regardless of return-to-sender state).
- A **Preparation** belongs to one **Prep batch**.
- A **Target** belongs to one **Graph batch** at the graphitization stage and to one **Magazine** at the measurement stage.
- A **Prep batch**, **Graph batch**, or **Magazine** may contain a mix of **Samples** and **Standards**.

## Flagged ambiguities

- "User" in the legacy database (table `user_t`) and Delphi UI refers to a **Submitter**, not a software-login user. The login-user concept does not yet exist in the codebase and is reserved for a future authentication layer.
- `prepaid` is stored as a value of **Project status** but is semantically a billing flag, orthogonal to the lab workflow. It does not affect lab handling. Read `status = 'prepaid'` as "prepaid project, billing already settled" — workflow position must be inferred from the `*_date` fields rather than `status` for these projects.
- The bare word "batch" is overloaded across **Prep batch**, **Graph batch**, and **Magazine** — three distinct lab events. Always qualify which one is meant.
- `stop = 1` on **Preparation** always means **workflow termination** — the prep was aborted and no targets will follow. UI labels this as "Discarded".
- `stop = 1` on **Target** primarily means workflow termination, but may also mean "measured, result flagged invalid" — distinguish by whether measurement results (`fm`, `c14_age`, etc.) are populated. UI labels this as "Discarded" in both cases. Stopped targets are not auto-excluded from sample-level aggregation; the operator selects contributing targets manually (see [ADR-0002](docs/adr/0002-sample-aggregation-math.md)).
- `sample_t.preparation` (free-text 255-char field) is a legacy summary of preparation work, mainly redundant with the structured `preparation_t` rows. The **Preparation** records are the source of truth; treat the string field as legacy read-only metadata and do not write to it from new code paths.
- `target_t.editallowed` and `sample_t.editable` look like booleans but are **tri-state**: `0` = not evaluated yet, `1` = evaluated and still editable by BATS, `2` = evaluated and frozen. Both are written by BATS, never by webSAMS. UI must read all three states correctly — treating the field as a boolean will silently break the "not yet evaluated" case.
