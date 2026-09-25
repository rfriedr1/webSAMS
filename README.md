# SAMS Web (Python Migration)

This repository now includes a Python web application that migrates the Delphi SAMS LIMS to a browser-based system.

## What is already migrated

- Core architecture: FastAPI + SQLAlchemy + Jinja templates
- OOP domain model for core entities:
  - `user_t`, `project_t`, `sample_t`, `preparation_t`, `target_t`
- Service/repository layer mirroring key `_dm.pas` methods:
  - queue dashboards (`planned`, `in prep`, `waiting for graph`, `waiting for measurement`, `express`)
  - global table search (`users`, `projects`, `samples`, `preparations`, `targets`)
  - user/project/sample drill-down
  - create user, create project, create sample (+ blank prep + blank target)
  - transfer target age to sample
  - set project status to `running`
  - project-status maintenance check (`closed` if all dated/discarded)

## Run

**Installing on a new PC?** Follow [`docs/quickstart.md`](docs/quickstart.md):
install Python + Git, clone, copy `.env.example` to `.env`, double-click the start
script. Five minutes, no administrator setup.

- Windows: `start_webapp_windows.bat` · macOS/Linux: `./start_webapp_macos.sh`
- Opens on <http://127.0.0.1:8502/>; set `HOST=0.0.0.0` to share on the lab network.
- A permanent server that starts on its own (Windows service, firewall, updates)
  is described in [`docs/server_installation.md`](docs/server_installation.md).

There is **no login yet** — keep SAMS Web on the lab network only.

Manual equivalent of the start script:

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -r requirements.lock.txt
python -m pip install --no-deps -e .
python -m uvicorn sams_web.main:app --port 8502
```

## New Python structure

- `sams_web/main.py`: app entrypoint
- `sams_web/models.py`: ORM models
- `sams_web/repositories.py`: SQL/data access
- `sams_web/services.py`: business workflows (ported from `_dm.pas`)
- `sams_web/routers/pages.py`: browser pages
- `sams_web/routers/api.py`: JSON API
- `docs/migration_map.md`: Delphi -> Python mapping

## Notes

- The migration intentionally starts with the highest-value workflows from `_dm.pas` and `SAMS_Main.pas`.
- More Delphi features (Word reports, email templates, camera integration, full wizard behavior, admin dialogs) can be ported in phases.
