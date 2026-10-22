# NEXORA — Python Backend

The NEXORA backend uses FastAPI, environment-based configuration, an HTTP
health endpoint, a real-time WebSocket system, and PostgreSQL persistence
managed through SQLAlchemy and Alembic.

MQTT, device firmware, mobile app, voice assistant, AI, biometrics, cameras,
automation execution, and security features are not implemented in this phase.

## Project layout

```text
app/
├── __init__.py
├── api/
│   ├── __init__.py
│   └── routes/
│       ├── __init__.py
│       ├── events.py              # POST /events/test
│       └── health.py              # GET /health
├── core/
│   ├── __init__.py
│   ├── config.py                 # Environment-based settings
│   └── logging.py                # Logging configuration
├── db/
│   ├── __init__.py
│   ├── base.py                    # SQLAlchemy declarative base
│   ├── dependencies.py            # Request-scoped session dependency
│   ├── models.py                  # Initial persistent data models
│   └── session.py                 # Reusable engine and sessions
├── websocket/
│   ├── __init__.py
│   ├── connection_manager.py
│   └── events.py                  # Structured WebSocket events
└── main.py                       # FastAPI app and /ws endpoint
alembic/
├── env.py
├── script.py.mako
└── versions/                      # Database schema migrations
tests/
├── test_config.py
├── test_database.py
├── test_health.py
└── test_websocket.py
alembic.ini
.env.example
.gitignore
requirements.txt
```

## Requirements

- Windows 10 or later
- Python 3.10 or later
- Windows Terminal or PowerShell

Check Python from Windows Terminal:

```powershell
python --version
```

If `python` is not recognized, install Python from
<https://www.python.org/downloads/windows/>. During setup, select **Add
python.exe to PATH**, then reopen Windows Terminal.

## Create and activate a virtual environment

Run these commands from the NEXORA project folder:

```powershell
cd "$HOME\OneDrive\Documents\NEXORA"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, allow scripts only in the current terminal
process and retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Alternatively, in Command Prompt:

```bat
cd /d "%USERPROFILE%\OneDrive\Documents\NEXORA"
python -m venv .venv
.venv\Scripts\activate.bat
```

## Configure and install dependencies

With the virtual environment active in PowerShell:

```powershell
Copy-Item .env.example .env
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The `.env` file is ignored by Git. Values use the `NEXORA_` prefix, for example
`NEXORA_LOG_LEVEL=DEBUG`. Do not put passwords, keys, or other secrets in source
code.

## Install and create the PostgreSQL database

Install PostgreSQL for Windows from the official PostgreSQL download page:
<https://www.postgresql.org/download/windows/>. The Windows installer includes
the PostgreSQL server and command-line tools. Keep the port at `5432` unless
you have a reason to change it, and remember the password you set for the
initial `postgres` administrator account.

Open a new PowerShell terminal after installation. If `psql` is not on `PATH`,
run it from the PostgreSQL `bin` directory (commonly
`C:\Program Files\PostgreSQL\<version>\bin`):

```powershell
psql -U postgres -h localhost
```

At the `postgres=#` prompt, create the application login, set its password
using psql's hidden password prompt, and create the database:

```sql
CREATE ROLE nexora_user WITH LOGIN;
\password nexora_user
CREATE DATABASE nexora OWNER nexora_user;
\q
```

In the project folder, copy the safe sample configuration and edit `.env`:

```powershell
Copy-Item .env.example .env
notepad .env
```

Replace the `DATABASE_URL` placeholder password with the password created
above. The URL format is:

```text
postgresql+psycopg://nexora_user:YOUR_PASSWORD@localhost:5432/nexora
```

If the password contains URL-reserved characters, percent-encode them in the
URL. The `.env` file is ignored by Git; do not put credentials in source files
or commit them.

## Run database migrations

Alembic records the current migration revision in the `alembic_version` table.
Migration scripts define schema changes, so upgrades and rollbacks are
repeatable and tracked rather than manually recreating tables.

From the activated project virtual environment, apply the initial schema:

```powershell
python -m alembic upgrade head
```

After changing SQLAlchemy models, generate a migration, inspect the generated
file in `alembic\versions`, then apply it:

```powershell
python -m alembic revision --autogenerate -m "describe schema change"
python -m alembic upgrade head
```

Roll back one revision with:

```powershell
python -m alembic downgrade -1
```

`python -m alembic downgrade base` rolls back all migrations and drops the
tables created by the initial migration. Use that only when you intend to
remove the schema/data.

## Start FastAPI

From the project folder with the virtual environment active:

```powershell
python -m uvicorn app.main:app --reload
```

The API is available at <http://127.0.0.1:8000>. Interactive API documentation
is at <http://127.0.0.1:8000/docs>.

## Verify the PostgreSQL connection

After setting `DATABASE_URL` and applying migrations, check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

The JSON response includes `"database": "connected"` when PostgreSQL answers a
`SELECT 1` probe. If no database URL is set, it reports
`"database": "not_configured"`; if the configured database cannot be reached,
it reports `"database": "unavailable"` and `"status": "degraded"`. The response
never includes the connection URL or credentials. The endpoint continues to
return HTTP 200 so database trouble does not hide the availability of the
FastAPI service.

## Test the health endpoint

In a second Windows Terminal tab:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

With `DATABASE_URL` set and PostgreSQL reachable, the response should be:

```json
{
  "status": "ok",
  "service": "NEXORA",
  "database": "connected"
}
```

Without a configured database, the response still reports a healthy API with
`"database": "not_configured"` instead.

## Test the WebSocket endpoint

Keep Uvicorn running. In a second terminal, activate the virtual environment
and run this one-line WebSocket client:

```powershell
python -c "from websockets.sync.client import connect; ws=connect('ws://127.0.0.1:8000/ws', legacy=True); ws.send('hello'); print(ws.recv()); ws.close()"
```

The server should print:

```text
NEXORA received: hello
```

The `websockets` client is installed by `uvicorn[standard]`. The automated
WebSocket test also checks multiple messages on the same connection.

## Test real-time broadcasts

The development endpoint `POST /events/test` broadcasts a structured JSON
system event to every client connected to `/ws`. Keep the backend running and
open two separate PowerShell terminals in the project folder. Activate the
virtual environment in both:

```powershell
.\.venv\Scripts\Activate.ps1
```

In the first terminal, connect a client that exits after receiving one event:

```powershell
python -c "from websockets.sync.client import connect; ws=connect('ws://127.0.0.1:8000/ws', legacy=True); print('Connected; waiting for broadcast...'); print(ws.recv()); ws.close()"
```

In the second terminal, connect a client that stays open for multiple events:

```powershell
python -c "from websockets.sync.client import connect; ws=connect('ws://127.0.0.1:8000/ws', legacy=True); print('Connected; waiting for broadcasts...'); exec('while True: print(ws.recv())')"
```

With both clients waiting, use a third terminal to trigger a broadcast:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/events/test
```

Both WebSocket terminals should print the same event, containing `type`,
`source`, `message`, and a UTC `timestamp`. The first client then closes. Run
the broadcast command again; the second, still-connected client should receive
another event without affecting the backend.

Run the automated tests, including the two-client broadcast/disconnect test,
with:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

## Run tests

In a separate terminal with the project virtual environment activated:

```powershell
python -m pytest -v
```

Tests run migrations against a temporary SQLite database, verify the database
session/health probe, and check that existing health and WebSocket features
remain available. PostgreSQL itself must be running and configured to verify
a live PostgreSQL connection.

## Troubleshooting

- **`python` is not recognized:** Install Python for Windows, select
  **Add python.exe to PATH**, and reopen the terminal.
- **Activation is disabled:** Use the process-scoped execution policy command
  above, or activate from Command Prompt with `activate.bat`.
- **`No module named ...`:** Activate `.venv`, then run
  `python -m pip install -r requirements.txt`.
- **Port 8000 is already in use:** Start with
  `python -m uvicorn app.main:app --reload --port 8001` and use port 8001 in
  the health and WebSocket URLs.
- **WebSocket connection fails:** Confirm the server is running, use the
  `ws://` scheme and `/ws` path, and check that the client is not using a
  different port.

## How this phase fits the NEXORA architecture

FastAPI remains the Python API layer. Its WebSocket manager handles real-time
clients, while SQLAlchemy sessions provide persistence to PostgreSQL and
Alembic manages database schema changes. Later phases may connect the backend
to MQTT, Mosquitto, and ESP32 devices; those integrations are not included
here.
