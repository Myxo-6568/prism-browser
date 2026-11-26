"""Python persistence and safe Markdown bridge for the Spectrum editor."""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import uuid
from pathlib import Path

from PyQt6.QtCore import QObject, QStandardPaths, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from prism.distill.core import _render_markdown
from prism.storage import SpectrumRepository

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
IMAGE_FETCH_TIMEOUT_MS = 20_000


class SpectrumBridge(QObject):
    """Expose a Spectrum record and persistence operations to its local editor."""

    errorOccurred = pyqtSignal(str)
    appearanceChanged = pyqtSignal(str)
    chatRequested = pyqtSignal(str, str)
    insertRequested = pyqtSignal(str, str)
    imageFetched = pyqtSignal(str, str, str)
    imageFetchFailed = pyqtSignal(str, str)

    def __init__(
        self,
        repository: SpectrumRepository,
        spectrum_id: int,
        appearance: dict[str, str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.spectrum_id = spectrum_id
        self._appearance = appearance or {"theme": "light", "accent": "#6d5ce7"}
        self._network = QNetworkAccessManager(self)
        self._image_replies: dict[str, QNetworkReply] = {}

    def set_appearance(self, appearance: dict[str, str]) -> None:
        """Update the colors used by the local Spectrum document."""
        self._appearance = appearance
        self.appearanceChanged.emit(json.dumps(appearance))

    @pyqtSlot(result=str)
    def get_appearance(self) -> str:
        """Return the active browser theme and accent."""
        return json.dumps(self._appearance)

    @pyqtSlot(result=str)
    def get_spectrum(self) -> str:
        """Return the record and ordered blocks as JSON."""
        try:
            record = self.repository.get_spectrum(self.spectrum_id)
        except sqlite3.Error as exc:
            self.errorOccurred.emit(str(exc))
            return ""
        if record is None:
            message = "This Spectrum no longer exists."
            self.errorOccurred.emit(message)
            return ""
        return json.dumps(
            {
                "id": record.id,
                "title": record.title,
                "source_url": record.source_url,
                "blocks": [
                    {
                        "id": block.id,
                        "kind": block.kind,
                        "content": block.content,
                        "source_url": block.source_url,
                    }
                    for block in record.blocks
                ],
            }
        )

    @pyqtSlot(str, result=str)
    def save_spectrum(self, encoded: str) -> str:
        """Persist the editor's current title and ordered block data."""
        try:
            payload = json.loads(encoded)
            if not isinstance(payload, dict) or not isinstance(
                payload.get("blocks"), list
            ):
                raise ValueError("Spectrum data has an invalid shape.")
            if not all(isinstance(block, dict) for block in payload["blocks"]):
                raise ValueError("Every Spectrum block must be an object.")
            self.repository.save_spectrum(
                self.spectrum_id,
                str(payload.get("title", "")),
                str(payload.get("source_url", "")),
                payload["blocks"],
            )
        except (ValueError, TypeError, sqlite3.Error) as exc:
            self.errorOccurred.emit(str(exc))
            return ""
        return self.get_spectrum()

    @pyqtSlot(str, result=str)
    def render_markdown(self, source: str) -> str:
        """Render and sanitize Markdown using the application's Phase 1 pipeline."""
        return _render_markdown(source)

    @pyqtSlot(str, result=str)
    def save_image(self, data_url: str) -> str:
        """Validate a pasted image and save a normalized PNG under app data."""
        try:
            header, encoded = data_url.split(",", 1)
            if not header.startswith("data:image/") or ";base64" not in header:
                raise ValueError("Clipboard data is not a supported image.")
            if len(encoded) > 28_000_000:
                raise ValueError("Image exceeds the 20 MB limit.")
            image_data = base64.b64decode(encoded, validate=True)
            image = QImage.fromData(image_data)
            if image.isNull():
                raise ValueError("The image could not be decoded.")
            if image.width() * image.height() > MAX_IMAGE_PIXELS:
                raise ValueError("Image dimensions exceed the supported limit.")
            image_path = self._save_image(image)
        except (ValueError, binascii.Error, OSError) as exc:
            self.errorOccurred.emit(str(exc))
            return ""
        return str(image_path)

    @pyqtSlot(str, str, str)
    def fetch_image(self, image_url: str, source_url: str, request_id: str) -> None:
        """Fetch a webpage image asynchronously and store a local PNG copy."""
        image = QUrl(image_url)
        source = QUrl(source_url)
        if (
            len(request_id) > 100
            or image.scheme().lower() not in {"http", "https"}
            or not image.host()
            or source.scheme().lower() not in {"http", "https"}
        ):
            self.imageFetchFailed.emit(request_id, "The image URL is not supported.")
            return
        if request_id in self._image_replies:
            return

        request = QNetworkRequest(image)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        origin = source.adjusted(
            QUrl.UrlFormattingOption.RemovePath
            | QUrl.UrlFormattingOption.RemoveQuery
            | QUrl.UrlFormattingOption.RemoveFragment
        )
        request.setRawHeader(b"Referer", origin.toEncoded())
        reply = self._network.get(request)
        self._image_replies[request_id] = reply
        timeout = QTimer(reply)
        timeout.setSingleShot(True)
        timeout.timeout.connect(reply.abort)
        timeout.start(IMAGE_FETCH_TIMEOUT_MS)
        reply.downloadProgress.connect(
            lambda received, _total, image_reply=reply:
                image_reply.abort() if received > MAX_IMAGE_BYTES else None
        )
        reply.finished.connect(
            lambda image_reply=reply, key=request_id, original=image.toString():
                self._finish_image_fetch(key, original, image_reply)
        )

    def _finish_image_fetch(
        self, request_id: str, original_url: str, reply: QNetworkReply
    ) -> None:
        """Validate, normalize, and save one completed webpage image request."""
        self._image_replies.pop(request_id, None)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise OSError(reply.errorString())
            image_data = bytes(reply.readAll())
            if not image_data or len(image_data) > MAX_IMAGE_BYTES:
                raise ValueError("The image is empty or exceeds the 20 MB limit.")
            image = QImage.fromData(image_data)
            if image.isNull():
                raise ValueError("The image response could not be decoded.")
            if image.width() * image.height() > MAX_IMAGE_PIXELS:
                raise ValueError("Image dimensions exceed the supported limit.")
            local_path = self._save_image(image)
        except (ValueError, OSError) as exc:
            self.imageFetchFailed.emit(request_id, str(exc))
        else:
            self.imageFetched.emit(request_id, original_url, str(local_path))
        finally:
            reply.deleteLater()

    @staticmethod
    def _save_image(image: QImage) -> Path:
        """Normalize an image to PNG in Prism's managed app-data folder."""
        app_data = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
        )
        image_dir = app_data / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / f"spectrum-{uuid.uuid4().hex}.png"
        if not image.save(str(image_path), "PNG"):
            raise OSError("The image could not be saved to app data.")
        return image_path

    @pyqtSlot(result=str)
    def get_annotations(self) -> str:
        """Return persisted drawing and text-highlight data."""
        try:
            return json.dumps(self.repository.get_annotations(self.spectrum_id))
        except (sqlite3.Error, ValueError) as exc:
            self.errorOccurred.emit(str(exc))
            return ""

    @pyqtSlot(str, result=bool)
    def save_annotations(self, encoded: str) -> bool:
        """Replace the Spectrum's vector drawings and selected-text highlights."""
        try:
            if len(encoded) > 2_000_000:
                raise ValueError("Spectrum annotations exceed the 2 MB limit.")
            annotations = json.loads(encoded)
            if not isinstance(annotations, list) or len(annotations) > 200:
                raise ValueError("Annotations must be a list of at most 200 items.")
            for annotation in annotations:
                self._validate_annotation(annotation)
            self.repository.save_annotations(self.spectrum_id, annotations)
        except (ValueError, TypeError, sqlite3.Error) as exc:
            self.errorOccurred.emit(str(exc))
            return False
        return True

    @staticmethod
    def _validate_annotation(annotation: object) -> None:
        """Bound vector payloads and validate positions before storing them."""
        if not isinstance(annotation, dict):
            raise ValueError("Spectrum annotations must be objects.")
        kind = annotation.get("type")
        if kind == "drawing":
            strokes = annotation.get("strokes")
            if not isinstance(strokes, list) or len(strokes) > 500:
                raise ValueError("Drawing must contain no more than 500 strokes.")
            for stroke in strokes:
                if not isinstance(stroke, dict):
                    raise ValueError("Drawing stroke is invalid.")
                if stroke.get("tool") not in {"pen", "highlighter", "eraser"}:
                    raise ValueError("Drawing tool is invalid.")
                width = stroke.get("width")
                if not isinstance(width, (int, float)) or not 1 <= width <= 24:
                    raise ValueError("Drawing stroke width must be between 1 and 24.")
                color = stroke.get("color")
                if not isinstance(color, str) or not re.fullmatch(
                    r"#[0-9a-fA-F]{6}", color
                ):
                    raise ValueError("Drawing color must be a six-digit hex value.")
                points = stroke.get("points")
                if not isinstance(points, list) or len(points) > 5000:
                    raise ValueError("Stroke point count exceeds the supported limit.")
                for point in points:
                    if not isinstance(point, list) or len(point) != 2:
                        raise ValueError("Drawing point is invalid.")
                    if any(
                        not isinstance(value, (int, float))
                        or not math.isfinite(value)
                        or not 0 <= value <= 1
                        for value in point
                    ):
                        raise ValueError("Drawing points must be normalized to 0–1.")
            return
        if kind == "highlight":
            start = annotation.get("start")
            end = annotation.get("end")
            quote = annotation.get("quote")
            color = annotation.get("color")
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end <= start
                or not isinstance(quote, str)
                or len(quote) > 5000
                or end - start != len(quote)
            ):
                raise ValueError("Text highlight range is invalid.")
            if not isinstance(color, str) or not re.fullmatch(
                r"#[0-9a-fA-F]{6}", color
            ):
                raise ValueError("Text highlight color must be a six-digit hex value.")
            return
        raise ValueError("Unsupported Spectrum annotation type.")

    @pyqtSlot(result=str)
    def get_chat_history(self) -> str:
        """Return chronological chat messages and their saved image paths."""
        try:
            messages = self.repository.list_chat_messages(self.spectrum_id)
        except sqlite3.Error as exc:
            self.errorOccurred.emit(str(exc))
            return ""
        return json.dumps(
            [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "image_paths": message.image_paths,
                    "created_at": message.created_at,
                }
                for message in messages
            ]
        )

    @pyqtSlot(str, str)
    def send_chat(self, content: str, image_paths_json: str) -> None:
        """Forward a user chat turn to the owning browser window."""
        self.chatRequested.emit(content, image_paths_json)

    @pyqtSlot(str, str)
    def insert_into_note(self, content: str, block_id: str) -> None:
        """Ask the editor to insert an assistant response into the note."""
        self.insertRequested.emit(content, block_id)
