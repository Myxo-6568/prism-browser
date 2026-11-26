"""Repository operations for saved distillations and their sources."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .db import Database


@dataclass(frozen=True)
class DistillationRecord:
    """A saved distillation and its first recorded source."""

    id: int
    created_at: str
    title: str
    mode: str
    markdown: str
    html: str
    source_url: str = ""
    source_title: str = ""


@dataclass(frozen=True)
class SpectrumBlockRecord:
    """One editable block saved inside a Spectrum."""

    id: int
    position: int
    kind: str
    content: str
    source_url: str


@dataclass(frozen=True)
class SpectrumRecord:
    """A saved Spectrum and its ordered blocks."""

    id: int
    created_at: str
    updated_at: str
    title: str
    source_url: str
    blocks: list[SpectrumBlockRecord]


@dataclass(frozen=True)
class SpectrumChatMessage:
    """A persisted message in a Spectrum's AI conversation."""

    id: int
    role: str
    content: str
    image_paths: list[str]
    created_at: str


class LibraryRepository:
    """Encapsulate queries used by the distillation library UI."""

    def __init__(self, database: Database):
        self.database = database

    def save_distillation(
        self,
        title: str,
        mode: str,
        markdown: str,
        html: str,
        sources: list[dict[str, str]],
    ) -> int:
        """Persist a distillation and all of its source metadata."""
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO distillations (title, mode, markdown, html)
                VALUES (?, ?, ?, ?)
                """,
                (title, mode, markdown, html),
            )
            distillation_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO distillation_sources (distillation_id, url, title)
                VALUES (?, ?, ?)
                """,
                [
                    (
                        distillation_id,
                        source.get("url", ""),
                        source.get("title", ""),
                    )
                    for source in sources
                ],
            )
            return distillation_id

    def search_distillations(self, query: str = "") -> list[DistillationRecord]:
        """Search saved titles, Markdown, and source URLs."""
        pattern = f"%{query.strip()}%"
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT d.id, d.created_at, d.title, d.mode, d.markdown, d.html,
                       COALESCE(s.url, '') AS source_url,
                       COALESCE(s.title, '') AS source_title
                FROM distillations AS d
                LEFT JOIN distillation_sources AS s ON s.id = (
                    SELECT MIN(s2.id)
                    FROM distillation_sources AS s2
                    WHERE s2.distillation_id = d.id
                )
                WHERE ? = ''
                   OR d.title LIKE ?
                   OR d.markdown LIKE ?
                   OR EXISTS (
                       SELECT 1 FROM distillation_sources AS matched
                       WHERE matched.distillation_id = d.id AND matched.url LIKE ?
                   )
                ORDER BY d.created_at DESC, d.id DESC
                """,
                (query.strip(), pattern, pattern, pattern),
            ).fetchall()
        return [DistillationRecord(**dict(row)) for row in rows]

    def get_distillation(self, distillation_id: int) -> DistillationRecord | None:
        """Fetch one saved distillation by its database ID."""
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT d.id, d.created_at, d.title, d.mode, d.markdown, d.html,
                       COALESCE(s.url, '') AS source_url,
                       COALESCE(s.title, '') AS source_title
                FROM distillations AS d
                LEFT JOIN distillation_sources AS s ON s.id = (
                    SELECT MIN(s2.id)
                    FROM distillation_sources AS s2
                    WHERE s2.distillation_id = d.id
                )
                WHERE d.id = ?
                """,
                (distillation_id,),
            ).fetchone()
        return DistillationRecord(**dict(row)) if row else None

    def delete_distillation(self, distillation_id: int) -> bool:
        """Delete a distillation and its sources; return whether a row existed."""
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM distillations WHERE id = ?", (distillation_id,)
            )
            return cursor.rowcount > 0

    def get_setting(self, key: str, default: str = "") -> str:
        """Return a setting value, or the supplied default when unset."""
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        """Insert or update a persisted application setting."""
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )


class SpectrumRepository:
    """Encapsulate persistent Spectrum and ordered block operations."""

    BLOCK_KINDS = {"text", "image", "quote", "heading"}

    def __init__(self, database: Database):
        self.database = database

    def save_spectrum(
        self,
        spectrum_id: int | None,
        title: str,
        source_url: str,
        blocks: list[dict[str, object]],
    ) -> int:
        """Create or update a Spectrum, retaining IDs for existing blocks."""
        normalized_title = title.strip() or "Untitled Spectrum"
        with self.database.connect() as connection:
            if spectrum_id is None:
                cursor = connection.execute(
                    "INSERT INTO spectrums (title, source_url) VALUES (?, ?)",
                    (normalized_title, source_url),
                )
                spectrum_id = int(cursor.lastrowid)
            else:
                cursor = connection.execute(
                    """
                    UPDATE spectrums
                    SET title = ?, source_url = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (normalized_title, source_url, spectrum_id),
                )
                if cursor.rowcount == 0:
                    raise ValueError(f"Spectrum {spectrum_id} does not exist.")

            existing_rows = connection.execute(
                "SELECT id FROM spectrum_blocks WHERE spectrum_id = ?",
                (spectrum_id,),
            ).fetchall()
            existing_ids = {int(row["id"]) for row in existing_rows}
            requested_ids: set[int] = set()
            for position, block in enumerate(blocks):
                kind = str(block.get("kind", "text"))
                if kind not in self.BLOCK_KINDS:
                    raise ValueError(f"Unsupported Spectrum block kind: {kind}")
                content = str(block.get("content", ""))
                source = str(block.get("source_url", ""))
                raw_id = block.get("id")
                block_id = int(raw_id) if raw_id not in (None, "") else None
                if block_id is not None:
                    if block_id not in existing_ids or block_id in requested_ids:
                        raise ValueError("Spectrum block ID is invalid or duplicated.")
                    requested_ids.add(block_id)
                    connection.execute(
                        """
                        UPDATE spectrum_blocks
                        SET position = ?, kind = ?, content = ?, source_url = ?
                        WHERE id = ? AND spectrum_id = ?
                        """,
                        (position, kind, content, source, block_id, spectrum_id),
                    )
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO spectrum_blocks
                            (spectrum_id, position, kind, content, source_url)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (spectrum_id, position, kind, content, source),
                    )
                    requested_ids.add(int(cursor.lastrowid))

            removed_ids = existing_ids - requested_ids
            if removed_ids:
                placeholders = ",".join("?" for _ in removed_ids)
                connection.execute(
                    f"DELETE FROM spectrum_blocks WHERE spectrum_id = ? "
                    f"AND id IN ({placeholders})",
                    (spectrum_id, *sorted(removed_ids)),
                )
            connection.execute(
                "UPDATE spectrums SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (spectrum_id,),
            )
        return spectrum_id

    def get_spectrum(self, spectrum_id: int) -> SpectrumRecord | None:
        """Fetch a Spectrum and its blocks in saved order."""
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, created_at, updated_at, title, source_url
                FROM spectrums WHERE id = ?
                """,
                (spectrum_id,),
            ).fetchone()
            if row is None:
                return None
            block_rows = connection.execute(
                """
                SELECT id, position, kind, content, source_url
                FROM spectrum_blocks
                WHERE spectrum_id = ?
                ORDER BY position, id
                """,
                (spectrum_id,),
            ).fetchall()
        return SpectrumRecord(
            id=int(row["id"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            title=str(row["title"]),
            source_url=str(row["source_url"]),
            blocks=[SpectrumBlockRecord(**dict(block)) for block in block_rows],
        )

    def list_spectrums(self) -> list[SpectrumRecord]:
        """Return saved Spectrums newest-updated first."""
        with self.database.connect() as connection:
            ids = connection.execute(
                "SELECT id FROM spectrums ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        records = [self.get_spectrum(int(row["id"])) for row in ids]
        return [record for record in records if record is not None]

    def delete_spectrum(self, spectrum_id: int) -> bool:
        """Delete a Spectrum and its dependent blocks."""
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM spectrums WHERE id = ?", (spectrum_id,)
            )
            return cursor.rowcount > 0

    def get_annotations(self, spectrum_id: int) -> list[dict[str, object]]:
        """Return persisted drawing and text-highlight annotation payloads."""
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT block_id, data_json FROM spectrum_annotations
                WHERE spectrum_id = ? ORDER BY id
                """,
                (spectrum_id,),
            ).fetchall()
        annotations: list[dict[str, object]] = []
        for row in rows:
            try:
                data = json.loads(row["data_json"])
            except (TypeError, ValueError):
                continue
            if isinstance(data, dict):
                data["block_id"] = row["block_id"]
                annotations.append(data)
        return annotations

    def save_annotations(
        self, spectrum_id: int, annotations: list[dict[str, object]]
    ) -> None:
        """Replace a Spectrum's annotations in one validated transaction."""
        with self.database.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM spectrums WHERE id = ?", (spectrum_id,)
            ).fetchone()
            if exists is None:
                raise ValueError(f"Spectrum {spectrum_id} does not exist.")
            block_ids = {
                int(row["id"])
                for row in connection.execute(
                    "SELECT id FROM spectrum_blocks WHERE spectrum_id = ?",
                    (spectrum_id,),
                ).fetchall()
            }
            connection.execute(
                "DELETE FROM spectrum_annotations WHERE spectrum_id = ?",
                (spectrum_id,),
            )
            for annotation in annotations:
                if not isinstance(annotation, dict):
                    raise ValueError("Spectrum annotations must be objects.")
                block_id = annotation.get("block_id")
                if block_id is not None:
                    try:
                        block_id = int(block_id)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("Annotation block ID is invalid.") from exc
                    if block_id not in block_ids:
                        raise ValueError(
                            "Annotation references a block outside this Spectrum."
                        )
                payload = {
                    key: value
                    for key, value in annotation.items()
                    if key != "block_id"
                }
                connection.execute(
                    """
                    INSERT INTO spectrum_annotations
                        (spectrum_id, block_id, data_json)
                    VALUES (?, ?, ?)
                    """,
                    (
                        spectrum_id,
                        block_id,
                        json.dumps(payload, separators=(",", ":")),
                    ),
                )
            connection.execute(
                "UPDATE spectrums SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (spectrum_id,),
            )

    def save_chat_message(
        self,
        spectrum_id: int,
        role: str,
        content: str,
        image_paths: list[str] | None = None,
    ) -> int:
        """Persist a user or assistant message with optional app-data image paths."""
        if role not in {"user", "assistant"}:
            raise ValueError("Chat message role must be user or assistant.")
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO chat_messages
                    (spectrum_id, role, content, image_paths_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    spectrum_id,
                    role,
                    content,
                    json.dumps(image_paths or []),
                ),
            )
            connection.execute(
                "UPDATE spectrums SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (spectrum_id,),
            )
            return int(cursor.lastrowid)

    def list_chat_messages(self, spectrum_id: int) -> list[SpectrumChatMessage]:
        """Return the chronological persisted chat for a Spectrum."""
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, role, content, image_paths_json, created_at
                FROM chat_messages WHERE spectrum_id = ?
                ORDER BY id
                """,
                (spectrum_id,),
            ).fetchall()
        messages = []
        for row in rows:
            try:
                image_paths = json.loads(row["image_paths_json"])
            except (TypeError, ValueError):
                image_paths = []
            if not isinstance(image_paths, list):
                image_paths = []
            messages.append(
                SpectrumChatMessage(
                    id=int(row["id"]),
                    role=str(row["role"]),
                    content=str(row["content"]),
                    image_paths=[str(path) for path in image_paths],
                    created_at=str(row["created_at"]),
                )
            )
        return messages
