# CLAUDE.md

## Project Purpose
- Create a laboratory LIMS software as a Python web application.
- Legacy delphi code (from a previous legacy LIMS system used in the laboratory) can be used as inspiration but new workflows, logics and design patterns should be/need to be explored
- UI/UX should be improved for browser use.
- Preserve clear OOP structure and maintainable layering.

## Repository Context
- Legacy reference code (read-only reference): `../delphi-code`
- Database schema notes: `schema_summary.md`
- Domain glossary and bounded vocabulary: `CONTEXT.md` — read this first before naming new things; flagged ambiguities are listed at the bottom.
- Architecture decision records: `docs/adr/` — sequentially numbered. Don't re-litigate decisions here without checking these first.

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
- `sams_web/models.py`: SQLAlchemy ORM models. Class names use domain language (`Submitter`); table names stay legacy (`user_t`).
- `sams_web/repositories.py`: DB access/query layer
- `sams_web/services.py`: business logic/workflows
- `sams_web/detail_update.py`: generic single-entity form-update primitive (`apply_detail_update` + `DetailUpdateConfig` per entity). All write paths flow through here; per-entity configs live next to the viewmodels.
- `sams_web/detail_page.py`: generic detail-page context builder (`build_detail_page_context` + `DetailPageConfig`). Read side of detail pages.
- `sams_web/preparation_bench.py` / `graphitization_bench.py`: bench workflow modules (`PreparationBench`, `GraphitizationBench`) — page_view() + save() + (graph) assign_graph_batch().
- `sams_web/magic_nav.py`: sealed `NavTarget` family + parser + match-based dispatchers for the magic-nav input.
- `sams_web/search.py`: `SearchContext` registry + `run_search()` + `fk_based_link()` rule for cell-level row links.
- `sams_web/routers/pages.py` and the per-area `pages_*.py`: server-rendered web routes (thin dispatchers).
- `sams_web/routers/api.py`: JSON API routes
- `sams_web/viewmodels/detail_sections*.py`: detail-page field grouping/formatting + per-entity configs (`SUBMITTER_DETAIL`, `PROJECT_DETAIL`, etc. for write; `*_DETAIL_PAGE` for read).
- `sams_web/templates/*`: Jinja templates
- `sams_web/static/app.js`: shared table-tools etc.
- `sams_web/static/js/*.js`: per-feature modules (toast, page-progress, detail-shortcuts, searchable-select, navigation-ui, magic-nav-ui, history-back, table-tools, detail-edit-mode, prep/graph bench UIs).
- `sams_web/static/style*.css`: split per concern (`style-core`, `style-detail-pages`, `style-tables`, `style-benches`, `style-settings-kpi`); `style.css` is the entrypoint that imports them.

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
- Highlight editable fields subtly in edit mode and visually mark changed (dirty-dots) fields.
- Use the same dirty-dot visual pattern for task-focused bench UIs (e.g. `Preparation Bench Entry`, `Graphitization Bench Entry`) so users can quickly see unsaved changes and where they were made.
- Detail-page edit controls (`Edit`, `Save`, `Cancel`) should be right-aligned and visually lightweight (no persistent instructional hint text).
- When saving detail-page edits, show clear progress feedback on the `Save` button (spinner/loading state), and temporarily disable edit toolbar buttons to prevent double-submit while the request is in progress.
- Global search table can allow horizontal scrolling if needed.
- **Empty values render as a muted italic em-dash (`—`)**, never `Not set` or `null` or `N/A`. The dash uses `.detail-empty` styling (italic, low contrast). The detection helper is `viewmodels.detail_sections_common.is_empty_display_value(value)` — it returns True for `None`, blank/whitespace strings, sentinel string tokens (`"undefined"`, `"null"`, `"n/a"`, `"none"`), and **sentinel dates with year < 1950** (legacy null stand-ins like `1899-12-30`). All `format_*_value` formatters route through this helper. New value formatters should call it; new templates should render the `—` via `<span class="detail-empty">—</span>`.
- **Long detail-page metadata sections collapse by default.** Use `<details>` (no `open` attribute) for "Additional Metadata" blocks. When the block holds 2+ sections, render an in-page TOC chip row at the top so operators can jump.
- **Sections whose every row is empty are dropped at build time.** Pass `drop_all_empty_sections=True` to `build_sections(...)` for verbose detail pages (sample currently uses this — preparation/target/project don't, by choice).
- **Header column labels live in `routers.pages_shared.TABLE_HEADER_LABELS`.** When adding a new column to a search context, dashboard table, or any other list, register a human label there. Unknown columns fall back to `snake_case → Title Case`.
- **Empty-state table rows** (`<td class="table-empty-row">`) use centred italic muted text and call out the relevant CTA (e.g. "Use **+ Prep** above to create one"). Don't ship the bare "No rows found" sentence.
- **Save / notice feedback fires as a toast** (top-right, auto-dismissing) via `window.SAMSToast.show(message, kind)` where `kind` ∈ `success | error | info`. The toast module also auto-promotes `?saved`, `?bench_saved`, `?graph_saved`, `?graph_batch_saved`, and any `*_notice` query params on page load and strips them from the URL via `history.replaceState`. Inline panel-head feedback is allowed alongside, but the toast is the primary surface.
- **Decorative animations and the blurred bg-shapes respect `@media (prefers-reduced-motion: reduce)`** — they're hidden / shortened for users who opted out.
- **Every interactive element has a visible `:focus-visible` outline** (`2px solid var(--brand-2)` with `2px` offset). When you add a new clickable thing, include it in the focus-ring rule list in `style-core.css`.
- **Three responsive breakpoints**: 1024px (large), 860px (medium), 640px (small). At 640px: the brand subtitle hides, cards stack to one column, inputs/buttons grow to ~44px touch targets, the magic-nav input fills its row.

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

## Detail Page field hierarchy
- The fields listed below are the *headline fields* that carry the main information about each entity. They render at the top of the detail page as `<article>` cards inside a `.cards` grid, organized into labelled **groups** — each group is a `<section class="card-group">` with a small uppercase title. Less important fields stay in the collapsible/section-grid below.
- Group labels stay short and noun-form (e.g. `Identity`, `Classification`, `Measurement Results`). When adding a new headline field, place it in the group whose label best describes its meaning rather than spinning up a new group.
- Numeric/categorical headline cards are display-only; identity-text and comment cards are editable in-place via the `.detail-field-shell-card` pattern so they participate in the page's edit-mode toggle.
- Empty values render as the muted italic `—` per the standard empty-value rule. Boolean fields render as the disabled-checkbox badge (`.detail-boolean-check`) so the value is visible at a glance.
- Generic CSS hooks: `.card-group` / `.card-group-title` (group container + label), `.detail-headline-cards` and `.detail-comments-cards` (variant card rows). Comment cards are full-width single-column; metric cards inherit the dashboard `.cards` auto-fit grid.

	### Submitter
	- **Identity** — Salutation · First Name · Last Name (editable)

	### Project
	- **Identity** — Project Name (editable, spans 2 cols) · Status (badge)
	- **Timeline** — In Date · Desired Date · Out Date
	- **Comments** — Project Comment (editable, full-width)

	### Sample
	- **Identity** — Sample Label · Sample Label # · Description 1 · Description 2 (all editable)
	- **Classification** — Type · Material · Fraction · Weight
	- **Measurement Results** — C14 Age · C14 Age Sigma
	- **Comments** — Submitter Comment · Lab Comment (both editable, two-column)

	### Preparation
	- **Batch & Timeline** — Batch · Prep Start · Prep End
	- **Outcome** — Yield (%) · Discarded · No Leftover · Targets (count)
	- **Comments** — Preparation Comment (editable, full-width)

	### Target
	- **Graphitization** — Graph Batch · Graphitized · Magazine · Discarded
	- **Elemental Analysis** — C (%) · N (%) · C/N Ratio · Total C (µg) *(calculated from `Weight Combustion` × `C (%)`; warning highlight when below the configured Lab Warning Threshold)*
	- **Measurement Results** — C14 Age · C14 Age Sigma · FM · FM Sigma · d13C
	- **Comments** — Target Comment (editable, full-width)


## Data Formatting Rules
- `C14 Age` and `C14 Age Sigma`: round/display as integers.
- `FM` and `FM Sigma`: round/display to 4 decimals.
- `d13C` and `d13C Sigma`: round/display to 4 decimals.
- `C (%)` (`conc_c`) and `N (%)` (`conc_n`): round/display to 1 decimal.
- `C/N Ratio`: calculate from EA values as `(conc_c/12.011)/(conc_n/14.007)` and round/display to 1 decimal.
- Boolean fields in detail cards: render as checkboxes (view mode).
- `stop` label in preparation/target detail views: `Discarded`.
- Empty / sentinel values: render as muted italic `—` (see UX/UI Invariants for the full empty-value rule).

## Frontend Modules and Shared Behaviours
- **Toasts**: `window.SAMSToast.show(message, kind, { duration })`. `kind` defaults to `info`; `duration` defaults to ~4.5s, pass `0` for sticky. Auto-fires on save query params.
- **Keyboard shortcuts within a record** (active when the page contains `[data-edit-scope]`): `e` toggle edit, `Esc` cancel, `Ctrl/Cmd + S` save (always intercepted, even while typing), `[` or `j` previous record, `]` or `k` next record, `?` open the cheat-sheet overlay. Suppressed while typing in inputs (except Save).
- **Searchable selects**: any `<select>` with more than 8 real options is auto-enhanced into a type-to-filter combobox by `searchable-select.js`. Mark a select with `data-no-searchable` to opt out. The shim commits back to the native `<select>` so server-side form handling is unchanged.
- **Page progress bar**: indeterminate top-of-page sweep on form submit / link navigation, via `page-progress.js`. No setup needed; appears automatically.
- **Pinned / Recent quick-access groups** auto-hide when their list is empty. Don't render placeholder "No pinned pages" text — that's deliberately removed.
- **Breadcrumbs** auto-hide when there is only the root crumb (the page title already says where you are).

## Settings and Setup
- Store setup data in a generic settings file, not feature-specific filenames.
- Current settings file: `sams_web/setup_data.json`.
- Setup page should remain extensible for future configuration modules.

## Lab Warning Thresholds
- The canonical list of in-app warning thresholds lives in `LAB_WARNING_THRESHOLD_FIELDS` in `sams_web/lab_warning_thresholds.py` — that tuple drives the Setup → "Lab Warning Thresholds" editor, the JSON persistence in `setup_data.json`, and the per-field formatting rules. Don't duplicate the list elsewhere; treat the code as source of truth and the Setup page as the user-facing rendering.
- Each threshold has its own evaluator in `sams_web/viewmodels/lab_warnings.py` returning a `WarningOutcome` dict keyed by the threshold's key. Evaluators are pure (no DB / no service / no request), so warnings stay easy to test and easy to extend.
- Detail-page integration is declarative: the entity's `DetailPageConfig` carries a `warnings_builder` callable, and `build_detail_page_context` exposes results as `{name}_warnings`. Templates branch via `render_detail_display_card(..., warning=*_warnings.get('<threshold_key>'))` — the macro handles the red-card highlight and the inline hint.
- To add a new warning: (1) append a `LabWarningThresholdField` entry, (2) extend the relevant `evaluate_*_warnings` function (or write a new one + wire it via `warnings_builder`), and (3) reference the warning key in the right card on the detail template. The Setup UI picks up the field automatically.

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
- `Samples -> Sample` lands on `/samples`, which is a **landing page** (not a redirect) with action cards: Resume last sample (only when different from newest), Newest sample, Browse all samples (→ `/search?context=samples`), and a Magic Nav explainer. The "last sample" is read from the `last_sample_nr` cookie.
- Sample page is a navigation hub to preparations and targets.
- Table features are centrally handled in `sams_web/static/app.js`; new tables should follow existing hooks to inherit behavior automatically.
- Dashboard layout: two side-by-side conceptual panels — **Lab Queues** (Planned / In Prep / Waiting for Graph / Waiting for Meas / Express + queue distribution chart) and **Standards Ready for Analysis** (Oxas / Blanks / Pferde / IAEA-C6 / IAEA-C7 / IAEA-C8 + standard distribution chart). Each chart sits inside a `<details>` collapsible.

## Development Guardrails
- Implement changes in shared layers when possible to avoid duplication.
- Keep templates focused on display; put logic in services/viewmodels/JS helpers.
- Prefer small, safe, incremental edits.

## Quick Validation
- Python syntax/import check: `python3 -m compileall sams_web`
- Frontend JS syntax check: `for f in sams_web/static/app.js sams_web/static/js/*.js; do node --check "$f"; done`
- App import smoke: `.venv/bin/python -c "from sams_web.main import app; print(len(app.routes))"`
- Routes smoke: `for path in / /samples /samples/<n> /projects/<n> /submitters/<n> /lab/preparation /lab/graphitization /search?context=samples; do curl -s -o /dev/null -w "$path -> %{http_code}\n" http://127.0.0.1:8000$path; done`
