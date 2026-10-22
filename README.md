# NEXORA — Phase 1: Real-Time Python Foundation

Phase 1 establishes the Python backend used as the central service layer in the
NEXORA architecture. It includes a FastAPI application, environment-based
configuration, basic logging, an HTTP health endpoint, and an asynchronous
WebSocket endpoint.

This phase intentionally does **not** add a database, MQTT, device firmware,
mobile app, voice assistant, AI, biometrics, cameras, automation, or security
features.

## Project layout

```text
app/
├── __init__.py
├── api/
│   ├── __init__.py
│   └── routes/
│       ├── __init__.py
│       └── health.py              # GET /health
├── core/
│   ├── __init__.py
│   ├── config.py                 # Environment-based settings
│   └── logging.py                # Logging configuration
├── websocket/
│   ├── __init__.py
│   └── connection_manager.py
└── main.py                       # FastAPI app and /ws endpoint
tests/
├── test_health.py
└── test_websocket.py
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
py --version
```

If `py` is not recognized, install Python from <https://www.python.org/downloads/windows/>.
During setup, select **Add python.exe to PATH**, then reopen Windows Terminal.
The `python` command can be used instead of `py` in the commands below if that
is how Python is installed on your computer.

## Create and activate a virtual environment

Run these commands from the NEXORA project folder:

```powershell
cd "$HOME\OneDrive\Documents\NEXORA"
py -3 -m venv .venv
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
py -3 -m venv .venv
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

## Start FastAPI

From the project folder with the virtual environment active:

```powershell
python -m uvicorn app.main:app --reload
```

The API is available at <http://127.0.0.1:8000>. Interactive API documentation
is at <http://127.0.0.1:8000/docs>.

## Test the health endpoint

In a second Windows Terminal tab:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

The response should be:

```json
{
  "status": "ok",
  "service": "NEXORA"
}
```

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

## Run tests

In a separate terminal with the project virtual environment activated:

```powershell
python -m pytest -v
```

Both the health endpoint and WebSocket message exchange should pass.

## Troubleshooting

- **`py` or `python` is not recognized:** Install Python for Windows, select
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

## How Phase 1 fits the NEXORA architecture

FastAPI provides the Python API foundation; asyncio-backed WebSockets provide
the live communication path for future clients. Configuration and logging are
centralized so later services can be added without putting database, MQTT,
device, or interface logic into route handlers. Subsequent phases will add
those components in the order specified by the NEXORA system specification.
