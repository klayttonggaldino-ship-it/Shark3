"""Carregamento assíncrono de miniaturas.

Se a janela/objeto já foi destruído quando a imagem chega, não emitimos o signal
(shiboken6.isValid) — emitir em objeto destruído causava crash silencioso (P-02).
"""
from __future__ import annotations

import urllib.request

import shiboken6
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap


class _ThumbSignals(QObject):
    loaded = Signal(str, QImage)


class _ThumbTask(QRunnable):
    def __init__(self, url: str, signals: _ThumbSignals):
        super().__init__()
        self.setAutoDelete(False)
        self.url, self.signals = url, signals

    def run(self) -> None:
        image = QImage()
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                image.loadFromData(resp.read(2_000_000))
        except Exception:  # noqa: BLE001 - miniatura é opcional
            pass
        if shiboken6.isValid(self.signals):
            self.signals.loaded.emit(self.url, image)


class ThumbCache(QObject):
    updated = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._pix: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._tasks: set[_ThumbTask] = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self._signals = _ThumbSignals(self)
        self._signals.loaded.connect(self._on_loaded)

    def get(self, url: str) -> QPixmap | None:
        if not url:
            return None
        pm = self._pix.get(url)
        if pm is None and url not in self._pending and url not in self._failed:
            self._pending.add(url)
            task = _ThumbTask(url, self._signals)
            self._tasks.add(task)
            self._pool.start(task)
        return pm

    def _on_loaded(self, url: str, image: QImage) -> None:
        self._pending.discard(url)
        self._tasks = {t for t in self._tasks if t.url != url}
        if image.isNull():
            self._failed.add(url)
            return
        self._pix[url] = QPixmap.fromImage(image).scaled(
            128, 72, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        self.updated.emit()

    def shutdown(self) -> None:
        self._pool.clear()
        self._pool.waitForDone(2000)
