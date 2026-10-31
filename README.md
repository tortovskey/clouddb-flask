# CloudDB

A Flask database management demo with a serverless-style console for virtual
databases, schemas, records, audit logs, exports, SQLite snapshots, and backups.

## Features

- User registration and sign-in.
- Isolated workspaces: users access only their own databases, tables, records, and backups.
- Virtual databases and tables defined with JSON schemas.
- Column types: `text`, `number`, `boolean`, `date`, and `json`.
- Record creation, editing, deletion, filtering, and sorting.
- Type-aware sorting, including correct numeric ordering.
- Global search across databases, tables, and records.
- JSON array imports and table exports in JSON or CSV.
- Isolated SQLite snapshots of selected virtual databases.
- Backup creation, SQLite downloads, and restoration into a new database.
- A dashboard showing autoscaling, regions, function invocations, storage usage, backup status, and audit events.

## SQLite snapshots

The `Download DB` button creates an isolated SQLite snapshot of the selected
virtual database. The application's raw `database.db` file is not exposed through
the interface.

Each snapshot contains these tables:

- `snapshot_meta`
- `tables`
- `records`
- `activity_events`

Snapshots exclude `users`, `password_hash`, and other users' data.

## Backup and restore

Use the `Backups` section to select a database, create a backup, download it as a
`.sqlite` file, or restore it into a new CloudDB database with a `Restored` suffix.
Restoring a backup preserves existing databases and records.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` in your browser.

If port `5000` is occupied, choose another port:

```powershell
python -m flask --app app run --host 127.0.0.1 --port 5001
```

The application creates its SQLite database as `database.db` automatically.

## Configuration

Set `SECRET_KEY` through an environment variable for a production-like deployment.
See `.env.example` for the available configuration. Local databases, logs, and
runtime files are excluded from Git.

For an HTTPS deployment, also set:

```text
SESSION_COOKIE_SECURE=True
```
