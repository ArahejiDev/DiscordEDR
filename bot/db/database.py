"""
Data access layer. Uses embedded SQLite (no external server required),
a perfect fit for a fully local app.
"""
import sqlite3
import os
from datetime import datetime, timezone
from contextlib import contextmanager

from bot.config import DB_PATH


def _ensure_dir():
    directory = os.path.dirname(DB_PATH)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


@contextmanager
def get_conn():
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _add_column_if_missing(conn, table, column, coltype):
    """Lightweight migration: adds a column to an existing table if it's
    not already there. Needed because pending_actions may come from an
    earlier version of the database that didn't have 'username' or
    'duration_seconds'."""
    cols = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db():
    """Creates the tables if they don't exist yet. Call this on bot startup."""
    with get_conn() as conn:
        c = conn.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            guild_id TEXT,
            channel_id TEXT,
            user_id TEXT,
            username TEXT,
            content TEXT,
            extra TEXT,
            timestamp TEXT NOT NULL
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_name TEXT NOT NULL,
            guild_id TEXT,
            user_id TEXT,
            username TEXT,
            description TEXT,
            severity TEXT,
            timestamp TEXT NOT NULL
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS members (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            guild_id TEXT,
            joined_at TEXT,
            account_created_at TEXT,
            left_at TEXT
        )
        """)

        c.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id)")

        c.execute("""
        CREATE TABLE IF NOT EXISTS pending_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            guild_id TEXT,
            user_id TEXT,
            username TEXT,
            reason TEXT,
            duration_seconds INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            requested_at TEXT NOT NULL,
            resolved_at TEXT,
            error TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at TEXT
        )
        """)
        # Migration: if pending_actions already existed from an earlier
        # version, it will be missing these columns. They're added without
        # touching existing data.
        _add_column_if_missing(conn, "pending_actions", "username", "TEXT")
        _add_column_if_missing(conn, "pending_actions", "duration_seconds", "INTEGER")
        _add_column_if_missing(conn, "pending_actions", "retry_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "pending_actions", "next_retry_at", "TEXT")

        c.execute("CREATE INDEX IF NOT EXISTS idx_pending_user ON pending_actions(user_id)")


def log_event(event_type, guild_id=None, channel_id=None, user_id=None,
              username=None, content=None, extra=None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO events
               (event_type, guild_id, channel_id, user_id, username, content, extra, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_type, str(guild_id) if guild_id else None,
             str(channel_id) if channel_id else None,
             str(user_id) if user_id else None,
             username, content, extra,
             datetime.now(timezone.utc).isoformat())
        )


def log_alert(rule_name, guild_id=None, user_id=None, username=None,
              description="", severity="medium"):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO alerts
               (rule_name, guild_id, user_id, username, description, severity, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rule_name, str(guild_id) if guild_id else None,
             str(user_id) if user_id else None,
             username, description, severity,
             datetime.now(timezone.utc).isoformat())
        )


def upsert_member(user_id, username, guild_id, joined_at, account_created_at):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO members (user_id, username, guild_id, joined_at, account_created_at, left_at)
               VALUES (?, ?, ?, ?, ?, NULL)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username,
                 guild_id=excluded.guild_id,
                 joined_at=excluded.joined_at,
                 left_at=NULL
            """,
            (str(user_id), username, str(guild_id), joined_at, account_created_at)
        )


def mark_member_left(user_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE members SET left_at = ? WHERE user_id = ?",
            (datetime.now(timezone.utc).isoformat(), str(user_id))
        )


# =====================================================================
# Read/query functions used by the desktop panel
# =====================================================================

def fetch_alerts(limit=200, severity=None):
    query = "SELECT * FROM alerts"
    params = []
    if severity:
        query += " WHERE severity = ?"
        params.append(severity)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def fetch_events(limit=300, event_type=None, search=None):
    query = "SELECT * FROM events WHERE 1=1"
    params = []
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    if search:
        query += " AND (username LIKE ? OR content LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def fetch_members(active_only=False):
    query = "SELECT * FROM members"
    if active_only:
        query += " WHERE left_at IS NULL"
    query += " ORDER BY joined_at DESC"
    with get_conn() as conn:
        rows = conn.execute(query).fetchall()
    return [dict(r) for r in rows]


def count_alerts_by_severity():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT severity, COUNT(*) as n FROM alerts GROUP BY severity"
        ).fetchall()
    return {r["severity"]: r["n"] for r in rows}


def top_active_users(limit=5):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT username, COUNT(*) as n FROM events
               WHERE event_type = 'message_create' AND username IS NOT NULL
               GROUP BY user_id ORDER BY n DESC LIMIT ?""",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def queue_action(action_type, guild_id, user_id, reason=None, username=None, duration_seconds=None):
    """Queues an action (kick, ban, warn, timeout...) for the bot to
    execute on its next cycle. 'username' is stored denormalized so the
    history can still be displayed even if the member has already left
    the server. 'duration_seconds' is only used for 'timeout'."""
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO pending_actions
               (action_type, guild_id, user_id, username, reason, duration_seconds, status, requested_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (action_type, str(guild_id) if guild_id else None, str(user_id), username, reason,
             duration_seconds, datetime.now(timezone.utc).isoformat())
        )
        return cur.lastrowid


def fetch_pending_actions(action_type=None):
    """Returns the 'pending' actions that are ready to be processed:
    either they never failed (next_retry_at is NULL) or their backoff
    has already expired (next_retry_at <= now)."""
    now = datetime.now(timezone.utc).isoformat()
    query = ("SELECT * FROM pending_actions WHERE status = 'pending' "
             "AND (next_retry_at IS NULL OR next_retry_at <= ?)")
    params = [now]
    if action_type:
        query += " AND action_type = ?"
        params.append(action_type)
    query += " ORDER BY id ASC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def schedule_retry(action_id, retry_count, delay_seconds, error=None):
    """Marks an action to be retried later instead of resolving it as a
    final error. Increments retry_count and computes when it can be
    attempted again (next_retry_at); status stays 'pending'."""
    next_retry = datetime.now(timezone.utc).timestamp() + delay_seconds
    next_retry_iso = datetime.fromtimestamp(next_retry, tz=timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """UPDATE pending_actions
               SET retry_count = ?, next_retry_at = ?, error = ?
               WHERE id = ?""",
            (retry_count, next_retry_iso, error, action_id)
        )


def resolve_action(action_id, status, error=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = ?, error = ?, resolved_at = ? WHERE id = ?",
            (status, error, datetime.now(timezone.utc).isoformat(), action_id)
        )


def fetch_recent_actions(limit=50):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_actions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_actions_for_user(user_id, limit=50):
    """Full history (any status: pending/done/error) of moderation actions
    taken against a specific user, most recent first. Used by the panel to
    check whether a member is a repeat offender."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_actions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (str(user_id), limit)
        ).fetchall()
    return [dict(r) for r in rows]


def count_actions_by_type_for_user(user_id):
    """Returns something like {'warn': 3, 'kick': 1, 'timeout': 2} for a
    user, counting only actions that actually got executed (status='done')."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT action_type, COUNT(*) as n FROM pending_actions
               WHERE user_id = ? AND status = 'done'
               GROUP BY action_type""",
            (str(user_id),)
        ).fetchall()
    return {r["action_type"]: r["n"] for r in rows}


# =====================================================================
# Analytics (the "Analítica" tab in the desktop panel)
# =====================================================================

def fetch_alerts_by_day(days=14):
    """Number of alerts per day and severity over the last N days, for the
    chart in the Analytics tab. Grouped by the first 10 characters of the
    ISO timestamp (YYYY-MM-DD) instead of using SQLite's own date functions,
    which don't always handle the timezone suffix ('+00:00') added by
    datetime.isoformat() well."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT SUBSTR(timestamp, 1, 10) AS day, severity, COUNT(*) as n
               FROM alerts
               WHERE SUBSTR(timestamp, 1, 10) >= DATE('now', ?)
               GROUP BY day, severity
               ORDER BY day ASC""",
            (f"-{days} days",)
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_rule_ranking(limit=15, days=None):
    """Rules that have generated the most alerts overall, highest first —
    useful for spotting which rule is producing the most noise/false
    positives. If days is given, limits to the same range as the rest of
    the tab."""
    query = "SELECT rule_name, COUNT(*) as n FROM alerts"
    params = []
    if days:
        query += " WHERE SUBSTR(timestamp, 1, 10) >= DATE('now', ?)"
        params.append(f"-{days} days")
    query += " GROUP BY rule_name ORDER BY n DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

def fetch_top_alerting_users(limit=15, days=None):
    """Users with the most alerts generated, highest first — for quickly
    spotting who's causing the most trouble. If days is given, limits to
    the same range as the rest of the Analytics tab."""
    query = "SELECT username, COUNT(*) as n FROM alerts WHERE username IS NOT NULL"
    params = []
    if days:
        query += " AND SUBSTR(timestamp, 1, 10) >= DATE('now', ?)"
        params.append(f"-{days} days")
    query += " GROUP BY user_id ORDER BY n DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]