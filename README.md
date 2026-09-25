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

> **Installing on a server?** Follow [`docs/server_installation.md`](docs/server_installation.md) (Windows service, firewall, updates, backups). Servers install exact versions from `requirements.lock.txt` and start with `start_server_windows.bat`. There is **no login yet** — keep SAMS Web on the lab network only.

For development:

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -e .
```

3. Set environment variables (or copy `.env.example` values into your shell):

```bash
export SAMS_DATABASE_URL='mysql+pymysql://<USER>:<PASSWORD>@<HOST>/<DATABASE>'
# optional: setup/settings storage file (defaults to `sams_web/setup_data.json`)
# export SAMS_SETUP_DATA_FILE='/path/to/setup_data.json'
```

4. Start app:

```bash
uvicorn sams_web.main:app --reload --port 8502
```

5. Open:
- UI: http://127.0.0.1:8502/
- API docs: http://127.0.0.1:8502/docs

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
