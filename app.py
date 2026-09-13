import csv
import io
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime
from functools import wraps

from flask import Flask, Response, g, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "development-only-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "False").lower() == "true"
app.config["DATABASE"] = os.path.join(app.root_path, "database.db")

ALLOWED_COLUMN_TYPES = {"text", "number", "boolean", "date", "json"}
MAX_IMPORT_RECORDS = 500

SCHEMA_TEMPLATES = [
    {
        "id": "clients",
        "name": "Клиенты",
        "description": "CRM-таблица для контактов, сегментов и статусов.",
        "columns": [
            {"name": "company", "type": "text", "required": True},
            {"name": "contact", "type": "text"},
            {"name": "email", "type": "text"},
            {"name": "segment", "type": "text", "default": "SMB"},
            {"name": "active", "type": "boolean", "default": True},
        ],
    },
    {
        "id": "incidents",
        "name": "Инциденты",
        "description": "Операционная таблица для заявок и SLA.",
        "columns": [
            {"name": "title", "type": "text", "required": True},
            {"name": "priority", "type": "text", "default": "medium"},
            {"name": "owner", "type": "text"},
            {"name": "opened_at", "type": "date"},
            {"name": "resolved", "type": "boolean", "default": False},
        ],
    },
    {
        "id": "assets",
        "name": "Активы",
        "description": "Инвентаризация сервисов, серверов и облачных ресурсов.",
        "columns": [
            {"name": "asset_id", "type": "text", "required": True},
            {"name": "region", "type": "text", "default": "eu-central-1"},
            {"name": "monthly_cost", "type": "number", "default": 0},
            {"name": "tags", "type": "json", "default": {}},
        ],
    },
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    db.execute("PRAGMA foreign_keys = ON")

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS databases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            database_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            columns_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (database_id) REFERENCES databases(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            database_id INTEGER NOT NULL,
            table_id INTEGER NOT NULL,
            data_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (database_id) REFERENCES databases(id) ON DELETE CASCADE,
            FOREIGN KEY (table_id) REFERENCES tables(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            details_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            database_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_databases_user ON databases(user_id);
        CREATE INDEX IF NOT EXISTS idx_tables_user_database ON tables(user_id, database_id);
        CREATE INDEX IF NOT EXISTS idx_records_user_table ON records(user_id, table_id);
        CREATE INDEX IF NOT EXISTS idx_activity_user_created ON activity_events(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_backups_user_database ON backups(user_id, database_id);
        """
    )
    db.commit()
    db.close()


def need_login(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Нужно войти"}), 401
        return func(*args, **kwargs)

    return wrapper


def row_to_dict(row):
    return dict(row) if row else None


def get_json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def log_activity(action, entity_type, entity_id=None, details=None):
    user_id = session.get("user_id")
    if not user_id:
        return

    db = get_db()
    db.execute(
        """
        INSERT INTO activity_events (user_id, action, entity_type, entity_id, details_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            action,
            entity_type,
            entity_id,
            json.dumps(details or {}, ensure_ascii=False),
        ),
    )


def table_belongs_to_user(table_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM tables WHERE id = ? AND user_id = ?",
        (table_id, session["user_id"]),
    ).fetchone()


def database_belongs_to_user(database_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM databases WHERE id = ? AND user_id = ?",
        (database_id, session["user_id"]),
    ).fetchone()


def parse_columns(columns):
    if isinstance(columns, str):
        columns = json.loads(columns)
    if not isinstance(columns, list) or not columns:
        raise ValueError("Добавьте хотя бы одну колонку")

    parsed = []
    names = set()
    for item in columns:
        if not isinstance(item, dict):
            raise ValueError("Колонка должна быть объектом JSON")

        name = str(item.get("name") or "").strip()
        column_type = str(item.get("type") or "text").strip().lower()
        if not name:
            raise ValueError("У каждой колонки должно быть имя")
        if name in names:
            raise ValueError(f"Колонка '{name}' уже существует")
        if column_type not in ALLOWED_COLUMN_TYPES:
            allowed = ", ".join(sorted(ALLOWED_COLUMN_TYPES))
            raise ValueError(f"Тип '{column_type}' не поддерживается. Доступно: {allowed}")

        column = {
            "name": name,
            "type": column_type,
            "required": bool(item.get("required", False)),
        }
        if "default" in item:
            column["default"] = item.get("default")
        parsed.append(column)
        names.add(name)

    return parsed


def coerce_boolean(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "да"}:
            return True
        if normalized in {"false", "0", "no", "нет"}:
            return False
    raise ValueError("ожидается boolean")


def coerce_number(value):
    if isinstance(value, bool):
        raise ValueError("ожидается число")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        normalized = value.strip().replace(",", ".")
        if not normalized:
            return ""
        number = float(normalized)
        return int(number) if number.is_integer() else number
    raise ValueError("ожидается число")


def coerce_date(value):
    if not isinstance(value, str):
        raise ValueError("ожидается дата в формате YYYY-MM-DD")
    normalized = value.strip()
    datetime.strptime(normalized, "%Y-%m-%d")
    return normalized


def coerce_json(value):
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return ""
        return json.loads(normalized)
    raise ValueError("ожидается JSON-объект, массив или строка JSON")


def coerce_value(column, value):
    if value in (None, ""):
        if column.get("required"):
            raise ValueError("обязательное поле")
        return value

    column_type = column.get("type", "text")
    try:
        if column_type == "number":
            return coerce_number(value)
        if column_type == "boolean":
            return coerce_boolean(value)
        if column_type == "date":
            return coerce_date(value)
        if column_type == "json":
            return coerce_json(value)
        return str(value)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"Поле '{column['name']}': {error}") from error


def check_record_data(table_row, data):
    if not isinstance(data, dict):
        raise ValueError("Запись должна быть JSON-объектом")

    columns = json.loads(table_row["columns_json"])
    result = {}
    column_names = []

    for column in columns:
        name = column["name"]
        column_names.append(name)

        if name in data:
            value = data[name]
        elif column.get("default") not in (None, ""):
            value = column.get("default")
        elif column.get("required"):
            raise ValueError(f"Поле '{name}' обязательно")
        else:
            continue

        result[name] = coerce_value(column, value)

    for key in data:
        if key not in column_names:
            raise ValueError(f"Лишнее поле: {key}")

    return result


def record_to_dict(row):
    item = row_to_dict(row)
    item["data"] = json.loads(row["data_json"])
    del item["data_json"]
    return item


def calculate_storage_bytes(db):
    values = [
        db.execute(
            "SELECT COALESCE(SUM(LENGTH(name) + LENGTH(description)), 0) FROM databases WHERE user_id = ?",
            (session["user_id"],),
        ).fetchone()[0],
        db.execute(
            "SELECT COALESCE(SUM(LENGTH(name) + LENGTH(columns_json)), 0) FROM tables WHERE user_id = ?",
            (session["user_id"],),
        ).fetchone()[0],
        db.execute(
            "SELECT COALESCE(SUM(LENGTH(data_json)), 0) FROM records WHERE user_id = ?",
            (session["user_id"],),
        ).fetchone()[0],
        db.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM backups WHERE user_id = ?",
            (session["user_id"],),
        ).fetchone()[0],
    ]
    return sum(values)


def get_stats_payload(db):
    databases_count = db.execute(
        "SELECT COUNT(*) FROM databases WHERE user_id = ?",
        (session["user_id"],),
    ).fetchone()[0]
    tables_count = db.execute(
        "SELECT COUNT(*) FROM tables WHERE user_id = ?",
        (session["user_id"],),
    ).fetchone()[0]
    records_count = db.execute(
        "SELECT COUNT(*) FROM records WHERE user_id = ?",
        (session["user_id"],),
    ).fetchone()[0]
    events_count = db.execute(
        "SELECT COUNT(*) FROM activity_events WHERE user_id = ?",
        (session["user_id"],),
    ).fetchone()[0]
    backups_count = db.execute(
        "SELECT COUNT(*) FROM backups WHERE user_id = ?",
        (session["user_id"],),
    ).fetchone()[0]

    return {
        "databases": databases_count,
        "tables": tables_count,
        "records": records_count,
        "events": events_count,
        "backups": backups_count,
        "storage_bytes": calculate_storage_bytes(db),
    }


def get_activity(limit=8):
    db = get_db()
    rows = db.execute(
        """
        SELECT * FROM activity_events
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (session["user_id"], limit),
    ).fetchall()

    items = []
    for row in rows:
        item = row_to_dict(row)
        item["details"] = json.loads(item.pop("details_json") or "{}")
        items.append(item)
    return items


def utc_stamp():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def safe_filename(value, fallback="database"):
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return name.lower() or fallback


def parse_json_field(value, fallback):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def collect_database_snapshot(database_id):
    db = get_db()
    database = database_belongs_to_user(database_id)
    if database is None:
        return None

    table_rows = db.execute(
        """
        SELECT id, name, columns_json, created_at
        FROM tables
        WHERE user_id = ? AND database_id = ?
        ORDER BY id
        """,
        (session["user_id"], database_id),
    ).fetchall()
    record_rows = db.execute(
        """
        SELECT id, table_id, data_json, created_at, updated_at
        FROM records
        WHERE user_id = ? AND database_id = ?
        ORDER BY id
        """,
        (session["user_id"], database_id),
    ).fetchall()

    tables_payload = []
    for row in table_rows:
        item = row_to_dict(row)
        item["columns"] = parse_json_field(item.pop("columns_json"), [])
        tables_payload.append(item)

    records_payload = []
    for row in record_rows:
        item = row_to_dict(row)
        item["data"] = parse_json_field(item.pop("data_json"), {})
        records_payload.append(item)

    table_ids = [row["id"] for row in table_rows]
    record_ids = [row["id"] for row in record_rows]
    activity_clauses = ["(entity_type = ? AND entity_id = ?)"]
    activity_params = [session["user_id"], "database", database_id]

    if table_ids:
        activity_clauses.append(f"(entity_type = 'table' AND entity_id IN ({','.join('?' for _ in table_ids)}))")
        activity_params.extend(table_ids)
    if record_ids:
        activity_clauses.append(f"(entity_type = 'record' AND entity_id IN ({','.join('?' for _ in record_ids)}))")
        activity_params.extend(record_ids)

    activity_rows = db.execute(
        f"""
        SELECT id, action, entity_type, entity_id, details_json, created_at
        FROM activity_events
        WHERE user_id = ? AND ({' OR '.join(activity_clauses)})
        ORDER BY id
        """,
        activity_params,
    ).fetchall()

    activity_payload = []
    for row in activity_rows:
        item = row_to_dict(row)
        item["details"] = parse_json_field(item.pop("details_json"), {})
        activity_payload.append(item)

    return {
        "version": 1,
        "source": "CloudDB",
        "exported_at": utc_stamp(),
        "database": {
            "id": database["id"],
            "name": database["name"],
            "description": database["description"],
            "created_at": database["created_at"],
        },
        "tables": tables_payload,
        "records": records_payload,
        "activity_events": activity_payload,
    }


def snapshot_payload_size(payload):
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def create_sqlite_snapshot(payload):
    fd, path = tempfile.mkstemp(prefix="clouddb_snapshot_", suffix=".sqlite")
    os.close(fd)
    connection = None
    try:
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE snapshot_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE tables (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                columns_json TEXT NOT NULL,
                created_at TEXT
            );

            CREATE TABLE records (
                id INTEGER PRIMARY KEY,
                table_id INTEGER NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE activity_events (
                id INTEGER PRIMARY KEY,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id INTEGER,
                details_json TEXT NOT NULL,
                created_at TEXT
            );
            """
        )

        database = payload.get("database", {})
        meta = {
            "version": str(payload.get("version", 1)),
            "source": payload.get("source", "CloudDB"),
            "exported_at": payload.get("exported_at", ""),
            "database_id": str(database.get("id", "")),
            "database_name": database.get("name", ""),
            "database_description": database.get("description", ""),
            "table_count": str(len(payload.get("tables", []))),
            "record_count": str(len(payload.get("records", []))),
        }
        connection.executemany(
            "INSERT INTO snapshot_meta (key, value) VALUES (?, ?)",
            [(key, str(value or "")) for key, value in meta.items()],
        )
        connection.executemany(
            "INSERT INTO tables (id, name, columns_json, created_at) VALUES (?, ?, ?, ?)",
            [
                (
                    table.get("id"),
                    table.get("name", ""),
                    json.dumps(table.get("columns", []), ensure_ascii=False),
                    table.get("created_at"),
                )
                for table in payload.get("tables", [])
            ],
        )
        connection.executemany(
            "INSERT INTO records (id, table_id, data_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    record.get("id"),
                    record.get("table_id"),
                    json.dumps(record.get("data", {}), ensure_ascii=False),
                    record.get("created_at"),
                    record.get("updated_at"),
                )
                for record in payload.get("records", [])
            ],
        )
        connection.executemany(
            """
            INSERT INTO activity_events (id, action, entity_type, entity_id, details_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    event.get("id"),
                    event.get("action", ""),
                    event.get("entity_type", ""),
                    event.get("entity_id"),
                    json.dumps(event.get("details", {}), ensure_ascii=False),
                    event.get("created_at"),
                )
                for event in payload.get("activity_events", [])
            ],
        )
        connection.commit()
        connection.close()
        connection = None
        with open(path, "rb") as snapshot_file:
            return snapshot_file.read()
    finally:
        if connection is not None:
            connection.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def sqlite_snapshot_response(payload, filename):
    content = create_sqlite_snapshot(payload)
    return Response(
        content,
        mimetype="application/vnd.sqlite3",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Length": str(len(content)),
        },
    )


def backup_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "database_id": row["database_id"],
        "size_bytes": row["size_bytes"],
        "created_at": row["created_at"],
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "runtime": "clouddb-console"})


@app.route("/api/me")
def me():
    if "user_id" not in session:
        return jsonify({"logged_in": False})
    return jsonify(
        {
            "logged_in": True,
            "user_id": session["user_id"],
            "email": session.get("email"),
        }
    )


@app.route("/api/register", methods=["POST"])
def register():
    data = get_json_body()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or "@" not in email:
        return jsonify({"error": "Введите корректный email"}), 400
    if len(password) < 8:
        return jsonify({"error": "Пароль должен быть не короче 4 символов"}), 400

    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email, generate_password_hash(password)),
        )
        session["user_id"] = cursor.lastrowid
        session["email"] = email
        log_activity("register", "user", cursor.lastrowid, {"email": email})
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Такой пользователь уже существует"}), 400

    return jsonify({"message": "Аккаунт создан", "email": email})


@app.route("/api/login", methods=["POST"])
def login():
    data = get_json_body()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Неверный email или пароль"}), 400

    session["user_id"] = user["id"]
    session["email"] = user["email"]
    log_activity("login", "user", user["id"], {"email": user["email"]})
    db.commit()
    return jsonify({"message": "Вход выполнен", "email": user["email"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Вы вышли"})


@app.route("/api/schema/templates")
@need_login
def schema_templates():
    return jsonify(SCHEMA_TEMPLATES)


@app.route("/api/databases", methods=["GET", "POST"])
@need_login
def databases():
    db = get_db()

    if request.method == "GET":
        rows = db.execute(
            """
            SELECT
                d.*,
                COUNT(DISTINCT t.id) AS table_count,
                COUNT(r.id) AS record_count
            FROM databases d
            LEFT JOIN tables t ON t.database_id = d.id AND t.user_id = d.user_id
            LEFT JOIN records r ON r.database_id = d.id AND r.user_id = d.user_id
            WHERE d.user_id = ?
            GROUP BY d.id
            ORDER BY d.id DESC
            """,
            (session["user_id"],),
        ).fetchall()
        return jsonify([row_to_dict(row) for row in rows])

    data = get_json_body()
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()

    if not name:
        return jsonify({"error": "Название базы обязательно"}), 400

    cursor = db.execute(
        "INSERT INTO databases (user_id, name, description) VALUES (?, ?, ?)",
        (session["user_id"], name, description),
    )
    log_activity("create_database", "database", cursor.lastrowid, {"name": name})
    db.commit()
    return jsonify({"id": cursor.lastrowid, "name": name, "description": description})


@app.route("/api/stats")
@need_login
def stats():
    return jsonify(get_stats_payload(get_db()))


@app.route("/api/overview")
@need_login
def overview():
    db = get_db()
    stats_payload = get_stats_payload(db)
    records_count = stats_payload["records"]
    estimated_invocations = stats_payload["events"] + records_count * 2 + stats_payload["tables"]
    latest_backup = db.execute(
        """
        SELECT name, created_at, size_bytes
        FROM backups
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session["user_id"],),
    ).fetchone()

    return jsonify(
        {
            "stats": stats_payload,
            "autoscaling": {
                "mode": "scale-to-zero",
                "min_instances": 0,
                "max_concurrency": 1000,
                "estimated_invocations": estimated_invocations,
                "cold_start_ms": 142,
                "p95_latency_ms": 38,
            },
            "backup_status": {
                "policy": "manual SQLite snapshots",
                "count": stats_payload["backups"],
                "latest_name": latest_backup["name"] if latest_backup else None,
                "latest_at": latest_backup["created_at"] if latest_backup else None,
                "latest_size_bytes": latest_backup["size_bytes"] if latest_backup else 0,
                "status": "ready" if stats_payload["databases"] else "waiting-for-database",
            },
            "regions": [
                {"code": "eu-central-1", "status": "active", "latency_ms": 31},
                {"code": "us-east-1", "status": "standby", "latency_ms": 84},
                {"code": "ap-south-1", "status": "standby", "latency_ms": 112},
            ],
            "functions": [
                {"name": "AuthFunction", "trigger": "HTTPS", "status": "healthy"},
                {"name": "SchemaFunction", "trigger": "HTTPS", "status": "healthy"},
                {"name": "RecordFunction", "trigger": "HTTPS", "status": "healthy"},
                {"name": "ExportFunction", "trigger": "on-demand", "status": "healthy"},
                {"name": "BackupFunction", "trigger": "snapshot", "status": "healthy"},
            ],
            "activity": get_activity(8),
        }
    )


@app.route("/api/activity")
@need_login
def activity():
    return jsonify(get_activity(20))


@app.route("/api/search")
@need_login
def global_search():
    db = get_db()
    query = (request.args.get("q") or "").strip().lower()
    if not query:
        return jsonify([])

    results = []
    database_rows = db.execute(
        "SELECT * FROM databases WHERE user_id = ? ORDER BY id DESC",
        (session["user_id"],),
    ).fetchall()
    for row in database_rows:
        text = f"{row['name']} {row['description']}".lower()
        if query in text:
            results.append(
                {
                    "type": "database",
                    "title": row["name"],
                    "subtitle": row["description"] or "База данных",
                    "database_id": row["id"],
                }
            )

    table_rows = db.execute(
        "SELECT * FROM tables WHERE user_id = ? ORDER BY id DESC",
        (session["user_id"],),
    ).fetchall()
    for row in table_rows:
        columns = json.loads(row["columns_json"])
        text = f"{row['name']} {json.dumps(columns, ensure_ascii=False)}".lower()
        if query in text:
            results.append(
                {
                    "type": "table",
                    "title": row["name"],
                    "subtitle": ", ".join(column["name"] for column in columns),
                    "database_id": row["database_id"],
                    "table_id": row["id"],
                }
            )

    record_rows = db.execute(
        "SELECT * FROM records WHERE user_id = ? ORDER BY id DESC LIMIT 200",
        (session["user_id"],),
    ).fetchall()
    for row in record_rows:
        data = json.loads(row["data_json"])
        text = json.dumps(data, ensure_ascii=False).lower()
        if query in text:
            results.append(
                {
                    "type": "record",
                    "title": f"Запись #{row['id']}",
                    "subtitle": text[:140],
                    "database_id": row["database_id"],
                    "table_id": row["table_id"],
                    "record_id": row["id"],
                }
            )

    return jsonify(results[:20])


@app.route("/api/databases/<int:database_id>", methods=["PUT"])
@need_login
def edit_database(database_id):
    db = get_db()
    data = get_json_body()
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()

    if database_belongs_to_user(database_id) is None:
        return jsonify({"error": "База не найдена"}), 404
    if not name:
        return jsonify({"error": "Название базы обязательно"}), 400

    db.execute(
        "UPDATE databases SET name = ?, description = ? WHERE id = ? AND user_id = ?",
        (name, description, database_id, session["user_id"]),
    )
    log_activity("update_database", "database", database_id, {"name": name})
    db.commit()
    return jsonify({"id": database_id, "name": name, "description": description})


@app.route("/api/databases/<int:database_id>", methods=["DELETE"])
@need_login
def delete_database(database_id):
    db = get_db()
    database = database_belongs_to_user(database_id)
    if database is None:
        return jsonify({"error": "База не найдена"}), 404

    db.execute(
        "DELETE FROM databases WHERE id = ? AND user_id = ?",
        (database_id, session["user_id"]),
    )
    log_activity("delete_database", "database", database_id, {"name": database["name"]})
    db.commit()
    return jsonify({"message": "База удалена"})


@app.route("/api/databases/<int:database_id>/snapshot.sqlite")
@need_login
def download_database_snapshot(database_id):
    payload = collect_database_snapshot(database_id)
    if payload is None:
        return jsonify({"error": "База не найдена"}), 404

    database_name = safe_filename(payload["database"]["name"])
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
    return sqlite_snapshot_response(payload, f"clouddb_{database_name}_{timestamp}.sqlite")


@app.route("/api/databases/<int:database_id>/backups", methods=["GET", "POST"])
@need_login
def database_backups(database_id):
    db = get_db()
    database = database_belongs_to_user(database_id)
    if database is None:
        return jsonify({"error": "База не найдена"}), 404

    if request.method == "GET":
        rows = db.execute(
            """
            SELECT id, name, database_id, size_bytes, created_at
            FROM backups
            WHERE user_id = ? AND database_id = ?
            ORDER BY id DESC
            """,
            (session["user_id"], database_id),
        ).fetchall()
        return jsonify([backup_to_dict(row) for row in rows])

    data = get_json_body()
    requested_name = (data.get("name") or "").strip()
    backup_name = requested_name or f"{database['name']} snapshot {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    payload = collect_database_snapshot(database_id)
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    size_bytes = len(payload_json.encode("utf-8"))
    cursor = db.execute(
        """
        INSERT INTO backups (user_id, database_id, name, payload_json, size_bytes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session["user_id"], database_id, backup_name, payload_json, size_bytes),
    )
    log_activity(
        "create_backup",
        "backup",
        cursor.lastrowid,
        {"name": backup_name, "database": database["name"], "size_bytes": size_bytes},
    )
    db.commit()
    row = db.execute(
        "SELECT id, name, database_id, size_bytes, created_at FROM backups WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return jsonify(backup_to_dict(row)), 201


@app.route("/api/backups/<int:backup_id>/download.sqlite")
@need_login
def download_backup_snapshot(backup_id):
    db = get_db()
    backup = db.execute(
        "SELECT * FROM backups WHERE id = ? AND user_id = ?",
        (backup_id, session["user_id"]),
    ).fetchone()
    if backup is None:
        return jsonify({"error": "Backup не найден"}), 404

    payload = parse_json_field(backup["payload_json"], None)
    if not isinstance(payload, dict):
        return jsonify({"error": "Backup поврежден"}), 400

    database_name = safe_filename((payload.get("database") or {}).get("name"), "backup")
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
    return sqlite_snapshot_response(payload, f"clouddb_backup_{database_name}_{timestamp}.sqlite")


@app.route("/api/backups/<int:backup_id>/restore", methods=["POST"])
@need_login
def restore_backup(backup_id):
    db = get_db()
    backup = db.execute(
        "SELECT * FROM backups WHERE id = ? AND user_id = ?",
        (backup_id, session["user_id"]),
    ).fetchone()
    if backup is None:
        return jsonify({"error": "Backup не найден"}), 404

    payload = parse_json_field(backup["payload_json"], None)
    if not isinstance(payload, dict):
        return jsonify({"error": "Backup поврежден"}), 400

    source_database = payload.get("database") or {}
    source_name = (source_database.get("name") or backup["name"] or "Database").strip()
    restored_name = f"{source_name} Restored"
    description = source_database.get("description") or ""
    cursor = db.execute(
        "INSERT INTO databases (user_id, name, description) VALUES (?, ?, ?)",
        (session["user_id"], restored_name, description),
    )
    restored_database_id = cursor.lastrowid

    table_id_map = {}
    for table in payload.get("tables", []):
        try:
            columns = parse_columns(table.get("columns", []))
        except Exception:
            columns = []
        if not columns:
            continue
        table_cursor = db.execute(
            "INSERT INTO tables (user_id, database_id, name, columns_json) VALUES (?, ?, ?, ?)",
            (
                session["user_id"],
                restored_database_id,
                table.get("name") or "restored_table",
                json.dumps(columns, ensure_ascii=False),
            ),
        )
        table_id_map[table.get("id")] = table_cursor.lastrowid

    restored_records = 0
    for record in payload.get("records", []):
        new_table_id = table_id_map.get(record.get("table_id"))
        if not new_table_id:
            continue
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        db.execute(
            "INSERT INTO records (user_id, database_id, table_id, data_json) VALUES (?, ?, ?, ?)",
            (
                session["user_id"],
                restored_database_id,
                new_table_id,
                json.dumps(data, ensure_ascii=False),
            ),
        )
        restored_records += 1

    log_activity(
        "restore_backup",
        "database",
        restored_database_id,
        {
            "name": restored_name,
            "backup": backup["name"],
            "tables": len(table_id_map),
            "records": restored_records,
        },
    )
    db.commit()
    return jsonify(
        {
            "id": restored_database_id,
            "name": restored_name,
            "description": description,
            "tables_restored": len(table_id_map),
            "records_restored": restored_records,
        }
    )


@app.route("/api/tables", methods=["GET", "POST"])
@need_login
def tables():
    db = get_db()

    if request.method == "GET":
        database_id = request.args.get("database_id")
        rows = db.execute(
            """
            SELECT
                t.*,
                COUNT(r.id) AS record_count,
                MAX(r.updated_at) AS last_record_at
            FROM tables t
            LEFT JOIN records r ON r.table_id = t.id AND r.user_id = t.user_id
            WHERE t.user_id = ? AND t.database_id = ?
            GROUP BY t.id
            ORDER BY t.id DESC
            """,
            (session["user_id"], database_id),
        ).fetchall()
        result = []
        for row in rows:
            item = row_to_dict(row)
            item["columns"] = json.loads(row["columns_json"])
            del item["columns_json"]
            result.append(item)
        return jsonify(result)

    data = get_json_body()
    database_id = data.get("database_id")
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "Название таблицы обязательно"}), 400
    if database_belongs_to_user(database_id) is None:
        return jsonify({"error": "База не найдена"}), 404

    try:
        columns = parse_columns(data.get("columns", []))
    except Exception as error:
        return jsonify({"error": str(error)}), 400

    cursor = db.execute(
        "INSERT INTO tables (user_id, database_id, name, columns_json) VALUES (?, ?, ?, ?)",
        (session["user_id"], database_id, name, json.dumps(columns, ensure_ascii=False)),
    )
    log_activity("create_table", "table", cursor.lastrowid, {"name": name, "columns": len(columns)})
    db.commit()
    return jsonify({"id": cursor.lastrowid, "name": name, "database_id": database_id, "columns": columns})


@app.route("/api/tables/<int:table_id>", methods=["PUT"])
@need_login
def edit_table(table_id):
    db = get_db()
    data = get_json_body()
    name = (data.get("name") or "").strip()

    table = table_belongs_to_user(table_id)
    if table is None:
        return jsonify({"error": "Таблица не найдена"}), 404
    if not name:
        return jsonify({"error": "Название таблицы обязательно"}), 400

    try:
        columns = parse_columns(data.get("columns", []))
    except Exception as error:
        return jsonify({"error": str(error)}), 400

    db.execute(
        "UPDATE tables SET name = ?, columns_json = ? WHERE id = ? AND user_id = ?",
        (name, json.dumps(columns, ensure_ascii=False), table_id, session["user_id"]),
    )
    log_activity("update_table", "table", table_id, {"name": name, "columns": len(columns)})
    db.commit()
    return jsonify({"id": table_id, "name": name, "database_id": table["database_id"], "columns": columns})


@app.route("/api/tables/<int:table_id>", methods=["DELETE"])
@need_login
def delete_table(table_id):
    db = get_db()
    table = table_belongs_to_user(table_id)
    if table is None:
        return jsonify({"error": "Таблица не найдена"}), 404

    db.execute(
        "DELETE FROM tables WHERE id = ? AND user_id = ?",
        (table_id, session["user_id"]),
    )
    log_activity("delete_table", "table", table_id, {"name": table["name"]})
    db.commit()
    return jsonify({"message": "Таблица удалена"})


@app.route("/api/records", methods=["GET", "POST"])
@need_login
def records():
    db = get_db()

    if request.method == "GET":
        table_id = request.args.get("table_id")
        filter_text = (request.args.get("filter") or "").strip()
        sort_by = (request.args.get("sort_by") or "id").strip()
        sort_order = (request.args.get("sort_order") or "desc").strip().lower()
        table = table_belongs_to_user(table_id)
        if table is None:
            return jsonify({"error": "Таблица не найдена"}), 404

        columns = json.loads(table["columns_json"])
        columns_by_name = {column["name"]: column for column in columns}
        system_sort_fields = {"id", "created_at", "updated_at"}
        if sort_by not in system_sort_fields and sort_by not in columns_by_name:
            sort_by = "id"

        rows = db.execute(
            "SELECT * FROM records WHERE table_id = ? AND user_id = ? ORDER BY id DESC",
            (table_id, session["user_id"]),
        ).fetchall()

        items = []
        for row in rows:
            item = record_to_dict(row)
            if filter_text and filter_text.lower() not in json.dumps(item["data"], ensure_ascii=False).lower():
                continue
            items.append(item)

        def sort_value(record):
            if sort_by == "id":
                return (0, int(record["id"]))
            if sort_by in {"created_at", "updated_at"}:
                return (0, record.get(sort_by) or "")

            column = columns_by_name[sort_by]
            column_type = column.get("type", "text")
            value = record["data"].get(sort_by, "")
            if value in (None, ""):
                empty_value = 0 if column_type in {"number", "boolean"} else ""
                return (1, empty_value)

            if column_type == "number":
                try:
                    return (0, float(value))
                except (TypeError, ValueError):
                    return (1, 0)
            if column_type == "boolean":
                return (0, 1 if value else 0)
            if column_type == "date":
                return (0, str(value))
            if column_type == "json":
                return (0, json.dumps(value, ensure_ascii=False, sort_keys=True))
            return (0, str(value).lower())

        items.sort(key=lambda record: sort_value(record)[1], reverse=sort_order != "asc")
        items.sort(key=lambda record: sort_value(record)[0])
        return jsonify(items)

    data = get_json_body()
    table_id = data.get("table_id")
    table = table_belongs_to_user(table_id)
    if table is None:
        return jsonify({"error": "Таблица не найдена"}), 404

    try:
        record_data = check_record_data(table, data.get("data", {}))
    except Exception as error:
        return jsonify({"error": str(error)}), 400

    cursor = db.execute(
        "INSERT INTO records (user_id, database_id, table_id, data_json) VALUES (?, ?, ?, ?)",
        (session["user_id"], table["database_id"], table_id, json.dumps(record_data, ensure_ascii=False)),
    )
    log_activity("create_record", "record", cursor.lastrowid, {"table": table["name"]})
    db.commit()
    return jsonify({"id": cursor.lastrowid, "data": record_data})


@app.route("/api/records/<int:record_id>", methods=["PUT", "DELETE"])
@need_login
def record_detail(record_id):
    db = get_db()

    row = db.execute(
        "SELECT * FROM records WHERE id = ? AND user_id = ?",
        (record_id, session["user_id"]),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Запись не найдена"}), 404

    if request.method == "DELETE":
        db.execute("DELETE FROM records WHERE id = ? AND user_id = ?", (record_id, session["user_id"]))
        log_activity("delete_record", "record", record_id, {"table_id": row["table_id"]})
        db.commit()
        return jsonify({"message": "Запись удалена"})

    table = table_belongs_to_user(row["table_id"])
    data = get_json_body()
    try:
        record_data = check_record_data(table, data.get("data", {}))
    except Exception as error:
        return jsonify({"error": str(error)}), 400

    db.execute(
        "UPDATE records SET data_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
        (json.dumps(record_data, ensure_ascii=False), record_id, session["user_id"]),
    )
    log_activity("update_record", "record", record_id, {"table_id": row["table_id"]})
    db.commit()
    return jsonify({"id": record_id, "data": record_data})


@app.route("/api/tables/<int:table_id>/import", methods=["POST"])
@need_login
def import_records(table_id):
    db = get_db()
    table = table_belongs_to_user(table_id)
    if table is None:
        return jsonify({"error": "Таблица не найдена"}), 404

    payload = get_json_body()
    records_payload = payload.get("records")
    if not isinstance(records_payload, list):
        return jsonify({"error": "Передайте массив records"}), 400
    if len(records_payload) > MAX_IMPORT_RECORDS:
        return jsonify({"error": f"За один импорт можно загрузить до {MAX_IMPORT_RECORDS} записей"}), 400

    try:
        normalized_records = [
            check_record_data(table, item.get("data", item) if isinstance(item, dict) else item)
            for item in records_payload
        ]
    except Exception as error:
        return jsonify({"error": str(error)}), 400

    for record_data in normalized_records:
        db.execute(
            "INSERT INTO records (user_id, database_id, table_id, data_json) VALUES (?, ?, ?, ?)",
            (session["user_id"], table["database_id"], table_id, json.dumps(record_data, ensure_ascii=False)),
        )

    log_activity("import_records", "table", table_id, {"count": len(normalized_records), "table": table["name"]})
    db.commit()
    return jsonify({"message": "Импорт завершен", "imported": len(normalized_records)})


@app.route("/api/tables/<int:table_id>/export")
@need_login
def export_table(table_id):
    db = get_db()
    table = table_belongs_to_user(table_id)
    if table is None:
        return jsonify({"error": "Таблица не найдена"}), 404

    rows = db.execute(
        "SELECT * FROM records WHERE table_id = ? AND user_id = ? ORDER BY id",
        (table_id, session["user_id"]),
    ).fetchall()
    columns = json.loads(table["columns_json"])
    records_payload = [
        {
            "id": row["id"],
            "data": json.loads(row["data_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]

    if request.args.get("format") == "csv":
        output = io.StringIO()
        fieldnames = ["id", "created_at", "updated_at"] + [column["name"] for column in columns]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for record in records_payload:
            row = {
                "id": record["id"],
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            }
            for column in columns:
                value = record["data"].get(column["name"], "")
                row[column["name"]] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            writer.writerow(row)
        return Response(
            output.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=table_{table_id}.csv"},
        )

    return jsonify(
        {
            "table": table["name"],
            "columns": columns,
            "records": records_payload,
        }
    )


init_db()


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
