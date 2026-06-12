"""
SQLite store for all scraped + AI-analysed opportunities.
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "opportunities.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS opportunities (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            uid         TEXT UNIQUE,          -- hash of url+title
            title       TEXT NOT NULL,
            url         TEXT,
            source      TEXT,                 -- GeM, CPPP, Mahatenders, etc.
            category    TEXT,                 -- gov | corp | export
            snippet     TEXT,
            -- AI-extracted fields
            value_inr   INTEGER,              -- estimated value in INR (0 if unknown)
            deadline    TEXT,                 -- ISO date string or empty
            location    TEXT,
            quantity    TEXT,
            relevance   INTEGER DEFAULT 0,    -- 1-10 score from AI
            summary     TEXT,                 -- AI one-line summary
            action      TEXT,                 -- AI recommended next step
            tags        TEXT,                 -- JSON list
            -- meta
            scraped_at  TEXT,
            ai_done     INTEGER DEFAULT 0     -- 0=pending, 1=done
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            uid         TEXT UNIQUE,          -- hash of company+email/phone
            company     TEXT,
            person      TEXT,                 -- name if found
            role        TEXT,                 -- e.g. Procurement Manager
            email       TEXT,
            phone       TEXT,
            source_url  TEXT,                 -- page where found
            notes       TEXT,
            scraped_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS runs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            finished_at TEXT,
            total_found INTEGER DEFAULT 0,
            new_added   INTEGER DEFAULT 0,
            notes       TEXT
        );
    """)
    conn.commit()
    conn.close()


def upsert_opportunity(row: dict) -> bool:
    """Insert if uid not seen before. Returns True if new."""
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM opportunities WHERE uid=?", (row["uid"],)
    ).fetchone()
    if existing:
        conn.close()
        return False
    conn.execute("""
        INSERT INTO opportunities
          (uid, title, url, source, category, snippet, scraped_at)
        VALUES (:uid, :title, :url, :source, :category, :snippet, :scraped_at)
    """, row)
    conn.commit()
    conn.close()
    return True


def save_ai_analysis(uid: str, analysis: dict):
    conn = get_conn()
    conn.execute("""
        UPDATE opportunities SET
            value_inr = :value_inr,
            deadline  = :deadline,
            location  = :location,
            quantity  = :quantity,
            relevance = :relevance,
            summary   = :summary,
            action    = :action,
            tags      = :tags,
            ai_done   = 1
        WHERE uid = :uid
    """, {**analysis, "uid": uid})
    conn.commit()
    conn.close()


def get_pending_ai():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE ai_done=0 ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all(category=None, min_relevance=0, limit=200):
    conn = get_conn()
    query = "SELECT * FROM opportunities WHERE relevance >= ?"
    params = [min_relevance]
    if category:
        query += " AND category=?"
        params.append(category)
    query += " ORDER BY relevance DESC, scraped_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def ensure_outreach_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS outreach (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company     TEXT,
            role        TEXT,
            email       TEXT,
            subject     TEXT,
            body        TEXT,
            status      TEXT DEFAULT 'draft',   -- draft|sent|replied|meeting|won|no
            ref_type    TEXT,                    -- contact|opportunity
            ref_id      INTEGER,
            updated_at  TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_outreach(row: dict) -> int:
    ensure_outreach_table()
    conn = get_conn()
    if row.get("id"):
        conn.execute("""UPDATE outreach SET company=:company, role=:role, email=:email,
            subject=:subject, body=:body, status=:status, updated_at=:updated_at WHERE id=:id""", row)
        rid = row["id"]
    else:
        cur = conn.execute("""INSERT INTO outreach
            (company,role,email,subject,body,status,ref_type,ref_id,updated_at)
            VALUES (:company,:role,:email,:subject,:body,:status,:ref_type,:ref_id,:updated_at)""", row)
        rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def get_outreach():
    ensure_outreach_table()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM outreach ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_outreach_status(oid: int, status: str):
    conn = get_conn()
    conn.execute("UPDATE outreach SET status=? WHERE id=?", (status, oid))
    conn.commit()
    conn.close()


def ensure_settings_table():
    conn = get_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()


def get_settings() -> dict:
    ensure_settings_table()
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def save_settings(d: dict):
    ensure_settings_table()
    conn = get_conn()
    for k, v in d.items():
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
    conn.commit()
    conn.close()


def purge_expired_tenders(today_iso=None):
    """Delete tenders whose bid_end_date / deadline is in the past."""
    import json, datetime
    today = datetime.date.fromisoformat(today_iso) if today_iso else datetime.date.today()

    def pdl(s):
        if not s:
            return None
        for f in ("%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(str(s).split()[0], f).date()
            except Exception:
                pass
        return None

    conn = get_conn()
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(opportunities)").fetchall()]
    has_pdf = "pdf_detail" in cols
    rows = conn.execute("SELECT id, deadline" + (", pdf_detail" if has_pdf else "") +
                        " FROM opportunities").fetchall()
    removed = 0
    for r in rows:
        d = {}
        if has_pdf and r["pdf_detail"]:
            try:
                d = json.loads(r["pdf_detail"])
            except Exception:
                pass
        dl = pdl(d.get("bid_end_date") or r["deadline"])
        if dl and dl < today:
            conn.execute("DELETE FROM opportunities WHERE id=?", (r["id"],))
            removed += 1
    conn.commit()
    conn.close()
    return removed


def ensure_status_column():
    conn = get_conn()
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(opportunities)").fetchall()]
    if "status" not in cols:
        conn.execute("ALTER TABLE opportunities ADD COLUMN status TEXT DEFAULT 'new'")
        conn.commit()
    conn.close()


def set_status(opp_id: int, status: str):
    conn = get_conn()
    conn.execute("UPDATE opportunities SET status=? WHERE id=?", (status, opp_id))
    conn.commit()
    conn.close()


def get_opportunities_full(limit=1000):
    """Return all opportunities with status, for the UI."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM opportunities ORDER BY relevance DESC, scraped_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def ensure_contact_country_column():
    conn = get_conn()
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()]
    if "country" not in cols:
        conn.execute("ALTER TABLE contacts ADD COLUMN country TEXT DEFAULT ''")
        conn.commit()
    conn.close()


def upsert_contact(row: dict) -> bool:
    """Insert contact if not seen. Returns True if new."""
    ensure_contact_country_column()
    row.setdefault("country", "")
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM contacts WHERE uid=?", (row["uid"],)
    ).fetchone()
    if existing:
        conn.close()
        return False
    conn.execute("""
        INSERT INTO contacts (uid, company, person, role, email, phone, source_url, notes, scraped_at, country)
        VALUES (:uid, :company, :person, :role, :email, :phone, :source_url, :notes, :scraped_at, :country)
    """, row)
    conn.commit()
    conn.close()
    return True


def get_contacts(company=None):
    conn = get_conn()
    if company:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE company LIKE ? ORDER BY company", (f"%{company}%",)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM contacts ORDER BY company").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_run(started_at, finished_at, total_found, new_added, notes=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO runs (started_at,finished_at,total_found,new_added,notes) VALUES (?,?,?,?,?)",
        (started_at, finished_at, total_found, new_added, notes)
    )
    conn.commit()
    conn.close()


def stats():
    conn = get_conn()
    row = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN category='gov'    THEN 1 ELSE 0 END) AS gov,
            SUM(CASE WHEN category='corp'   THEN 1 ELSE 0 END) AS corp,
            SUM(CASE WHEN category='export' THEN 1 ELSE 0 END) AS export,
            SUM(CASE WHEN ai_done=0         THEN 1 ELSE 0 END) AS pending_ai,
            MAX(scraped_at) AS last_scraped
        FROM opportunities
    """).fetchone()
    conn.close()
    return dict(row)
