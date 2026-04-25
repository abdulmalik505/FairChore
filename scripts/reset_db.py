#!/usr/bin/env python
"""
Safely reset FairChore database to clean seed data.
Drops all tables and reinitializes with schema.sql.
"""

import sys
import os
import io

# Fix encoding for Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import psycopg2
from psycopg2 import sql

# Database connection details — read from .env if present, otherwise defaults.
from dotenv import load_dotenv
load_dotenv()

def _parse_db_url(url):
    """Tiny parser: postgresql://user:pass@host:port/dbname → kwargs dict."""
    from urllib.parse import urlparse
    p = urlparse(url)
    return {
        "host":     p.hostname or "localhost",
        "port":     p.port or 5432,
        "user":     p.username or "postgres",
        "password": p.password or "",
        "database": (p.path or "/").lstrip("/") or "fairchore",
    }

_url = os.environ.get("DATABASE_URL", "postgresql://postgres:REDACTED@localhost:5432/fairchore")
DB_CONFIG = _parse_db_url(_url)
DB_NAME   = DB_CONFIG.pop("database")


def _admin_connect():
    """Connect to the postgres admin DB so we can CREATE/DROP the target DB."""
    return psycopg2.connect(dbname="postgres", **DB_CONFIG)


def get_connection():
    """Connect to the target DB. Auto-creates it if it doesn't exist."""
    try:
        return psycopg2.connect(dbname=DB_NAME, **DB_CONFIG)
    except psycopg2.OperationalError as e:
        if "does not exist" not in str(e):
            print(f"[X] Failed to connect to database: {e}")
            sys.exit(1)
        # DB doesn't exist yet — create it.
        print(f"  [INFO] Database '{DB_NAME}' not found, creating it...")
        admin = _admin_connect()
        admin.autocommit = True
        cur = admin.cursor()
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
        cur.close()
        admin.close()
        return psycopg2.connect(dbname=DB_NAME, **DB_CONFIG)


def drop_all_tables(cursor):
    """Drop all tables in the database."""
    print("Dropping existing tables...")

    # Get list of all tables
    cursor.execute("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
    """)
    tables = cursor.fetchall()

    if not tables:
        print("  [OK] No tables to drop")
        return

    for (table,) in tables:
        print(f"  [DROP] {table}")
        cursor.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
            sql.Identifier(table)
        ))


def parse_sql_statements(sql_text):
    """Parse SQL statements, handling comments properly."""
    statements = []
    current = []

    for line in sql_text.split('\n'):
        # Strip comments
        if '--' in line:
            line = line[:line.index('--')]

        line = line.strip()
        if not line:
            continue

        current.append(line)

        if line.endswith(';'):
            statement = ' '.join(current).strip()
            if statement:
                statements.append(statement)
            current = []

    return statements


def execute_schema(cursor, schema_path):
    """Execute schema.sql to create tables and seed data."""
    if not os.path.exists(schema_path):
        print(f"[ERROR] Schema file not found: {schema_path}")
        sys.exit(1)

    print(f"\nLoading schema from {schema_path}...")

    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_sql = f.read()

    # Parse SQL statements properly (handle comments)
    statements = parse_sql_statements(schema_sql)

    for i, statement in enumerate(statements, 1):
        try:
            cursor.execute(statement)
            print(f"  [OK] Statement {i}/{len(statements)}")
        except psycopg2.Error as e:
            print(f"  [ERROR] Statement {i}: {e}")
            raise


def verify_data(cursor):
    """Verify seed data was loaded correctly."""
    print("\nVerifying seed data...")

    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    print(f"  [OK] Users: {user_count}")

    cursor.execute("SELECT COUNT(*) FROM households")
    household_count = cursor.fetchone()[0]
    print(f"  [OK] Households: {household_count}")

    cursor.execute("SELECT COUNT(*) FROM chores")
    chore_count = cursor.fetchone()[0]
    print(f"  [OK] Chores: {chore_count}")

    cursor.execute("SELECT COUNT(*) FROM burden_scores")
    burden_count = cursor.fetchone()[0]
    print(f"  [OK] Burden scores: {burden_count}")

    # Show test households
    cursor.execute("SELECT id, name, join_code FROM households ORDER BY id")
    households = cursor.fetchall()
    print(f"\nTest Households:")
    for hid, name, code in households:
        cursor.execute("SELECT COUNT(*) FROM household_members WHERE household_id = %s", (hid,))
        member_count = cursor.fetchone()[0]
        print(f"  - {name} (code: {code}) - {member_count} members")


def main():
    """Main reset flow."""
    print("=" * 70)
    print("FairChore Database Reset Tool")
    print("=" * 70)

    # Get schema path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    schema_path = os.path.join(project_root, "schema.sql")

    print(f"\nDatabase: {DB_NAME}")
    print(f"Schema file: {schema_path}")

    # Confirm action (skip if --yes flag provided)
    skip_confirmation = '--yes' in sys.argv
    if not skip_confirmation:
        response = input("\n[WARNING] This will DELETE all data and reload seed data.\nContinue? (y/N): ")
        if response.lower() != 'y':
            print("[CANCELLED]")
            sys.exit(0)
    else:
        print("\n[AUTO] Proceeding with database reset (--yes flag)")

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Reset process
        drop_all_tables(cursor)
        execute_schema(cursor, schema_path)
        verify_data(cursor)

        conn.commit()
        cursor.close()
        conn.close()

        print("\n" + "=" * 70)
        print("[SUCCESS] Database reset successfully!")
        print("=" * 70)
        print("\nTest Accounts (all passwords: test123):")
        print("  - admin@flat42.com    (Flat 42)")
        print("  - admin@smiths.com    (The Smiths)")
        print("  - admin@family.com    (Family Home)")
        print("\nReady to start the backend and frontend for demo!")

    except psycopg2.Error as e:
        print(f"\n[ERROR] Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
