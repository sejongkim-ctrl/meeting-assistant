"""SQLite database setup via aiosqlite."""

import os
import sqlite3
from pathlib import Path

import aiosqlite

DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent / "meeting_assistant.db"))


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def create_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                transcript TEXT,
                diarized_script TEXT,
                summary TEXT,
                wav_path TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.commit()
        # Migration: add generated_docs column if not present (SQLite has no IF NOT EXISTS for columns)
        try:
            await db.execute("ALTER TABLE notes ADD COLUMN generated_docs TEXT")
            await db.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
        # Migration: add share_token column if not present
        try:
            await db.execute("ALTER TABLE notes ADD COLUMN share_token TEXT")
            await db.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
        # FTS5 virtual table for full-text search
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
            USING fts5(title, summary, transcript_text, note_id UNINDEXED, content='', contentless_delete=1)
        """)
        await db.commit()
