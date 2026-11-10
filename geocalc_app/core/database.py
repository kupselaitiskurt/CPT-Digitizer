"""
GeoCalc Pro - Database Core
SQLite-backed persistent storage for projects, borings, CPT data, and layers.
"""
import sqlite3
import json
import os
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Default database path in user's home directory
DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".geocalc_pro", "geocalc.db")


def get_db_path() -> str:
    """Return the database path, creating directories if needed."""
    db_dir = os.path.dirname(DEFAULT_DB_PATH)
    os.makedirs(db_dir, exist_ok=True)
    return DEFAULT_DB_PATH


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Get a database connection with row_factory enabled."""
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialize_database(db_path: Optional[str] = None):
    """Create all tables if they don't exist."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.executescript("""
        -- Projects table
        CREATE TABLE IF NOT EXISTS projects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT,
            client      TEXT,
            location    TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            metadata    TEXT  -- JSON blob for extensible fields
        );

        -- Reports (uploaded PDF files)
        CREATE TABLE IF NOT EXISTS reports (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            filename     TEXT NOT NULL,
            file_path    TEXT,
            file_hash    TEXT,
            report_date  TEXT,
            lab_firm     TEXT,
            uploaded_at  TEXT NOT NULL,
            raw_text     TEXT  -- Extracted full text for re-processing
        );

        -- Boring locations
        CREATE TABLE IF NOT EXISTS borings (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id    INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            boring_id    TEXT NOT NULL,        -- e.g. "B-1", "BH-3"
            latitude     REAL,
            longitude    REAL,
            easting      REAL,                 -- local coordinate
            northing     REAL,
            elevation    REAL,                 -- ground surface elevation (ft or m)
            total_depth  REAL,
            water_table  REAL,                 -- depth to water table
            date_drilled TEXT,
            drill_method TEXT,
            notes        TEXT,
            metadata     TEXT                  -- JSON
        );

        -- Soil layers within a boring
        CREATE TABLE IF NOT EXISTS soil_layers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            boring_id       INTEGER NOT NULL REFERENCES borings(id) ON DELETE CASCADE,
            depth_top       REAL NOT NULL,     -- ft from surface
            depth_bottom    REAL NOT NULL,
            uscs_symbol     TEXT,              -- e.g. SP, CL, ML
            soil_description TEXT,
            color           TEXT,
            moisture        TEXT,
            consistency     TEXT,              -- loose/medium/dense for sand; soft/stiff for clay
            blow_counts     TEXT,              -- JSON: list of N values per 6" interval
            n_value         INTEGER,           -- SPT N (blows/ft)
            n60             REAL,              -- energy-corrected N
            n160            REAL,              -- overburden + energy corrected N
            liquid_limit    REAL,
            plastic_limit   REAL,
            plasticity_index REAL,
            fines_content   REAL,
            unit_weight     REAL,
            cohesion        REAL,
            friction_angle  REAL,
            compression_index REAL,
            metadata        TEXT               -- JSON for additional lab values
        );

        -- CPT (Cone Penetration Test) soundings
        CREATE TABLE IF NOT EXISTS cpt_soundings (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id    INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            cpt_id       TEXT NOT NULL,        -- e.g. "CPT-1"
            latitude     REAL,
            longitude    REAL,
            elevation    REAL,
            date_tested  TEXT,
            equipment    TEXT,
            notes        TEXT
        );

        -- CPT data points (depth vs qc, fs, u2)
        CREATE TABLE IF NOT EXISTS cpt_data (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sounding_id  INTEGER NOT NULL REFERENCES cpt_soundings(id) ON DELETE CASCADE,
            depth        REAL NOT NULL,        -- meters
            qc           REAL,                 -- cone resistance (MPa)
            fs           REAL,                 -- sleeve friction (kPa)
            u2           REAL,                 -- pore pressure (kPa)
            rf           REAL,                 -- friction ratio (%)
            qt           REAL,                 -- corrected tip resistance
            bq           REAL,                 -- pore pressure ratio
            ic           REAL,                 -- soil behavior type index
            soil_type    TEXT                  -- interpreted soil type
        );

        -- Fence diagram configurations (saved views)
        CREATE TABLE IF NOT EXISTS fence_diagrams (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name         TEXT NOT NULL,
            boring_ids   TEXT NOT NULL,        -- JSON list of boring IDs
            created_at   TEXT NOT NULL,
            config       TEXT                  -- JSON: exaggeration, colors, etc.
        );

        -- Index for fast geo-queries
        CREATE INDEX IF NOT EXISTS idx_borings_project ON borings(project_id);
        CREATE INDEX IF NOT EXISTS idx_borings_latlon  ON borings(latitude, longitude);
        CREATE INDEX IF NOT EXISTS idx_layers_boring   ON soil_layers(boring_id);
        CREATE INDEX IF NOT EXISTS idx_cpt_project     ON cpt_soundings(project_id);
    """)

    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {get_db_path()}")


# ── Project CRUD ──────────────────────────────────────────────────────────────

def create_project(name: str, description: str = "", client: str = "",
                   location: str = "") -> int:
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO projects (name, description, client, location, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, description, client, location, now, now)
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def list_projects() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT p.*, "
        "  (SELECT COUNT(*) FROM borings b WHERE b.project_id = p.id) AS boring_count, "
        "  (SELECT COUNT(*) FROM cpt_soundings c WHERE c.project_id = p.id) AS cpt_count "
        "FROM projects p ORDER BY p.updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_project(project_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_project(project_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()


# ── Boring CRUD ───────────────────────────────────────────────────────────────

def save_boring(project_id: int, report_id: int, boring_data: dict) -> int:
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO borings
            (report_id, project_id, boring_id, latitude, longitude, elevation,
             total_depth, water_table, date_drilled, drill_method, notes, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        report_id, project_id,
        boring_data.get("boring_id", ""),
        boring_data.get("latitude"),
        boring_data.get("longitude"),
        boring_data.get("elevation"),
        boring_data.get("total_depth"),
        boring_data.get("water_table"),
        boring_data.get("date_drilled", ""),
        boring_data.get("drill_method", ""),
        boring_data.get("notes", ""),
        json.dumps(boring_data.get("metadata", {}))
    ))
    boring_row_id = cur.lastrowid

    # Save layers
    for layer in boring_data.get("layers", []):
        conn.execute("""
            INSERT INTO soil_layers
                (boring_id, depth_top, depth_bottom, uscs_symbol, soil_description,
                 color, moisture, consistency, blow_counts, n_value, n60,
                 liquid_limit, plastic_limit, plasticity_index, fines_content,
                 unit_weight, cohesion, friction_angle, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            boring_row_id,
            layer.get("depth_top", 0),
            layer.get("depth_bottom", 0),
            layer.get("uscs_symbol", ""),
            layer.get("soil_description", ""),
            layer.get("color", ""),
            layer.get("moisture", ""),
            layer.get("consistency", ""),
            json.dumps(layer.get("blow_counts", [])),
            layer.get("n_value"),
            layer.get("n60"),
            layer.get("liquid_limit"),
            layer.get("plastic_limit"),
            layer.get("plasticity_index"),
            layer.get("fines_content"),
            layer.get("unit_weight"),
            layer.get("cohesion"),
            layer.get("friction_angle"),
            json.dumps(layer.get("metadata", {}))
        ))

    conn.commit()
    conn.close()
    return boring_row_id


def get_project_borings(project_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM borings WHERE project_id = ? ORDER BY boring_id", (project_id,)
    ).fetchall()
    result = []
    for r in rows:
        b = dict(r)
        layers = conn.execute(
            "SELECT * FROM soil_layers WHERE boring_id = ? ORDER BY depth_top", (b["id"],)
        ).fetchall()
        b["layers"] = [dict(l) for l in layers]
        result.append(b)
    conn.close()
    return result


def save_cpt(project_id: int, report_id: int, cpt_data: dict) -> int:
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO cpt_soundings
            (report_id, project_id, cpt_id, latitude, longitude, elevation,
             date_tested, equipment, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        report_id, project_id,
        cpt_data.get("cpt_id", ""),
        cpt_data.get("latitude"),
        cpt_data.get("longitude"),
        cpt_data.get("elevation"),
        cpt_data.get("date_tested", ""),
        cpt_data.get("equipment", ""),
        cpt_data.get("notes", ""),
    ))
    sounding_id = cur.lastrowid

    # Bulk insert CPT data points
    points = cpt_data.get("data_points", [])
    if points:
        conn.executemany("""
            INSERT INTO cpt_data (sounding_id, depth, qc, fs, u2, rf, ic, soil_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (sounding_id, p.get("depth"), p.get("qc"), p.get("fs"),
             p.get("u2"), p.get("rf"), p.get("ic"), p.get("soil_type"))
            for p in points
        ])

    conn.commit()
    conn.close()
    return sounding_id


def save_report(project_id: int, filename: str, file_path: str,
                raw_text: str = "", lab_firm: str = "") -> int:
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO reports (project_id, filename, file_path, lab_firm, uploaded_at, raw_text)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (project_id, filename, file_path, lab_firm, now, raw_text))
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid
