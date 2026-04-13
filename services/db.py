"""
Модуль для роботи з базою даних SQLite.
Мiстить функцiї iнiцiалiзацiї БД та управлiння з'єднанням.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from flask import g, current_app


def get_db():
    """
    Отримати з'єднання з базою даних.
    З'єднання зберiгається в контекстi запиту Flask.
    """
    if "db" not in g:
        db_path = current_app.config.get("DATABASE_PATH", "pharmaref.db")
        g.db = sqlite3.connect(
            db_path,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
        # Увiмкнути пiдтримку зовнiшнiх ключiв
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    """Закрити з'єднання з базою даних."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def get_db_connection(db_path=None):
    """
    Контекстний менеджер для з'єднання з БД поза контекстом Flask.
    Використовується для iнiцiалiзацiї та мiграцiй.
    """
    if db_path is None:
        from config import Config
        db_path = Config.DATABASE_PATH

    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path=None):
    """
    Iнiцiалiзацiя бази даних: створення всiх таблиць та iндексiв.
    """
    schema = """
    -- Основна таблиця лiкарських засобiв
    CREATE TABLE IF NOT EXISTS drugs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL CHECK(source IN ('ua', 'fda')),
        trade_name TEXT NOT NULL,
        inn TEXT,
        atc_code TEXT,
        indications TEXT,
        dispensing TEXT,
        reg_number TEXT,
        status TEXT,
        fda_set_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Iндекси для швидкого пошуку
    CREATE INDEX IF NOT EXISTS idx_drugs_source ON drugs(source);
    CREATE INDEX IF NOT EXISTS idx_drugs_inn ON drugs(inn);
    CREATE INDEX IF NOT EXISTS idx_drugs_atc ON drugs(atc_code);
    CREATE INDEX IF NOT EXISTS idx_drugs_trade_name ON drugs(trade_name);

    -- FTS5 вiртуальна таблиця для повнотекстового пошуку
    CREATE VIRTUAL TABLE IF NOT EXISTS drugs_fts USING fts5(
        trade_name,
        inn,
        indications,
        content='drugs',
        content_rowid='id'
    );

    -- Тригери для синхронiзацiї FTS5 з основною таблицею
    CREATE TRIGGER IF NOT EXISTS drugs_ai AFTER INSERT ON drugs BEGIN
        INSERT INTO drugs_fts(rowid, trade_name, inn, indications)
        VALUES (new.id, new.trade_name, new.inn, new.indications);
    END;

    CREATE TRIGGER IF NOT EXISTS drugs_ad AFTER DELETE ON drugs BEGIN
        INSERT INTO drugs_fts(drugs_fts, rowid, trade_name, inn, indications)
        VALUES ('delete', old.id, old.trade_name, old.inn, old.indications);
    END;

    CREATE TRIGGER IF NOT EXISTS drugs_au AFTER UPDATE ON drugs BEGIN
        INSERT INTO drugs_fts(drugs_fts, rowid, trade_name, inn, indications)
        VALUES ('delete', old.id, old.trade_name, old.inn, old.indications);
        INSERT INTO drugs_fts(rowid, trade_name, inn, indications)
        VALUES (new.id, new.trade_name, new.inn, new.indications);
    END;

    -- Таблиця контрольованих речовин України (КМУ №770/2000)
    CREATE TABLE IF NOT EXISTS controlled_ua (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        substance TEXT NOT NULL UNIQUE,
        table_num INTEGER NOT NULL CHECK(table_num IN (1, 2, 3)),
        list_num INTEGER,
        level TEXT NOT NULL CHECK(level IN ('forbidden', 'restricted', 'precursor'))
    );

    CREATE INDEX IF NOT EXISTS idx_controlled_ua_substance ON controlled_ua(substance);

    -- Таблиця контрольованих речовин DEA (США)
    CREATE TABLE IF NOT EXISTS controlled_dea (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        substance TEXT NOT NULL UNIQUE,
        schedule TEXT NOT NULL CHECK(schedule IN ('I', 'II', 'III', 'IV', 'V'))
    );

    CREATE INDEX IF NOT EXISTS idx_controlled_dea_substance ON controlled_dea(substance);

    -- Таблиця ATC класифiкатора
    CREATE TABLE IF NOT EXISTS atc (
        code TEXT PRIMARY KEY,
        name_uk TEXT,
        name_en TEXT
    );

    -- Таблиця кешу для OpenFDA запитiв
    CREATE TABLE IF NOT EXISTS cache (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        expires_at TIMESTAMP NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);

    -- Таблиця метаданих (дата оновлення DRLZ тощо)
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    with get_db_connection(db_path) as conn:
        conn.executescript(schema)


def rebuild_fts_index(db_path=None):
    """
    Перебудувати FTS5 iндекс.
    Викликається пiсля масового завантаження даних.
    """
    with get_db_connection(db_path) as conn:
        # Очистити FTS таблицю
        conn.execute("DELETE FROM drugs_fts")
        # Заповнити заново
        conn.execute("""
            INSERT INTO drugs_fts(rowid, trade_name, inn, indications)
            SELECT id, trade_name, inn, indications FROM drugs
        """)


def clear_drugs_table(db_path=None, source=None):
    """
    Очистити таблицю лiкiв.
    Якщо вказано source, видаляє тiльки записи з цього джерела.
    """
    with get_db_connection(db_path) as conn:
        if source:
            conn.execute("DELETE FROM drugs WHERE source = ?", (source,))
        else:
            conn.execute("DELETE FROM drugs")


def get_db_info(db_path=None):
    """
    Отримати iнформацiю про базу даних.
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        # Кiлькiсть записiв
        cursor.execute("SELECT COUNT(*) FROM drugs WHERE source = 'ua'")
        ua_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM drugs WHERE source = 'fda'")
        fda_count = cursor.fetchone()[0]

        # Дата оновлення DRLZ
        cursor.execute("SELECT value FROM metadata WHERE key = 'drlz_updated_at'")
        row = cursor.fetchone()
        drlz_updated = row[0] if row else None

        return {
            "ua_drugs_count": ua_count,
            "fda_drugs_count": fda_count,
            "total_drugs_count": ua_count + fda_count,
            "drlz_updated_at": drlz_updated
        }


def init_app(app):
    """
    Iнiцiалiзацiя модуля БД для Flask застосунку.
    """
    app.teardown_appcontext(close_db)
