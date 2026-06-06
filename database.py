import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "msf_counters.db")

VALID_CATEGORIES = ["War", "Crucible", "Arena", "Raid"]

CATEGORY_EMOJI = {
    "War": "⚔️",
    "Crucible": "🏆",
    "Arena": "🛡️",
    "Raid": "👾",
}


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(cursor, conn):
    """Apply any missing schema changes to an existing database."""
    migrations = [
        "ALTER TABLE counters ADD COLUMN note TEXT",
        "ALTER TABLE teams ADD COLUMN category TEXT",
        "ALTER TABLE counters ADD COLUMN punchup TEXT",
    ]
    for sql in migrations:
        try:
            cursor.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            category TEXT
        );

        CREATE TABLE IF NOT EXISTS counters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            counter_team_id INTEGER NOT NULL,
            note TEXT,
            punchup TEXT,
            FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
            FOREIGN KEY (counter_team_id) REFERENCES teams(id) ON DELETE CASCADE,
            UNIQUE (team_id, counter_team_id)
        );

        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        );
    """)
    _migrate(cursor, conn)
    conn.close()


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

def get_or_create_team(name: str) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO teams (name) VALUES (?)", (name,))
    conn.commit()
    cursor.execute("SELECT id FROM teams WHERE name = ? COLLATE NOCASE", (name,))
    row = cursor.fetchone()
    conn.close()
    return row["id"]


def get_team_row(name: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, category FROM teams WHERE name = ? COLLATE NOCASE", (name,)
    )
    row = cursor.fetchone()
    conn.close()
    return row if row else None


def get_team_canonical_name(team_name: str):
    row = get_team_row(team_name)
    return row["name"] if row else None


def add_team(name: str) -> tuple[bool, str]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO teams (name) VALUES (?)", (name,))
        conn.commit()
        return True, f"✅ Team <b>{name}</b> created."
    except sqlite3.IntegrityError:
        canonical = get_team_canonical_name(name)
        return False, f"Team <b>{canonical}</b> already exists."
    finally:
        conn.close()


def del_team(name: str) -> tuple[bool, str]:
    row = get_team_row(name)
    if not row:
        return False, f"Team not found: <b>{name}</b>"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM teams WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return True, f"🗑️ Team <b>{row['name']}</b> and all its counters have been deleted."


def set_category(team_name: str, category: str) -> tuple[bool, str]:
    if category not in VALID_CATEGORIES:
        cats = ", ".join(VALID_CATEGORIES)
        return False, f"❌ Invalid category. Choose one of: {cats}"
    row = get_team_row(team_name)
    if not row:
        return False, f"Team not found: <b>{team_name}</b>"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE teams SET category = ? WHERE id = ?", (category, row["id"]))
    conn.commit()
    conn.close()
    emoji = CATEGORY_EMOJI.get(category, "")
    return True, f"✅ <b>{row['name']}</b> is now in category {emoji} <b>{category}</b>."


def list_all_teams() -> list[dict]:
    """Return all teams that appear in at least one counter, sorted alphabetically."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT t.name, t.category
        FROM teams t
        WHERE EXISTS (
            SELECT 1 FROM counters c WHERE c.team_id = t.id OR c.counter_team_id = t.id
        )
        ORDER BY t.name COLLATE NOCASE
        """
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r["name"], "category": r["category"]} for r in rows]


def list_all_teams_full() -> list[dict]:
    """Return ALL teams (including those with no counters), sorted alphabetically."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, category FROM teams ORDER BY name COLLATE NOCASE"
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r["name"], "category": r["category"]} for r in rows]


def list_teams_by_category(category: str) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT name, category FROM teams
        WHERE category = ? COLLATE NOCASE
        ORDER BY name COLLATE NOCASE
        """,
        (category,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r["name"], "category": r["category"]} for r in rows]


def search_teams(query: str) -> list[str]:
    """Partial name search — returns only teams that have at least one counter."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT t.name
        FROM teams t
        WHERE t.name LIKE ? COLLATE NOCASE
          AND EXISTS (
              SELECT 1 FROM counters c WHERE c.team_id = t.id OR c.counter_team_id = t.id
          )
        ORDER BY t.name COLLATE NOCASE
        """,
        (f"%{query}%",),
    )
    rows = cursor.fetchall()
    conn.close()
    return [r["name"] for r in rows]


def get_teams_countered_by(team_name: str) -> list[dict]:
    """Return all teams that the given team counters (reverse lookup)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT t_target.name AS team_name, c.note, c.punchup
        FROM counters c
        JOIN teams t_counter ON t_counter.id = c.counter_team_id
        JOIN teams t_target ON t_target.id = c.team_id
        WHERE t_counter.name = ? COLLATE NOCASE
        ORDER BY t_target.name COLLATE NOCASE
        """,
        (team_name,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r["team_name"], "note": r["note"], "punchup": r["punchup"]} for r in rows]


def search_all_teams(query: str) -> list[str]:
    """Partial name search across ALL teams (including those with no counters)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT name FROM teams
        WHERE name LIKE ? COLLATE NOCASE
        ORDER BY name COLLATE NOCASE
        """,
        (f"%{query}%",),
    )
    rows = cursor.fetchall()
    conn.close()
    return [r["name"] for r in rows]


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

def add_counter(
    team_name: str,
    counter_team_name: str,
    note: str = None,
    punchup: str = None,
) -> tuple[bool, str]:
    team_row = get_team_row(team_name)
    counter_row = get_team_row(counter_team_name)

    team_id = get_or_create_team(team_name) if not team_row else team_row["id"]
    counter_id = get_or_create_team(counter_team_name) if not counter_row else counter_row["id"]

    team_canonical = team_row["name"] if team_row else team_name
    counter_canonical = counter_row["name"] if counter_row else counter_team_name

    if team_id == counter_id:
        return False, "A team cannot counter itself."

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO counters (team_id, counter_team_id, note, punchup) VALUES (?, ?, ?, ?)",
            (team_id, counter_id, note, punchup),
        )
        conn.commit()
        msg = f"✅ Added: <b>{counter_canonical}</b> counters <b>{team_canonical}</b>"
        if punchup:
            msg += f"\n👊 Punch-up: {punchup}"
        if note:
            msg += f"\n📝 Note: {note}"
        return True, msg
    except sqlite3.IntegrityError:
        return False, f"Counter already exists: <b>{counter_canonical}</b> already counters <b>{team_canonical}</b>"
    finally:
        conn.close()


def del_counter(team_name: str, counter_team_name: str) -> tuple[bool, str]:
    team_row = get_team_row(team_name)
    counter_row = get_team_row(counter_team_name)

    if not team_row:
        return False, f"Team not found: <b>{team_name}</b>"
    if not counter_row:
        return False, f"Team not found: <b>{counter_team_name}</b>"

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM counters WHERE team_id = ? AND counter_team_id = ?",
        (team_row["id"], counter_row["id"]),
    )
    conn.commit()
    affected = cursor.rowcount
    conn.close()

    if affected:
        return True, f"🗑️ Removed: <b>{counter_row['name']}</b> no longer counters <b>{team_row['name']}</b>"
    return False, f"No such counter found: <b>{counter_row['name']}</b> vs <b>{team_row['name']}</b>"


def get_counters_for_team(team_name: str) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT t_counter.name AS counter_name, c.note, c.punchup
        FROM counters c
        JOIN teams t ON t.id = c.team_id
        JOIN teams t_counter ON t_counter.id = c.counter_team_id
        WHERE t.name = ? COLLATE NOCASE
        ORDER BY t_counter.name COLLATE NOCASE
        """,
        (team_name,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r["counter_name"], "note": r["note"], "punchup": r["punchup"]} for r in rows]


def import_csv_data(rows: list[dict]) -> dict:
    """
    Bulk-import counter data from parsed CSV rows.
    Each row dict must have: Team, Counter, PunchUp (optional), Note (optional).
    - If Team + Counter does not exist: create it.
    - If Team + Counter already exists: update PunchUp and Note.
    - Skips rows with missing Team/Counter or where Team == Counter.
    Returns counts: teams_created, counters_added, counters_updated, skipped.
    """
    teams_created = 0
    counters_added = 0
    counters_updated = 0
    skipped = 0

    conn = get_connection()
    cursor = conn.cursor()

    for row in rows:
        team_name = (row.get("Team") or "").strip()
        counter_name = (row.get("Counter") or "").strip()
        punchup = (row.get("PunchUp") or "").strip() or None
        note = (row.get("Note") or "").strip() or None

        if not team_name or not counter_name:
            skipped += 1
            continue

        if team_name.lower() == counter_name.lower():
            skipped += 1
            continue

        # Create team if missing
        result = cursor.execute(
            "SELECT id FROM teams WHERE name = ? COLLATE NOCASE", (team_name,)
        ).fetchone()
        if result:
            team_id = result["id"]
        else:
            cursor.execute("INSERT INTO teams (name) VALUES (?)", (team_name,))
            team_id = cursor.lastrowid
            teams_created += 1

        # Create counter team if missing
        result = cursor.execute(
            "SELECT id FROM teams WHERE name = ? COLLATE NOCASE", (counter_name,)
        ).fetchone()
        if result:
            counter_id = result["id"]
        else:
            cursor.execute("INSERT INTO teams (name) VALUES (?)", (counter_name,))
            counter_id = cursor.lastrowid
            teams_created += 1

        # Insert or update counter
        existing = cursor.execute(
            "SELECT id FROM counters WHERE team_id = ? AND counter_team_id = ?",
            (team_id, counter_id),
        ).fetchone()

        if existing:
            cursor.execute(
                "UPDATE counters SET punchup = ?, note = ? WHERE id = ?",
                (punchup, note, existing["id"]),
            )
            counters_updated += 1
        else:
            cursor.execute(
                "INSERT INTO counters (team_id, counter_team_id, note, punchup) VALUES (?, ?, ?, ?)",
                (team_id, counter_id, note, punchup),
            )
            counters_added += 1

    conn.commit()
    conn.close()
    return {
        "teams_created": teams_created,
        "counters_added": counters_added,
        "counters_updated": counters_updated,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Admins
# ---------------------------------------------------------------------------

def is_admin(user_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None


def add_admin(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def remove_admin(user_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0


def list_admins() -> list[int]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins ORDER BY user_id")
    rows = cursor.fetchall()
    conn.close()
    return [r["user_id"] for r in rows]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def reset_database() -> dict:
    """Delete all teams, counters, and notes. Admins are preserved."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS cnt FROM teams")
    teams = cursor.fetchone()["cnt"]
    cursor.execute("SELECT COUNT(*) AS cnt FROM counters")
    counters = cursor.fetchone()["cnt"]
    cursor.execute("DELETE FROM counters")
    cursor.execute("DELETE FROM teams")
    conn.commit()
    conn.close()
    return {"teams_deleted": teams, "counters_deleted": counters}


def get_stats() -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS cnt FROM teams")
    teams = cursor.fetchone()["cnt"]
    cursor.execute("SELECT COUNT(*) AS cnt FROM counters")
    counters = cursor.fetchone()["cnt"]
    cursor.execute("SELECT COUNT(*) AS cnt FROM admins")
    admins = cursor.fetchone()["cnt"]

    # Per-category breakdown
    cursor.execute(
        "SELECT category, COUNT(*) AS cnt FROM teams WHERE category IS NOT NULL GROUP BY category"
    )
    by_cat = {r["category"]: r["cnt"] for r in cursor.fetchall()}
    conn.close()
    return {
        "teams": teams,
        "counters": counters,
        "admins": admins,
        "by_category": by_cat,
    }
