"""SQLite database setup and forward-only schema migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PyQt6.QtCore import QStandardPaths

CURRENT_SCHEMA_VERSION = 1


class Database:
    """Provide initialized SQLite connections for Prism's app-data database."""

    def __init__(self, path: str | Path | None = None):
        if path is None:
            data_dir = Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppDataLocation
                )
            )
            data_dir.mkdir(parents=True, exist_ok=True)
            path = data_dir / "prism.sqlite3"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        """Open a configured connection with foreign keys and row access enabled."""
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        """Create the schema and apply any pending forward migrations."""
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, 0)"
            )
            row = connection.execute(
                "SELECT version FROM schema_version WHERE id = 1"
            ).fetchone()
            version = int(row["version"])
            while version < CURRENT_SCHEMA_VERSION:
                next_version = version + 1
                self._apply_migration(connection, next_version)
                connection.execute(
                    "UPDATE schema_version SET version = ? WHERE id = 1",
                    (next_version,),
                )
                version = next_version
            if version > CURRENT_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema {version} is newer than supported schema "
                    f"{CURRENT_SCHEMA_VERSION}."
                )

    @staticmethod
    def _apply_migration(connection: sqlite3.Connection, version: int) -> None:
        """Apply one versioned schema migration."""
        if version != 1:
            raise RuntimeError(f"No database migration is defined for version {version}.")
        statements = (
            """
            CREATE TABLE distillations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                title TEXT NOT NULL,
                mode TEXT NOT NULL,
                markdown TEXT NOT NULL,
                html TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE distillation_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                distillation_id INTEGER NOT NULL
                    REFERENCES distillations(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                title TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE spectrums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                title TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            CREATE TABLE spectrum_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spectrum_id INTEGER NOT NULL
                    REFERENCES spectrums(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('text', 'image', 'quote', 'heading')),
                content TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            CREATE TABLE spectrum_annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spectrum_id INTEGER NOT NULL
                    REFERENCES spectrums(id) ON DELETE CASCADE,
                block_id INTEGER REFERENCES spectrum_blocks(id) ON DELETE SET NULL,
                data_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spectrum_id INTEGER REFERENCES spectrums(id) ON DELETE SET NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                image_paths_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
        )
        for statement in statements:
            connection.execute(statement)
