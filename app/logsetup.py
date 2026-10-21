"""Configuração de logs: arquivo rotativo + ponte (signal) para a aba Logs."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QObject, Signal

from .paths import DATA_DIR, LOG_PATH


class QtLogBridge(QObject):
    message = Signal(str)


class _BridgeHandler(logging.Handler):
    def __init__(self, bridge: QtLogBridge):
        super().__init__(logging.INFO)
        self.bridge = bridge
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.message.emit(self.format(record))
        except RuntimeError:  # objeto Qt já destruído (encerrando o app)
            pass


def setup_logging() -> QtLogBridge:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(fh)
    bridge = QtLogBridge()
    root.addHandler(_BridgeHandler(bridge))
    return bridge
