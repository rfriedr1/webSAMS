# AGENTS.md

## Project Purpose
- Create a laboratory LIMS software as a Python web application.
- Legacy delphi code (from a previous legacy LIMS system used in the laboratory) can be used as inspiration but new workflows, logics and design patterns should be/need to be explored
- UI/UX should be improved for browser use.
- Preserve clear OOP structure and maintainable layering.

## Repository Context
- Legacy reference code (read-only reference): `../delphi-code`
- Database schema notes: `schema_summary.md`

## App purpose
- the app serves as the main Laboratory Management and Information System (LIMS) of our radiocarbon laboratory
- use modern design patters regarding LIMS and regarding UI/UX
- Navigation between pages and data records needs to be easy and logical

## Domain Model
- One `Submitter` can have many `Projects`. (DB table is `user_t` for legacy reasons; see `docs/adr/0001-submitter-naming.md`.)
- One `Project` can have many `Samples`.
- One `Sample` can have many `Preparations`.
- One `Preparation` can have many `Targets`.
- `Targets` hold the information of the graphitization procedure and also the analytical results (C14 age etc etc) optianed from that target

## App Architecture
- `sams_web/main.py`: FastAPI app setup
- `sams_web/models.py`: SQLAlchemy ORM models
- `sams_web/repositories.py`: DB access/query layer
- `sams_web/services.py`: business logic/workflows
- `sams_web/routers/pages.py`: server-rendered web routes
- `sams_web/routers/api.py`: JSON API routes
- `sams_web/viewmodels/detail_sections.py`: detail-page field grouping/formatting
- `sams_web/templates/*`: Jinja templates
- `sams_web/static/app.js`: shared frontend behavior (table tools, navigation helpers)
- `sams_web/static/style.css`: global UI styling

## Data Access Strategy
- Use a pragmatic hybrid approach.
- Prefer ORM for entity-centric CRUD/detail flows (users, projects, samples, preparations, targets).
- Use raw SQL (or SQLAlchemy Core) for complex queue/search/report/worklist queries where SQL is clearer and/or more performant.
- Keep all DB access inside the repository layer and avoid query logic in routers/templates.

## Runtime and Configuration
- Python environment: `.venv` (local virtual environment)
- Install: `pip install -e .`
- Start app: `uvicorn sams_web.main:app --reload`
- Default env examples in `.env.example`
- Key variables:
- `SAMS_DATABASE_URL` (default: `mysql+pymysql://mams:Micadas.1@192.168.123.30/db_dmams`)
- `SAMS_SETUP_DATA_FILE` (default: `sams_web/setup_data.json`)

## UX/UI Invariants (Keep Consistent)
- Use modern design patters regarding visual alignment and sizing of UI objects and logical separation of control groups  
- Use modern, clean, consistent typography and card-based detail layouts.
- Each internal page should display breadcrumb navigation for orientation and quick backtracking.
- Keep history-based back navigation on detail pages. Back navigation should alway show where to link back to.
- Use icons instead of labelled buttons if the function of the icons are easily recognizable (don't do this in the primary and secondary navigation bar)
- Any table should provide:
- Search/filter
- Column sorting
- Download icon export (Excel-compatible)
- Internal scrolling within table container (avoid excessive page scrolling)
- No server-side pagination in UI tables (load full dataset; pagination, if needed later, should be client-side UX)
- Prefer inline links in tables for navigation to details (instead of row-click navigation).
- Keep link-column style consistent (underlined, colored, bold).
- In detail cards/views, align field values (text/number/date) to the right for scanability; keep comment/multiline fields left-aligned.
- In detail cards/views, do not use per-field hairlines; use subtle divider lines only at explicit group transitions.
- In detail pages, edit mode should be in-place: the same field box switches from display to editor (no duplicated display+editor stacked layout).
- Minimize layout shift in edit mode (stable row/card height where possible); multiline/comment fields may expand when needed.
- Highlight editable fields subtly in edit mode and visually mark changed (dirty) fields.
- Use the same dirty-dot visual pattern for task-focused bench UIs (e.g. `Preparation Bench Entry`, `Graphitization Bench Entry`) so users can quickly see unsaved changes and where they were made.
- Detail-page edit controls (`Edit`, `Save`, `Cancel`) should be right-aligned and visually lightweight (no persistent instructional hint text).
- When saving detail-page edits, show clear progress feedback on the `Save` button (spinner/loading state), and temporarily disable edit toolbar buttons to prevent double-submit while the request is in progress.
- Global search table can allow horizontal scrolling if needed.

## Magic Nav Rules
- Input only digits: treat as `sample_nr` and open sample detail.
- Prefix `pr` + digits: treat as `project_nr` and open project detail.
- Prefix `sub` + digits: treat as `user_nr` and open submitter detail.
- Magic commands:
- `/prep` opens `Lab/Preparation`
- `/graph` opens `Lab/Graphitization`
- `/ana` opens `Lab/Analysis`
- Unknown pattern: show `unknown ID`.
- Not-found IDs: show inline error in the patch area and do not navigate.
- Keep `/help` updated whenever Magic Nav behavior changes (prefixes, labels, validation, or routing targets).

## Detail Page Navigation Rules
- Maintain quick navigation on detail pages to quickly navigate to next and previous record with:
- Previous arrow
- Jump-to-number input
- Next arrow
- `/max` indicator
- Guard invalid jump input values and keep user on current record when invalid.

## Data Formatting Rules
- `C14 Age` and `C14 Sigma`: round/display as integers.
- `FM` and `FM Sigma`: round/display to 4 decimals.
- `d13C` and `d13C Sigma`: round/display to 4 decimals.
- `C (%)` (`conc_c`) and `N (%)` (`conc_n`): round/display to 1 decimal.
- `C/N Ratio`: calculate from EA values as `(conc_c/12.011)/(conc_n/14.007)` and round/display to 1 decimal.
- Boolean fields in detail cards: render as checkboxes (view mode).
- `stop` label in preparation/target detail views: `Discarded`.

## Settings and Setup
- Store setup data in a generic settings file, not feature-specific filenames.
- Current settings file: `sams_web/setup_data.json`.
- Setup page should remain extensible for future configuration modules.

## Current Workflow Notes
- Main navigation labels:
- `Dashboard`
- `Samples`
- `Lab`
- `Search`
- `Setup`
- `Help`
- `API Docs`
- Secondary navigation:
- Under `Samples`: `Sample`, `Projects`, `Submitters`
- Under `Lab`: `Preparation`, `Graphitization`, `Analysis`
- Breadcrumb navigation is shown on pages via the shared `base.html` layout.
- Dedicated detail pages exist for sample, preparation, and target.
- `Samples -> Sample` lands on `/samples`, which opens:
- last visited sample when available
- otherwise the highest `sample_nr` (newest sample)
- Sample page is a navigation hub to preparations and targets.
- Table features are centrally handled in `sams_web/static/app.js`; new tables should follow existing hooks to inherit behavior automatically.

## Development Guardrails
- Preserve existing behavior unless the user explicitly asks for change.
- Implement changes in shared layers when possible to avoid duplication.
- Keep templates focused on display; put logic in services/viewmodels/JS helpers.
- Prefer small, safe, incremental edits.

## Quick Validation
- Python syntax/import check: `python3 -m compileall sams_web`
- Frontend JS syntax check: `node --check sams_web/static/app.js`
