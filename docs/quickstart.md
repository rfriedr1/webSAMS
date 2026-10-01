# SAMS Web — Quick Start

Install and run SAMS Web on a PC in about five minutes. No service, no
administrator setup: you start it when you need it and close the window to stop.
(For a permanent server that starts on its own, see
[`server_installation.md`](server_installation.md) — later.)

> **There is no login yet.** Anyone who can open the address can change data.
> By default the app is reachable only from the PC it runs on; only open it to
> the lab network deliberately (step 5), and never to the internet.

## 1. Install Python and Git (once per PC)

- **Python 3.14** from <https://www.python.org/downloads/> — in the installer tick
  **Add python.exe to PATH**. (3.13 is also tested; 3.11 and 3.12 work.)
- **Git** from <https://git-scm.com/download/> — defaults are fine.

Check in a new terminal / PowerShell window:

```
py --version          # Windows       → Python 3.14.x
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

When you see `[run] webSAMS is starting`, open **<http://127.0.0.1:8502/>** in a
browser on that PC. (On Windows the window also prints the address other PCs use.) The header shows which database
you are connected to — check it is the one you intended.

**To stop:** press `Ctrl+C` in the window, or just close it.

If instead you see `[setup] No .env file found`, step 3 was skipped or the file
is misnamed.

## 5. Who can open it

| | Default | Change it with |
|---|---|---|
| **Windows** (`start_webapp_windows.bat`) | **the whole lab network** | `set HOST=127.0.0.1` before starting → only this PC |
| **macOS / Linux** (`start_webapp_macos.sh`) | only this computer | `HOST=0.0.0.0 ./start_webapp_macos.sh` → the lab network |

Other PCs open `http://<this-pc's-name>:8502/` — the Windows launcher prints the
exact address when it starts. The first time, Windows Firewall asks whether to
allow Python: allow it for **private networks only**. On Windows Server there is
no prompt; an administrator adds the rule once (see `server_installation.md` §8).

Remember: **no login yet**, so everyone who can reach the port can edit data.
Keep it on the lab network; never forward the port to the internet.

To make a Windows PC private for one session:

```
Windows (cmd):          set HOST=127.0.0.1 && start_webapp_windows.bat
Windows (PowerShell):   $env:HOST="127.0.0.1"; .\start_webapp_windows.bat
```

## 6. First things to set up in the app

Open **Setup** in the top bar:

1. **E-mail** — the server details are pre-filled; enter the password, save, then
   use *Send a test e-mail* to your own address. Until this works, the import's
   confirmation e-mail stays disabled.
2. **Lab Warning Thresholds** and **Graphitization Systems** — check they match the lab.
3. **Sample Photos** — the folder with the sample photos, as this computer sees it
   (e.g. `R:\SAMS Images` when the drive is connected, or `\\<server>\<share>\SAMS Images`).
   Photos whose file name starts with the sample number then appear on the sample page.

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
| `No Python 3.11 or newer found` | Install Python 3.14 (step 1) with **Add to PATH** ticked |
| `.venv was created with an old Python` | Delete the `.venv` folder and start again |
| Upgraded Python (e.g. 3.13 → 3.14) and want to use it | Delete the `.venv` folder and start again — it keeps the Python it was made with |
| `[setup] No .env file found` | Create `.env` (step 3); check it isn't `.env.txt` |
| `SAMS_DATABASE_URL is required` | `.env` exists but the line is missing or commented out |
| Pages show a database error | Wrong user/password/database in `.env`, or no network route to `192.168.123.30:3306` |
| `Address already in use` on 8502 | SAMS is already running in another window, or set `PORT=8503` |
| Package install fails on first run | Needs internet once; corporate proxies may block PyPI — see `server_installation.md` §5 |
| Other PCs can't connect | Windows Firewall blocked Python (allow it for private networks), or on macOS/Linux it was started without `HOST=0.0.0.0` |

## For developers

`SAMS_DEV=1` before starting turns on auto-reload when code changes. Tests:

```
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```
