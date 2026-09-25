# SAMS Web — Server Installation Guide

> **Just want to install and run it on a PC?** Use [`quickstart.md`](quickstart.md) —
> clone, create `.env`, double-click the start script. This guide is for a
> *permanent* server: one that starts on its own at boot and serves the whole lab.

How to install, run, update and back up SAMS Web on a **Windows server** in the lab
network. A Linux variant is in [Appendix A](#appendix-a-linux-server-systemd);
running it on your own PC for development is in [Appendix B](#appendix-b-workstation--development).

> ### ⚠️ Read first: there is no login yet
> Anyone who can open the app's address can view **and change** every record, run
> imports that write to the database, edit Setup, and make the server send e-mail
> as the lab's mail account.
>
> Until a login exists, SAMS Web must be reachable **from the lab network only**:
> - never forward the port through a router, VPN gateway or reverse proxy to the internet
> - restrict the firewall rule to the lab subnet (section 8)
>
> Adding a login later (planned: Windows accounts via IIS) will not change anything
> else in this guide — see section 13.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Folder layout](#2-folder-layout)
3. [Get the code](#3-get-the-code)
4. [Configure `.env`](#4-configure-env)
5. [Install](#5-install)
6. [First run and verification](#6-first-run-and-verification)
7. [Run as a Windows service](#7-run-as-a-windows-service)
8. [Open the firewall for the lab network](#8-open-the-firewall-for-the-lab-network)
9. [First-time setup in the browser](#9-first-time-setup-in-the-browser)
10. [Updating and rolling back](#10-updating-and-rolling-back)
11. [Backups](#11-backups)
12. [Troubleshooting](#12-troubleshooting)
13. [Later: HTTPS and login via IIS](#13-later-https-and-login-via-iis)

All commands below are for **PowerShell run as Administrator** unless noted.
Paths assume the app lives in `C:\webSAMS`; adjust if you choose another folder.

---

## 1. What you need

| Item | Notes |
|---|---|
| Windows Server 2019 / 2022 / 2025 | Windows 10/11 also works. Administrator rights for setup. |
| **Python 3.13** (64-bit) from [python.org](https://www.python.org/downloads/windows/) | In the installer choose **Customize installation → Install Python for all users**. A per-user install under `C:\Users\…\AppData` is not readable by the service account. Tick *Add Python to environment variables*. The app was built and tested on 3.13; 3.11+ works but is not what the pinned packages were tested with. |
| **Git for Windows** from [git-scm.com](https://git-scm.com/download/win) | To clone and update. The repository is private: the first `git clone` asks you to sign in to GitHub. |
| **NSSM** (Non-Sucking Service Manager) from [nssm.cc](https://nssm.cc/download) | Runs SAMS Web as a Windows service. Copy `win64\nssm.exe` to e.g. `C:\Tools\nssm\` and add that folder to `PATH`. |
| Network access to MySQL | TCP **3306** from this server to the database host. Test: `Test-NetConnection 192.168.123.30 -Port 3306` → `TcpTestSucceeded : True`. |
| MySQL account | Read/write on the SAMS database. Never commit its password (it belongs only in `.env`). |
| Correct clock and time zone | Imports stamp `in_date` and the +90-day `desired_date` with the server's local date. |

Check Python afterwards (new PowerShell window):

```powershell
py -3.13 --version        # Python 3.13.x
git --version
nssm version
```

---

## 2. Folder layout

Keep the **code** and the **data SAMS writes at run time** apart, so `git pull` can never
overwrite settings and a reinstall can never lose them.

| Path | What | Written by | In git? |
|---|---|---|---|
| `C:\webSAMS\` | The application (git checkout) | you, on install/update | yes |
| `C:\webSAMS\.env` | Database URL and runtime options — **contains the DB password** | you, once | **no** (gitignored) |
| `C:\webSAMS\.venv\` | Python virtual environment | `pip` | no |
| `C:\webSAMS\logs\` | Service log files | the service | no (gitignored) |
| `C:\ProgramData\webSAMS\setup_data.json` | Live settings from *Setup* — **contains the SMTP password** | the app | **no** |
| `C:\webSAMS\sams_web\setup_data.example.json` | Secret-free snapshot of the lab's settings | developers | yes |

On first start there is no `setup_data.json` yet. SAMS then reads
`setup_data.example.json`, so the server begins with the lab's thresholds,
graphitization systems, import headings and e-mail templates. The first time
anyone clicks **Save** in Setup, SAMS creates the live file with all of that plus the change.

```powershell
New-Item -ItemType Directory -Force C:\ProgramData\webSAMS | Out-Null
```

---

## 3. Get the code

```powershell
cd C:\
git clone https://github.com/rfriedr1/webSAMS.git webSAMS
cd C:\webSAMS
New-Item -ItemType Directory -Force logs | Out-Null
```

Record which version you deployed, so you can go back to it (section 10):

```powershell
git log --oneline -1
git tag deploy-$(Get-Date -Format yyyy-MM-dd)
```

> Copying the folder instead of cloning also works, but then `git pull` is not
> available for updates. If you copy, copy from a checkout made on Windows so the
> `.bat` files keep their Windows line endings.

---

## 4. Configure `.env`

Create `C:\webSAMS\.env` (plain text, **no** `.txt` extension — in Explorer turn on
*View → File name extensions* to be sure):

```env
# Required. Which database this server works on — see the note below.
SAMS_DATABASE_URL=mysql+pymysql://<USER>:<PASSWORD>@192.168.123.30/<DATABASE>

# Live settings OUTSIDE the checkout (absolute path — the service does not
# necessarily start in C:\webSAMS, so a relative path would point elsewhere).
SAMS_SETUP_DATA_FILE=C:\ProgramData\webSAMS\setup_data.json

# Keep false on a server: true shows Python tracebacks in the browser.
SAMS_DEBUG=false
SAMS_SQL_ECHO=false

# Optional: name in the browser tab/header
# SAMS_APP_TITLE=SAMS Web
```

**Choosing the database.** Development runs against `db_dmams_test2`. The
production database `db_dmams` is shared with **BATS**, and SAMS writes to it
immediately: every import creates submitters, projects, samples, preparations
and targets that cannot be undone from the app. Point a server at `db_dmams`
only when you intend real use.

If the password contains `@ : / ? # %`, URL-encode those characters
(e.g. `@` → `%40`).

Lock the file down — it holds the database password:

```powershell
icacls C:\webSAMS\.env /inheritance:r /grant:r "Administrators:F" "SYSTEM:F"
# If the service runs as a dedicated account (section 7), let it read the file too:
# icacls C:\webSAMS\.env /grant "svc-websams:R"
```

---

## 5. Install

Install **exactly** the package versions the app was tested with, from
`requirements.lock.txt`. Do not use `pip install --upgrade` on a server.

```powershell
cd C:\webSAMS
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Quick self-check (must print `app-import-ok` and no errors):

```powershell
.venv\Scripts\python.exe -m compileall -q sams_web
.venv\Scripts\python.exe -c "from sams_web.main import app; print('app-import-ok')"
```

**If the locked install fails** (e.g. a package reports no Windows build for your
Python version): note the failing package, then install from the project's version
ranges instead — `.venv\Scripts\python.exe -m pip install -e .` — and report the
failure so the lock can be corrected. The lock was generated on macOS; the only
platform difference it encodes is that `uvloop` is skipped on Windows and
`colorama` is added.

---

## 6. First run and verification

Start it in the foreground once, before making it a service:

```powershell
cd C:\webSAMS
.\start_server_windows.bat
```

Expected output ends with `Uvicorn running on http://0.0.0.0:8502`. Leave it running and,
in a **second** PowerShell window, check:

```powershell
# the process is up
Invoke-RestMethod http://localhost:8502/api/health            # status: ok
# the database is reachable (this one queries MySQL)
Invoke-RestMethod http://localhost:8502/api/dashboard/counts  # queue numbers
```

Then open `http://localhost:8502/` in a browser on the server. The header shows
which database is connected — confirm it is the one you intended.

Stop with **Ctrl+C**.

> Use `start_server_windows.bat`, **not** `start_webapp_windows.bat`, on a server.
> The latter is a workstation launcher: it reinstalls packages on every start
> (a boot that fails whenever PyPI is unreachable), runs with `--reload`, listens on
> `127.0.0.1` only, and sets `SAMS_SETUP_DATA_FILE` itself — overriding `.env`.

---

## 7. Run as a Windows service

A service starts at boot, keeps running when nobody is logged in, and restarts
after a crash.

```powershell
nssm install webSAMS "C:\webSAMS\start_server_windows.bat"
nssm set webSAMS AppDirectory "C:\webSAMS"
nssm set webSAMS DisplayName "SAMS Web (LIMS)"
nssm set webSAMS Description "CEZA C14 laboratory information system - http://<server>:8502/"
nssm set webSAMS Start SERVICE_AUTO_START

# Log files, rotated at 10 MB
nssm set webSAMS AppStdout "C:\webSAMS\logs\service.log"
nssm set webSAMS AppStderr "C:\webSAMS\logs\service.log"
nssm set webSAMS AppRotateFiles 1
nssm set webSAMS AppRotateOnline 1
nssm set webSAMS AppRotateBytes 10485760

# Restart 5 s after an unexpected exit
nssm set webSAMS AppExit Default Restart
nssm set webSAMS AppRestartDelay 5000

nssm start webSAMS
nssm status webSAMS          # SERVICE_RUNNING
```

Repeat the two checks from section 6 (`/api/health`, `/api/dashboard/counts`).

### Which account the service runs as

By default NSSM runs the service as **LocalSystem**, which works immediately.
Better practice is a dedicated local account with only the rights it needs:

```powershell
# 1. create the account (you will be asked for a password)
New-LocalUser -Name svc-websams -Description "SAMS Web service" -PasswordNeverExpires
# 2. what it may touch
icacls C:\webSAMS                /grant "svc-websams:(OI)(CI)RX"
icacls C:\webSAMS\logs           /grant "svc-websams:(OI)(CI)M"
icacls C:\ProgramData\webSAMS    /grant "svc-websams:(OI)(CI)M"
icacls C:\webSAMS\.env           /grant "svc-websams:R"
# 3. run the service as it
nssm set webSAMS ObjectName ".\svc-websams" "<the password>"
nssm restart webSAMS
```

If the service then refuses to start with *error 1069 (logon failure)*, grant the
account **Log on as a service** under *Local Security Policy → Local Policies →
User Rights Assignment*.

### Everyday service commands

```powershell
nssm status  webSAMS
nssm stop    webSAMS
nssm start   webSAMS
nssm restart webSAMS
Get-Content C:\webSAMS\logs\service.log -Tail 50 -Wait     # follow the log
```

---

## 8. Open the firewall for the lab network

Allow the port **only from the lab subnet**. The address below is an example based
on the database's network (`192.168.123.x`); use your actual lab range.

```powershell
New-NetFirewallRule -DisplayName "SAMS Web (TCP 8502, lab network only)" `
  -Direction Inbound -Protocol TCP -LocalPort 8502 `
  -RemoteAddress 192.168.123.0/24 -Profile Domain,Private -Action Allow
```

From a lab PC, open `http://<server-name-or-ip>:8502/`. Bookmark that address for
all users.

---

## 9. First-time setup in the browser

Open **Setup** in SAMS Web and work through:

1. **E-mail** — server, port, security, username and sender are pre-filled from the
   lab's settings, but the **password is not** (it is never stored in git). Enter it,
   click **Save E-mail**, then use **Send a test e-mail** with your own address.
   Until this works, the import's confirmation e-mail stays disabled.
2. **Lab Warning Thresholds** — check Total C (µg) and prep-yield minimums.
3. **Graphitization Systems** — the list of system pills on the graphitization bench.
4. **Standard Thresholds** — dashboard colour limits for standards.
5. **Import Column Headings** — only if customers use headings SAMS doesn't recognise yet.

After the first **Save**, `C:\ProgramData\webSAMS\setup_data.json` exists; include it
in backups (section 11).

---

## 10. Updating and rolling back

```powershell
cd C:\webSAMS
git tag deploy-$(Get-Date -Format yyyy-MM-dd-HHmm)     # remember the running version
nssm stop webSAMS

git pull
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe -m compileall -q sams_web

nssm start webSAMS
Invoke-RestMethod http://localhost:8502/api/dashboard/counts
```

Users may need **one hard refresh** (Ctrl+F5) after an update; SAMS otherwise
versions its CSS/JS so browsers pick up changes automatically.

**Rolling back** to the version before the update:

```powershell
cd C:\webSAMS
git tag --list "deploy-*"                  # find the previous tag
nssm stop webSAMS
git checkout deploy-2026-09-22-0930        # the tag you want
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
nssm start webSAMS
```

To return to the latest version afterwards: `git checkout main`, then the update
steps again.

Settings are unaffected by updates and rollbacks — they live in
`C:\ProgramData\webSAMS\`, outside the checkout.

---

## 11. Backups

SAMS itself keeps almost nothing on the server — the data is in MySQL. Back up:

| What | Why |
|---|---|
| The MySQL database | All lab data. Handled by your database backup routine. |
| `C:\ProgramData\webSAMS\setup_data.json` | Settings, e-mail templates, SMTP password. |
| `C:\webSAMS\.env` | Database connection. Store the backup securely — it contains the password. |

The application folder itself can always be re-cloned from GitHub.

---

## 12. Troubleshooting

**Service won't start / stops immediately**
Read `C:\webSAMS\logs\service.log`. Most common:
- `SAMS_DATABASE_URL is required` → `.env` missing, misnamed (`.env.txt`), or unreadable by the service account.
- `No .venv in …` / `No .env in …` → messages from `start_server_windows.bat`; see sections 4–5.
- `[Errno 10048]` / *address already in use* → something else uses port 8502:
  `Get-NetTCPConnection -LocalPort 8502 | Select OwningProcess` then `Get-Process -Id <pid>`.

**Pages fail with a database error**
`Test-NetConnection <db-host> -Port 3306`; check user, password (URL-encoding!) and
database name in `.env`; check the MySQL user may connect **from this server's IP**.

**Setup changes are not saved**
The service account needs *Modify* on `C:\ProgramData\webSAMS` (section 7), and
`SAMS_SETUP_DATA_FILE` in `.env` must be that absolute path.

**Lab PCs cannot connect, but `http://localhost:8502` works on the server**
Firewall rule (section 8) missing or restricted to the wrong subnet; or the network
profile is *Public* (the rule above applies to *Domain* and *Private*).

**Confirmation / test e-mail fails**
Use **Setup → E-mail → Send a test e-mail**; it reports the mail server's reason.
The stored password is only reused for the saved server, port, security mode and
username — change any of those and you must type the password again.

**The page looks outdated after an update**
Ctrl+F5 once in that browser.

---

## 13. Later: HTTPS and login via IIS

Not needed for the internal-only setup above; planned for when SAMS gets a login.
The intended shape, so today's setup already fits:

- IIS on the same server, with **URL Rewrite** + **Application Request Routing**,
  terminates HTTPS on port 443 and forwards to `http://127.0.0.1:8502`.
- IIS **Windows Authentication** identifies the user from their domain login — no
  passwords stored in SAMS.
- SAMS then listens on localhost only: set `SAMS_HOST=127.0.0.1` for the service
  (`nssm set webSAMS AppEnvironmentExtra SAMS_HOST=127.0.0.1`) and remove the
  port-8502 firewall rule, so nothing can bypass IIS.

---

## Appendix A: Linux server (systemd)

Same structure as above: code in `/opt/webSAMS`, settings in `/var/lib/websams`.

```bash
sudo apt install -y git python3 python3-venv
sudo git clone https://github.com/rfriedr1/webSAMS.git /opt/webSAMS
cd /opt/webSAMS
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install -r requirements.lock.txt
sudo .venv/bin/python -m pip install --no-deps -e .
sudo mkdir -p /var/lib/websams && sudo chown www-data: /var/lib/websams
```

`/opt/webSAMS/.env` as in section 4, with
`SAMS_SETUP_DATA_FILE=/var/lib/websams/setup_data.json`; `sudo chmod 600 .env && sudo chown www-data: .env`.

`/etc/systemd/system/websams.service`:

```ini
[Unit]
Description=SAMS Web (LIMS)
After=network-online.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/webSAMS
ExecStart=/opt/webSAMS/.venv/bin/python -m uvicorn sams_web.main:app --host 0.0.0.0 --port 8502 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now websams
journalctl -u websams -f
```

Restrict port 8502 to the lab subnet in the host firewall (e.g. `ufw allow from 192.168.123.0/24 to any port 8502 proto tcp`).
Updates: `git pull`, the two `pip install` lines, `sudo systemctl restart websams`.

---

## Appendix B: Workstation / development

Covered by [`quickstart.md`](quickstart.md). In short: `start_webapp_windows.bat` /
`./start_webapp_macos.sh` create `.venv`, install from `requirements.lock.txt` (only
when it changed), and run on `http://127.0.0.1:8502/`. `HOST=0.0.0.0` opens it to
the network, `SAMS_DEV=1` turns on auto-reload, `PORT=…` changes the port.
