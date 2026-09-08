# SIP Automation — Setup Guide (New Machine)

This gets the app running on a new PC from a zipped copy of this project.

## 1. Prerequisites

- **Python 3.11** recommended (matches `pyproject.toml`). If you only have a
  newer Python (e.g. 3.13/3.14) available, that also works for this app —
  just create the virtual environment with whatever Python you have; there
  is nothing 3.11-specific in the actual code.
- **PostgreSQL** installed and running locally (or reachable over network).
  This project was tested against PostgreSQL 18, but any recent version works.

## 2. Extract the zip

Unzip `sip-automation.zip` anywhere, e.g. `C:\dev\sip-automation`.

## 3. Create a virtual environment and install dependencies

Open a terminal in the extracted `sip-automation` folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install pandas sqlalchemy "psycopg[binary]" pydantic pydantic-settings pyyaml openpyxl pyxlsb python-calamine structlog pyarrow python-dotenv psycopg2-binary fastapi uvicorn python-multipart
```

(If you have Poetry installed and Python 3.11 available, `poetry install` is
the cleaner option and installs the exact pinned versions from `pyproject.toml`.)

## 4. Configure the database connection

Copy `.env.example` to `.env` and fill in your real Postgres password:

```powershell
Copy-Item .env.example .env
notepad .env
```

Update `POSTGRES_PASSWORD` (and `POSTGRES_HOST`/`POSTGRES_USERNAME` if your
Postgres setup differs).

## 5. Create the database and load the schema

In pgAdmin, psql, or any Postgres client, create an empty database named
`SIP` (or whatever you set `POSTGRES_DATABASE` to), then load the schema:

```powershell
psql -h localhost -U postgres -d SIP -f db\schema.sql
```

This creates the `raw`, `canonical`, and `core` schemas/tables the app
expects — it does **not** contain any actual data, just table structure.

## 6. Run the app

```powershell
.\.venv\Scripts\python.exe -m uvicorn sip_automation.api.main:app --app-dir src --host 127.0.0.1 --port 8000 --reload
```

Then open **http://127.0.0.1:8000/ui/** in a browser.

## 7. Source files

The 5-6 Excel files you upload through the UI (employee, bp, sales,
nacs_guarantee, ytd_payments, bdm) are not part of this zip — get those from
whoever shared this project with you, or from your own source system export.

## Notes

- `data/precompute_exceptions.yaml` and `logs/precompute_exceptions_audit.log`
  will be created automatically the first time you use the Precompute
  Exceptions admin tab — nothing to set up manually there.
- `outputs/metric_engine/` and `storage/uploads/` are created automatically
  per pipeline run.
- The demo login password is in `src/sip_automation/api/static/app.js`
  (`SHARED_PASSWORD`), and the admin-tab password is also there
  (`ADMIN_PASSWORD`) — ask whoever shared this with you for those, or read
  the file directly since this is a demo-level, not real, authentication.
