# Installation

OmniOSINT runs on your own computer. Windows 10/11 (64-bit) is the primary
platform; Linux, including WSL2, is supported.

Your data (settings, protected secrets, logs, backups) is stored separately from
the program, so updating, reinstalling or deleting the program folder does not
touch it:

| Platform | Data folder |
|---|---|
| Windows | `%LOCALAPPDATA%\OmniOSINT` |
| Linux | `~/.local/share/OmniOSINT` |

Set `OMNIOSINT_HOME` to use another location.

## Requirements

| Component | Version | Needed for |
|---|---|---|
| Windows 10/11 64-bit, or Linux x86-64 | | |
| Python | 3.12 or 3.13, 64-bit | Running OmniOSINT |
| PostgreSQL | 15 or later (14 works but is out of support) | Storing everything |
| Node.js | 22.22 or later | Building the web interface |
| Memory / disk | 4 GB RAM, 2 GB free disk recommended | |
| Redis | 6 or later | Optional; not used for anything essential yet |
| Docker Desktop | Any recent | Optional way to run PostgreSQL |
| Rust toolchain | Stable | Only to build the desktop shell yourself |

The installer checks all of these and tells you what is missing. It installs
nothing system-wide without asking you first.

## Windows

1. Get the code: clone the repository, or download and extract a release.
2. Double-click **`install.bat`** (or run it from a terminal).

   The installer:
   * checks Windows, memory and disk space;
   * finds Python 3.12+ (offers to install it with winget if missing, only if
     you agree);
   * creates `.venv` in the program folder and installs the exact, hash-checked
     dependency versions from `requirements.txt`;
   * builds the web interface (offers to install Node.js the same way);
   * prepares the database, asking you to choose between:
     1. **Create the database on a PostgreSQL server on this computer.** You
        enter the password of the `postgres` administrator account once; it
        is used only to create an `omniosint` account and database and is not
        stored. The new account's random password goes into the protected
        secret store.
     2. **Use an existing database.** Enter host, port, database name, user and
        password.
     3. **Run PostgreSQL in Docker Desktop** (listens on 127.0.0.1:5433).
     4. **Skip for now.**
   * creates or upgrades the database schema;
   * runs the diagnostics (`omniosint doctor`).

   A log of the run is written to `logs\setup-<date>.log` in the data folder.

3. Double-click **`start.bat`**. It checks the configuration and the database,
   starts the API and the background worker, waits until they report healthy
   and opens your browser. On the very first start the browser opens the
   first-run setup page with the one-time setup token already filled in:
   create your administrator account there.

That window can be closed: OmniOSINT keeps running until you run `stop.bat`.

### Windows scripts

| Script | What it does |
|---|---|
| `install.bat` | Install or repair. Safe to run again |
| `start.bat` | Start and open the interface (`--no-open` to skip the browser) |
| `stop.bat` | Stop cleanly |
| `restart.bat` | Stop, then start |
| `health-check.bat` | Is it running and healthy, then full diagnostics |
| `update.bat` | Stop, back up, fetch the new version, re-run setup, start again |
| `backup.bat` | Back up the database and settings |
| `restore.bat` | Restore a backup (lists backups when run without a file) |
| `uninstall.bat` | Remove what the installer created; keeps your data unless you say otherwise |

`install.bat` options (passed to `setup.ps1`): `-NonInteractive`,
`-InstallMissing`, `-Update`, `-SkipFrontend`,
`-Database ask|bootstrap|existing|docker|skip`, `-PostgresAdminUser`,
`-PythonPath`. Run `Get-Help .\setup.ps1 -Detailed` for details.

The scripts run PowerShell with `-ExecutionPolicy Bypass` for their own process
only; no system setting is changed.

### Installing PostgreSQL on Windows

If you do not have PostgreSQL yet, either:

* install it from <https://www.postgresql.org/download/windows/> (the
  installer asks you to choose a password for the `postgres` account; keep it
  for the next step), then run `install.bat` and choose option 1; or
* install Docker Desktop, run `install.bat` and choose option 3.

## Linux and WSL2

```bash
scripts/linux/install.sh
```

The same steps as on Windows; it installs no system packages and tells you what
is missing (for example `sudo apt install python3.12 python3.12-venv`).
Options: `--update`, `--skip-frontend`, `--non-interactive`,
`--database ask|bootstrap|existing|docker|skip`, `--pg-admin-user NAME`,
`--python PATH`.

On a local PostgreSQL server you can also create the account by hand:

```bash
sudo -u postgres createuser --pwprompt omniosint
sudo -u postgres createdb -O omniosint omniosint
.venv/bin/omniosint secrets set database.password
.venv/bin/omniosint db upgrade
```

Then:

```bash
.venv/bin/omniosint start --open
.venv/bin/omniosint status
.venv/bin/omniosint stop
```

## Desktop application (optional)

The desktop shell starts and stops OmniOSINT for you and shows the interface in
its own window. Build it with `npm run build` in `desktop\` (needs Rust); see
[desktop/README.md](../desktop/README.md). Install OmniOSINT itself first.

## Configuration

Defaults are in `config/settings.yaml` (do not edit; it is replaced on update).
Change settings in the data folder, either by hand in
`config\settings.yaml` or with the command line:

```bash
omniosint config set server.port 9000
omniosint config show
omniosint config paths
```

Secrets never go into settings files:

```bash
omniosint secrets set database.password
```

On Windows the secret store is protected with DPAPI for your user account.
Environment variables such as `OMNIOSINT_SERVER__PORT` override everything;
see `.env.example`.

## Updating

Windows: run `update.bat`. It stops OmniOSINT, makes a backup (label
`pre-update`), pulls the new version when the folder is a git checkout, re-runs
setup and starts OmniOSINT again. For a downloaded release, extract it over the
program folder and run `update.bat -NoPull`.

Linux: `git pull`, then `scripts/linux/install.sh --update`.

## Backup and restore

```bash
omniosint backup create            # or backup.bat
omniosint backup list
omniosint backup verify FILE
omniosint stop
omniosint backup restore FILE      # or restore.bat FILE
```

A backup is a zip archive with a PostgreSQL dump, your user settings file and
checksums. It needs the PostgreSQL command line tools (`pg_dump`, `pg_restore`,
`psql`); set `database.pg_bin_dir` if they are not on PATH.

* Restoring replaces all data in the database, in one transaction: it either
  completes or changes nothing. The current data is backed up first.
* The audit trail is part of the data and is restored too; entries made after
  the backup was taken remain in that automatic pre-restore backup.
* **Backups are not encrypted** in this version. Keep them on an encrypted
  volume. Secrets are not included; re-enter them after restoring on another
  computer.

## Uninstalling

`uninstall.bat` stops OmniOSINT and removes `.venv`, the web interface build
and the desktop build output. It keeps your data folder unless you type
`DELETE` when asked (or pass `-RemoveData`), and never touches the database. To
remove the database, an administrator runs `DROP DATABASE omniosint; DROP ROLE
omniosint;` (or `docker compose down --volumes` for the Docker option). Then
delete the program folder.

## Troubleshooting

Start with:

```bash
omniosint doctor
```

| Symptom | Likely cause |
|---|---|
| `start` says the port is in use | Another program uses 8765: `omniosint config set server.port 8800` |
| Database "authentication failed" | Wrong password: `omniosint secrets set database.password` |
| Database "connection refused" | PostgreSQL is not running |
| Schema "out of date" after an update | `omniosint db upgrade` |
| Browser shows "web interface has not been built" | Install Node.js 22.22+, run `install.bat -Update` |
| Secret store "cannot be unlocked" | Secrets are bound to the Windows account that stored them; enter them again |

Logs are in the `logs` folder of the data folder: `api.log` and `worker.log`
(JSON lines), plus `api.out.log` and `worker.out.log` with each process's raw
output.
