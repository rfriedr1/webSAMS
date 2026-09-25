# SAMS Web — Quick Start

Install and run SAMS Web on a PC in about five minutes. No service, no
administrator setup: you start it when you need it and close the window to stop.
(For a permanent server that starts on its own, see
[`server_installation.md`](server_installation.md) — later.)

> **There is no login yet.** Anyone who can open the address can change data.
> By default the app is reachable only from the PC it runs on; only open it to
> the lab network deliberately (step 5), and never to the internet.

## 1. Install Python and Git (once per PC)

- **Python 3.13** from <https://www.python.org/downloads/> — in the installer tick
  **Add python.exe to PATH**. (3.11 or 3.12 also work.)
- **Git** from <https://git-scm.com/download/> — defaults are fine.

Check in a new terminal / PowerShell window:

```
python --version      # Windows       → Python 3.13.x
python3 --version     # macOS / Linux
git --version
```

## 2. Get the code

```
git clone https://github.com/rfriedr1/webSAMS.git
cd webSAMS
```

The repository is private; Git will ask you to sign in to GitHub the first time.

## 3. Tell it which database to use

Copy `.env.example` to `.env` in the same folder and open `.env` in a text editor
(Notepad is fine — make sure the file is named exactly `.env`, not `.env.txt`).

Fill in the one required line:

```
SAMS_DATABASE_URL=mysql+pymysql://<USER>:<PASSWORD>@192.168.123.30/db_dmams_test2
```

- `db_dmams_test2` is the **test copy** — start here.
- `db_dmams` is the **live lab database**, shared with BATS. Imports write to it
  immediately and cannot be undone from the app; switch only when you mean it.

Windows: `copy .env.example .env` · macOS/Linux: `cp .env.example .env`

## 4. Start it

| | |
|---|---|
| **Windows** | double-click `start_webapp_windows.bat` (or run it from a prompt) |
| **macOS / Linux** | `./start_webapp_macos.sh` |

The first start picks the newest Python 3.11+ on the PC, creates a private
environment in `.venv`, and installs the exact tested package versions from
`requirements.lock.txt` — allow a minute or two and an internet connection.
Every later start skips that and takes seconds.

If it stops with *No Python 3.11 or newer found*, step 1 was skipped. If it says
the `.venv` folder *was created with an old Python*, delete that folder and start
again.

When you see

```
[run] SAMS Web is starting on http://127.0.0.1:8502/
```

open **<http://127.0.0.1:8502/>** in a browser. The header shows which database
you are connected to — check it is the one you intended.

**To stop:** press `Ctrl+C` in the window, or just close it.

If instead you see `[setup] No .env file found`, step 3 was skipped or the file
is misnamed.

## 5. Optional: let other lab PCs use it

By default only the PC running SAMS can open it. To share it on the lab network,
set `HOST` before starting:

```
Windows (PowerShell):   $env:HOST="0.0.0.0"; .\start_webapp_windows.bat
Windows (cmd):          set HOST=0.0.0.0 && start_webapp_windows.bat
macOS / Linux:          HOST=0.0.0.0 ./start_webapp_macos.sh
```

Others then open `http://<this-pc's-name-or-ip>:8502/`. Windows Firewall will ask
once whether to allow Python on private networks — allow it for **private
networks only**. Remember: no login yet, so everyone on the network can edit.

## 6. First things to set up in the app

Open **Setup** in the top bar:

1. **E-mail** — the server details are pre-filled; enter the password, save, then
   use *Send a test e-mail* to your own address. Until this works, the import's
   confirmation e-mail stays disabled.
2. **Lab Warning Thresholds** and **Graphitization Systems** — check they match the lab.

Settings are saved to `sams_web/setup_data.json` inside the folder. It is not in
git, so it survives updates; back it up if you customise a lot.

## 7. Updating

```
git pull
```

then start as usual — the launcher notices when the package list changed and
reinstalls. Press `Ctrl+F5` once in the browser if a page looks stale.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No Python 3.11 or newer found` | Install Python 3.13 (step 1) with **Add to PATH** ticked |
| `.venv was created with an old Python` | Delete the `.venv` folder and start again |
| `[setup] No .env file found` | Create `.env` (step 3); check it isn't `.env.txt` |
| `SAMS_DATABASE_URL is required` | `.env` exists but the line is missing or commented out |
| Pages show a database error | Wrong user/password/database in `.env`, or no network route to `192.168.123.30:3306` |
| `Address already in use` on 8502 | SAMS is already running in another window, or set `PORT=8503` |
| Package install fails on first run | Needs internet once; corporate proxies may block PyPI — see `server_installation.md` §5 |
| Other PCs can't connect | Started without `HOST=0.0.0.0`, or Windows Firewall blocked Python |

## For developers

`SAMS_DEV=1` before starting turns on auto-reload when code changes. Tests:

```
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```
