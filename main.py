"""Shark3 — ponto de entrada."""
import os
import sys
import threading
import time
import traceback


def _ensure_stdio() -> None:
    # No EXE sem console (PyInstaller --noconsole) stdout/stderr são None e quebram bibliotecas.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


_ensure_stdio()

from PySide6.QtCore import QLockFile  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import theme  # noqa: E402
from app.config import Config  # noqa: E402
from app.database import Database  # noqa: E402
from app.logsetup import setup_logging  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from app.paths import APP_NAME, ASSETS_DIR, DATA_DIR, DB_PATH, LOG_PATH, TMP_DIR  # noqa: E402


def _install_excepthooks(log) -> None:
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Erro não tratado:\n%s", text)
        try:
            QMessageBox.critical(None, APP_NAME, f"Ocorreu um erro inesperado:\n\n{exc}\n\nDetalhes em:\n{LOG_PATH}")
        except Exception:  # noqa: BLE001
            pass

    def thread_hook(args):
        text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        log.error("Erro em thread:\n%s", text)

    sys.excepthook = hook
    threading.excepthook = thread_hook


def _purge_tmp() -> None:
    """Remove restos de downloads interrompidos (mais de 1 dia)."""
    limit = time.time() - 86400
    if TMP_DIR.exists():
        for p in TMP_DIR.iterdir():
            try:
                if p.is_file() and p.stat().st_mtime < limit:
                    p.unlink()
            except OSError:
                pass


def main() -> int:
    if sys.platform == "win32":
        try:  # ícone correto na barra de tarefas
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.Desktop")
        except Exception:  # noqa: BLE001
            pass

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon = ASSETS_DIR / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    bridge = setup_logging()
    import logging

    _install_excepthooks(logging.getLogger("main"))

    lock = QLockFile(str(DATA_DIR / "app.lock"))  # evita abrir duas instâncias
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} já está em execução.")
        return 0

    theme.install(app)
    _purge_tmp()
    cfg = Config()
    db = Database(DB_PATH)
    win = MainWindow(cfg, db, bridge)
    win.show()
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
