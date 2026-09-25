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
- `sams_web/sample_import/`: Excel submission-sheet import (see "Sample Import" below)
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
- Start app: `uvicorn sams_web.main:app --reload --port 8502` (or `./start_webapp_macos.sh`). **The app runs on port 8502**, not uvicorn's default 8000 — both start scripts default to it; override with `PORT=…`.
- Default env examples in `.env.example`
- **Servers**: install from `requirements.lock.txt` (exact pins) + `pip install --no-deps -e .`, start with `start_server_windows.bat` (no `--reload`, no package installs, binds `0.0.0.0`, one worker, honours `.env`). The full procedure is `docs/server_installation.md` — **update it whenever the port, env vars, settings path, start command or dependencies change.** `start_webapp_*.{bat,sh}` are workstation launchers only.
- **Regenerating the lock** after a deliberate upgrade: `pip freeze --exclude-editable`, then re-add the two platform markers — `uvloop` has no Windows build (`; sys_platform != "win32"`) and `colorama` is Windows-only.
- **No login exists yet**: the app must stay on the lab network. Planned: IIS in front with Windows Authentication (guide §13).
- `.gitattributes` forces CRLF for `*.bat` on checkout — cmd.exe mis-parses LF-only batch files.
- Key variables:
- `SAMS_DATABASE_URL` — **required, no default** (`config.py` refuses to start without it). Format `mysql+pymysql://<USER>:<PASSWORD>@<HOST>/<DATABASE>`; the real value lives only in the gitignored `.env`. Never write credentials into a tracked file.
- `SAMS_SETUP_DATA_FILE` (default: `sams_web/setup_data.json`) — the **live** settings file. It is gitignored because it holds the SMTP password; on a server point it at an absolute path outside the checkout (e.g. `C:\ProgramData\webSAMS\setup_data.json`) so `git pull` never touches it.
- `sams_web/setup_data.example.json` is the secret-free, tracked snapshot. `SetupStore` reads it whenever the live file does not exist yet, so a fresh install starts with the lab's settings; the first save writes the live file. To carry a settings change into git, copy it into the example and blank every password.

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
- **Detail rows whose value is longer than 24 characters stack**: label on its own line, value full-width and left-aligned (`.detail-field-row.is-long-value`, set in `_detail_fields.html` from the value's length). A side-by-side label/value pair only reads well while the value is short; institution names, addresses and e-mails otherwise wrap into ribbons. The rule is length-driven, not field-name-driven, so it holds for every entity.
- In detail cards/views, do not use per-field hairlines; use subtle divider lines only at explicit group transitions.
- **The field box (`.detail-field-shell`) is an editing affordance, not decoration.** In view mode it is drawn with a transparent border and no fill, so a section reads as a plain label/value list; the box appears on hover of an editable row, in edit mode, quick-edit, dirty, error and warning states. Keep the border 1px transparent rather than removing it, so switching modes never shifts layout. (Before this, ~40 outlined boxes per detail page — most holding only `—` — were the largest source of visual noise.)
- **Field labels are sentence case** (`var(--text-sm)`, weight 600, muted). Uppercase tracked text is reserved for `.card-group-title` and section heads, so structure outranks fields.
- **Empty rows collapse per section.** The row macro adds `.is-empty-value` when `row.value is none`; `detail-empty-fields.js` hides those rows (`.is-empty-hidden`) behind a per-section "N empty fields hidden" toggle whose state persists for the session. Edit mode overrides the hiding through CSS so every field stays fillable, and the toggle itself is hidden while editing. Uses a dedicated class, not `hidden`, precisely so the edit-mode override can win without `!important`.
- In detail pages, edit mode should be in-place: the same field box switches from display to editor (no duplicated display+editor stacked layout).
- Minimize layout shift in edit mode (stable row/card height where possible); multiline/comment fields may expand when needed.
- Highlight editable fields subtly in edit mode and visually mark changed (dirty-dots) fields.
- Use the same dirty-dot visual pattern for task-focused bench UIs (e.g. `Preparation Bench Entry`, `Graphitization Bench Entry`) so users can quickly see unsaved changes and where they were made.
- Detail-page edit controls (`Edit`, `Save`, `Cancel`) should be right-aligned and visually lightweight (no persistent instructional hint text).
- When saving detail-page edits, show clear progress feedback on the `Save` button (spinner/loading state), and temporarily disable edit toolbar buttons to prevent double-submit while the request is in progress.
- Tables use `table-layout: auto` with `min-width: 100%`, so each column takes the width its content needs; `.table-wrap` scrolls horizontally when the total exceeds the panel. Never go back to `table-layout: fixed` — it split the width evenly and shredded long values (a project name got the same 109px as a 3-digit count).
- `td` uses `overflow-wrap: break-word`, never `word-break: break-word` / `overflow-wrap: anywhere`. The latter zeroes the cell's min-content contribution, letting an auto-layout column collapse below its longest word.
- `thead th` never wraps, so a column is always at least as wide as its own label.
- Date columns are detected from cell content by `table-tools.js` and tagged `.table-col-atomic` (nowrap + tabular numerals) — a hyphen is a legal break opportunity, so `2026-01-28` otherwise wraps to `2026-` / `01-28`.
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
- `/sub` opens `Samples/Submitters` (the list — distinct from the `sub<number>` prefix, which opens one submitter)
- `/proj` opens `Samples/Projects`
- `/import` opens `Samples/Import`
- Commands are matched *before* the `pr` / `sub` prefixes and always start with `/`, so a new command can never shadow an identifier form. Add one by extending `MAGIC_IDENTIFIER_COMMAND_ROUTES` + `..._LABELS` in `magic_nav.py`; the `/help` rules table is generated from those dicts, but the cheat-sheet overlay (`magic-nav-ui.js`), the command palette's own `magicCommandMap` (`navigation-ui.js`), the input's rotating placeholders (`base.html`), the `/help` prose list and `not_found.html` are hand-written and must be updated too.
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
- **Headline values come from the headline builders, never raw ORM attributes.** Every value a detail-page card displays must route through the entity's `build_*_headline` (which calls `format_*_value`) — templates read `{name}_headline.<key>`. Passing `sample.type` directly leaks legacy sentinel strings like `"undefined"` and sentinel dates into the UI. Editable cards pass `display_value={name}_headline.<key>` alongside `raw_value`.
- **Global asset bundles**: `base.html` loads `/static/bundle.css` + `/static/bundle.js` (concatenated + minified in `main.py`, cached per process, `Cache-Control: immutable`). **Bump the `css_v` global in `routers/pages_shared.py` whenever any static asset changes** — it's the cache-bust signal. Bench CSS/JS load only on the bench page via `extra_styles`/`extra_scripts` blocks.
- **Page-specific JS registers into `window.SAMSAppInstallers`; `app.js` dispatches the list.** `app.js` ships inside `bundle.js`, which is the *first* deferred script, so its dispatch must wait for `DOMContentLoaded` — `document.readyState === "interactive"` is already true while later deferred scripts (the bench modules) are still pending. Running on `interactive` silently no-opped `installers.installGraphitizationBench?.()` and killed both bench UIs. Only `readyState === "complete"` may run immediately.
- **`[hidden]` always wins**: `style-core.css` has a global `[hidden] { display: none !important; }` reset. Never work around it with a class-based show/hide; toggle the `hidden` property.
- **Design tokens**: type scale (`--text-xs` 0.72 · `--text-sm` 0.84 · `--text-base` 0.92 · `--text-md` 1 · `--text-lg` 1.18 · `--text-xl` 1.4 · `--text-2xl` 1.66 · `--text-3xl` 1.96 rem, plus `--text-h2/h3/h4`) and 4px spacing scale (`--space-1` … `--space-6`) live in `:root` in `style-core.css`. **Every text `font-size` must be a token** — the stylesheets were consolidated from 43 distinct literal sizes onto this scale, and a literal rem value is only acceptable for a glyph (stepper arrows, dirty dot, close ×, dropzone icon). Bands when choosing: xs = micro labels/badges, sm = labels, notes, table cells, base = field values and body copy, md = headings inside cards / buttons.
- **A capped list must never rely on the in-table filter for search.** `table-tools.js` filters only the rows already in the DOM, so on a truncated list it silently reports "no matches" for records that exist — searching *Friedrich* on `/submitters` found nothing because the first 500 rows alphabetically stopped at *Ebinger-Rist*. Either load the whole table or give the page a server-side search box; never a cap plus a client-side filter alone.
- `/submitters` **loads all rows** (~2 700 → ~846 KB / ~70 ms), so its one search box filters everything.
- `/projects` keeps the 500-row cap (12 985 rows render to ~9.2 MB, an order of magnitude worse) and instead has a **server-side** search form (`?q=`) covering project name, number, status and submitter, plus `?show_all=true`. `repositories.count_projects()` / `count_submitters()` back the honest "N of M" banners.
- **Starlette is pinned `<1.0`** in `pyproject.toml`: Starlette 1.0 changed `TemplateResponse(name, ctx)` → `TemplateResponse(request, name, ctx)`. Migrate all ~27 call sites before lifting the pin.
- **Sub-nav rows only render for modules with 2+ destinations** — single-chip sub-navs that duplicate the main nav item are deliberately removed (`navigation.py`).
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

## Sample Import (Excel submission sheets)
- Customers return filled-in copies of `templates/Submit_Samples_Template.xlsx`. The importer reads the `.xlsx` **directly** — no CSV export step (that was a legacy Delphi limitation).
- Wizard at `/samples/import` (Samples → Import), four steps: **Upload → Review & fix → Lab values → Imported (+ e-mail)**.
- Module layout in `sams_web/sample_import/`:
	- `vocabulary.py` — normalisation + fuzzy label matching, and the *built-in* heading synonyms.
	- `fields.py` — **the importable-field registry.** Built-in fields plus operator-defined ones resolved into one `FieldRegistry` (synonyms / labels / allow-list / lookup-backed set). `SAMPLE_TARGET_COLUMNS` is derived from the `Sample` ORM model, so a new model column is automatically available as an import target; `BLOCKED_TARGET_COLUMNS` keeps identity and BATS-owned result columns off-limits.
	- `workbook.py` — `.xlsx` → normalized `Grid` of `Cell`s; picks the submission worksheet by content score.
	- `parser.py` — finds the sample-table header by *scoring every row* against the registry's headings, then reads the metadata block above it as `label | value` pairs. **Nothing is addressed by fixed row/column index.**
	- `draft.py` — typed, JSON-serialisable results; every value carries its source cell address.
	- `matching.py` — submitter scoring (e-mail ≫ surname+organisation ≫ surname) and lookup resolution.
	- `commit.py` — the single transaction. `mailer.py` — render + SMTP send. `service.py` — glue for the router.
- **Adding an import column needs no code change.** Setup → *Import Column Headings* has two parts: extra spellings for built-in fields, and *Additional columns* where the operator picks a target `sample_t` column, a label, and the headings that map to it. Stored in `setup_data.json` as `{"headings": {...}, "custom": [...]}`; the old flat shape is still read.
- **Layout flexibility.** Header row = whichever row scores ≥ 2 recognised columns (`MIN_HEADER_MATCHES`). Unrecognised columns are kept per-row in `SampleDraft.extras` and offered for manual mapping — data is never silently dropped. Template helper text ("erforderlich/required") is filtered by `is_noise()`.
- **Controlled vocabularies are enforced server-side.** `material` / `type` / `fraction` must exist in `material_t` / `sampletype_t` / `fraction_t`; near misses are *suggestions*, never silent coercion, and `commit.py` re-validates the browser payload and falls back to `"undefined"`.
- **Lab values vs customer values.** The customer's own material text is only a *grouping key*. Step 3 groups rows by it and the operator assigns the lab's `type` / `material` / `fraction` plus prep steps 1–5 (`method_t`) per group — with a tick-rows-and-apply toolbar for arbitrary selections, and per-row overrides in the table. Only an exact lookup hit is pre-applied; fuzzy suggestions wait for a click.
- **Submitter / invoice.** Scored candidates first, a browse-and-search picker over all submitters, or create-new with the full editable field set (incl. `salutation`, `title`, `language`, `user_comment` — `language` selects the e-mail template). The invoice recipient is a *second* `user_t` row linked via `project_t.invoice_nr`, and is matched independently.
- **Duplicate projects.** When the chosen submitter already has a same/similar-named project, the wizard offers *add to that project* or *create a separate one* with a suggested `<name>_<Month>_<Year>`. Appending skips project creation and leaves the existing project's settings untouched.
- Project fields come from lookup tables: `projecttype_t`, `research_t`, `reporttype_t`, `advisor_t` (supervisor), plus priority 0/1/2 and the `free_of_charge` / `return_to_sender` / `prep_return_to_sender` flags.
- Intake defaults (`commit.py`): `status='planned'`, `priority=1`, `price='300'`, `in_date=today`, `desired_date=+90 days`, sample `type/material/fraction='undefined'`, `editable=1`.
- **Column widths come from the live MySQL schema, not `models.py`** — the ORM over-declares several (`user_label` is 100 in the DB, `material` 20). See `_SAMPLE_WIDTHS` / `_CONTACT_WIDTHS` / `_PROJECT_WIDTHS`.
- A commit creates, in one transaction: submitter (reused or new) → optional invoice recipient → project (new or existing) → one sample per row, each with preparation #1 carrying its prep steps, and target #1.
- **Setup → E-mail has a *Send a test e-mail* panel** (`POST /setup/email/test`). It posts the fields as currently typed — unsaved edits included — so settings can be verified before saving; a field sent empty is honoured as empty (blanking the username really does test an unauthenticated relay). The **password is the one exception**: it is never rendered back into the page, and blank means "reuse the stored one" both here and on save. Test sends never copy the configured Bcc.
- **Confirmation e-mail is never sent automatically.** After a commit the wizard renders the message (recipient, subject, body with `MAMS-<nr>` numbers paired to the customer's labels) and the operator edits, skips, or clicks Send. SMTP settings and per-language templates live in Setup → *E-mail*; `EmailSettingsStore.template_for_language()` picks by the submitter's `language`, falling back to English. Mail failures never roll back the import — the records are already committed.

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
- Under `Samples`: `Sample`, `Projects`, `Submitters`, `Import`
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
- Routes smoke: `for path in / /samples /samples/<n> /projects/<n> /submitters/<n> /lab/preparation /lab/graphitization /search?context=samples; do curl -s -o /dev/null -w "$path -> %{http_code}\n" http://127.0.0.1:8502$path; done`
