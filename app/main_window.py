"""Janela principal."""
from __future__ import annotations

import itertools
import logging
import os
import subprocess
import sys
from pathlib import Path

import shiboken6
import yt_dlp
from PySide6.QtCore import QPoint, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QStackedWidget, QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import audio
from .delegates import (ACTIVE, ROLE_ID, ROLE_KIND, ROLE_PROGRESS, ROLE_STATUS, ROLE_SUB, ROLE_THUMB, STATUS_LABELS,
                        ItemDelegate)
from .dialogs import SelectionDialog, SettingsDialog
from .paths import APP_NAME, APP_VERSION, ASSETS_DIR
from .thumbs import ThumbCache
from .workers import DownloadSignals, DownloadTask, ExtractSignals, ExtractTask, split_urls

log = logging.getLogger("ui")
RESTARTABLE = ("ready", "error", "cancelled", "skipped")
FINAL = ("done", "error", "cancelled", "skipped")
MIX_CHOICES = ["25", "50", "100", "200", "300"]


class MainWindow(QMainWindow):
    def __init__(self, cfg, db, log_bridge):
        super().__init__()
        self.cfg, self.db = cfg, db
        self.setWindowTitle(f"{APP_NAME}")
        self.resize(1040, 700)
        self.setMinimumSize(720, 480)
        self.setAcceptDrops(True)
        icon = ASSETS_DIR / "icon.png"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        # estado
        self.items: dict[int, dict] = {}
        self.nodes: dict[int, QTreeWidgetItem] = {}
        self.tasks: dict[int, DownloadTask] = {}
        self.id_by_video: dict[str, int] = {}
        self.title_key_index: dict[str, list[tuple[int, int]]] = {}
        self.pending: dict[int, QTreeWidgetItem] = {}
        self.req_ctx: dict[int, dict] = {}
        self.extract_tasks: dict[int, ExtractTask] = {}
        self._req = itertools.count(1)
        self.conflict_queue: list[tuple[int, str]] = []
        self.conflict_busy = False
        self.conflict_all: str | None = None
        self.batch_total = self.batch_done = 0

        # infraestrutura de threads
        self.thumbs = ThumbCache(self)
        self.thumbs.updated.connect(lambda: self.tree.viewport().update())
        self.dl_pool = QThreadPool(self)
        self.dl_pool.setMaxThreadCount(cfg["concurrency"])
        self.ex_pool = QThreadPool(self)
        self.ex_pool.setMaxThreadCount(3)
        self.dl_sig = DownloadSignals(self)
        self.ex_sig = ExtractSignals(self)
        self.dl_sig.stage.connect(self._on_stage)
        self.dl_sig.progress.connect(self._on_progress)
        self.dl_sig.finished.connect(self._on_finished)
        self.dl_sig.failed.connect(self._on_failed)
        self.dl_sig.cancelled.connect(self._on_cancelled)
        self.dl_sig.skipped.connect(self._on_skipped)
        self.dl_sig.conflict.connect(self._on_conflict)
        self.dl_sig.log.connect(self._on_task_log)
        self.ex_sig.done.connect(self._on_extract_done)
        self.ex_sig.failed.connect(self._on_extract_failed)

        self._build_ui()
        log_bridge.message.connect(self.log_view.appendPlainText)
        self._load_library()
        self._startup_checks()
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(300)
        self.status_timer.timeout.connect(self._update_status_bar)
        self.status_timer.start()

    # ------------------------------------------------------------------ interface
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 6)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Cole um link do YouTube (vídeo, playlist ou Mix)…")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setToolTip("Pressione Enter para analisar. Você também pode arrastar links para a janela.")
        self.url_edit.returnPressed.connect(self.add_from_input)
        self.fmt_combo = QComboBox()
        for key, f in audio.FORMATS.items():
            self.fmt_combo.addItem(f["label"], key)
        self.fmt_combo.setToolTip("Formato de saída")
        self.q_combo = QComboBox()
        self.q_combo.setToolTip("Qualidade. O YouTube oferece ~128 kbps (AAC) ou até ~160 kbps (Opus): "
                                "valores maiores só aumentam o tamanho.")
        self.add_btn = QPushButton("Baixar")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self.add_from_input)
        self.settings_btn = QToolButton()
        self.settings_btn.setText("⚙")
        self.settings_btn.setToolTip("Configurações")
        self.settings_btn.clicked.connect(self.show_settings)
        top.addWidget(self.url_edit, 1)
        top.addWidget(self.fmt_combo)
        top.addWidget(self.q_combo)
        top.addWidget(self.add_btn)
        top.addWidget(self.settings_btn)
        root.addLayout(top)

        sec = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filtrar…")
        self.filter_edit.setFixedWidth(190)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.folder_btn = QPushButton()
        self.folder_btn.setObjectName("ghost")
        self.folder_btn.clicked.connect(lambda: self._open_dir(Path(self.cfg["download_dir"])))
        sec.addWidget(self.filter_edit)
        sec.addWidget(self.folder_btn)
        sec.addStretch(1)
        for text, slot in (("Baixar selecionados", self.start_selected), ("Cancelar", self.cancel_selected),
                           ("Repetir falhas", self.retry_failed), ("Remover", self.remove_selected),
                           ("Limpar concluídos", self.clear_finished)):
            b = QPushButton(text)
            b.setObjectName("ghost")
            b.clicked.connect(slot)
            sec.addWidget(b)
        root.addLayout(sec)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # aba Downloads: estado vazio / árvore
        self.stack = QStackedWidget()
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(1)
        icon_lb = QLabel("♪")
        icon_lb.setObjectName("emptyIcon")
        icon_lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        txt = QLabel("Nenhum download ainda.\nCole um link acima para converter em áudio.")
        txt.setObjectName("emptyText")
        txt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(icon_lb)
        el.addWidget(txt)
        el.addStretch(2)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Título", "Duração", "Status"])
        self.tree.setItemDelegate(ItemDelegate(self.thumbs, self.tree))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(18)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setMouseTracking(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setStretchLastSection(False)
        self.tree.setColumnWidth(1, 84)
        self.tree.setColumnWidth(2, 150)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree, activated=self.remove_selected)
        self.stack.addWidget(empty)
        self.stack.addWidget(self.tree)
        self.tabs.addTab(self.stack, "Downloads")

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.tabs.addTab(self.log_view, "Logs")
        self.setCentralWidget(central)

        sb = self.statusBar()
        self.sb_label = QLabel("Pronto")
        self.sb_bar = QProgressBar()
        self.sb_bar.setFixedWidth(220)
        self.sb_bar.setRange(0, 1000)
        self.sb_bar.setVisible(False)
        self.sb_ver = QLabel()
        sb.addWidget(self.sb_label, 1)
        sb.addPermanentWidget(self.sb_bar)
        sb.addPermanentWidget(self.sb_ver)

        self.fmt_combo.blockSignals(True)
        self.fmt_combo.setCurrentIndex(max(0, self.fmt_combo.findData(self.cfg["format"])))
        self.fmt_combo.blockSignals(False)
        self._fill_top_quality(self.cfg["quality"])
        self.fmt_combo.currentIndexChanged.connect(lambda _: self._top_format_changed())
        self.q_combo.currentIndexChanged.connect(lambda _: self._top_quality_changed())
        self._refresh_header_labels()

    def _startup_checks(self) -> None:
        log.info("%s %s iniciado · yt-dlp %s", APP_NAME, APP_VERSION, yt_dlp.version.__version__)
        ff = audio.find_ffmpeg()
        js, desc = audio.find_js_runtimes(self.cfg.data)
        if not ff:
            log.error("FFmpeg não encontrado: a conversão não vai funcionar (pip install imageio-ffmpeg).")
        else:
            log.info("FFmpeg: %s", ff)
        if js:
            log.info("Runtime JavaScript: %s", desc)
        else:
            log.warning("Nenhum runtime JavaScript (Deno) encontrado: o YouTube pode falhar. "
                        "Instale com 'winget install DenoLand.Deno' ou rode setup.bat.")

    def _refresh_header_labels(self) -> None:
        _, desc = audio.find_js_runtimes(self.cfg.data)
        self.sb_ver.setText(f"yt-dlp {yt_dlp.version.__version__}  ·  JS: {desc or 'ausente ⚠'}")
        d = Path(self.cfg["download_dir"])
        self.folder_btn.setText("📁  " + (os.sep.join(d.parts[-2:]) if len(d.parts) > 1 else str(d)))
        self.folder_btn.setToolTip(f"Abrir a pasta de destino\n{d}")

    # ---- formato/qualidade na barra superior
    def _fill_top_quality(self, current: str) -> None:
        fmt = self.fmt_combo.currentData()
        self.q_combo.blockSignals(True)
        self.q_combo.clear()
        for value, label in audio.quality_options(fmt):
            self.q_combo.addItem(label, value)
        self.q_combo.setCurrentIndex(max(0, self.q_combo.findData(audio.normalize_quality(fmt, current))))
        self.q_combo.setEnabled(self.q_combo.count() > 1)
        self.q_combo.blockSignals(False)

    def _top_format_changed(self) -> None:
        self._fill_top_quality(self.cfg["quality"])
        self.cfg["format"] = self.fmt_combo.currentData()
        self.cfg["quality"] = self.q_combo.currentData() or ""
        self.cfg.save()

    def _top_quality_changed(self) -> None:
        self.cfg["quality"] = self.q_combo.currentData() or ""
        self.cfg.save()

    def show_settings(self) -> None:
        if SettingsDialog(self.cfg, self).exec():
            self.dl_pool.setMaxThreadCount(self.cfg["concurrency"])
            self.fmt_combo.blockSignals(True)
            self.fmt_combo.setCurrentIndex(max(0, self.fmt_combo.findData(self.cfg["format"])))
            self.fmt_combo.blockSignals(False)
            self._fill_top_quality(self.cfg["quality"])
            self._refresh_header_labels()

    # ------------------------------------------------------------------ biblioteca (DB -> UI)
    def _load_library(self) -> None:
        rows = self.db.all_rows()
        for r in (x for x in rows if x["kind"] == "group"):
            it = self._item_from_row(r)
            self._register(it)
            self._make_node(it)
        for r in (x for x in rows if x["kind"] == "video"):
            it = self._item_from_row(r)
            self._register(it)
            self._make_node(it, self.nodes.get(it["parent_id"]) if it["parent_id"] else None)
        for it in list(self.items.values()):
            if it["kind"] == "group":
                self._refresh_node(it["id"])
        self.tree.expandAll()
        self._update_empty_state()

    @staticmethod
    def _item_from_row(r) -> dict:
        return {"id": r["id"], "parent_id": r["parent_id"], "kind": r["kind"], "group_kind": r["group_kind"],
                "group_ref": r["group_ref"], "video_id": r["video_id"], "title": r["title"], "channel": r["channel"],
                "duration": r["duration"], "url": r["url"], "thumb": r["thumb"], "index": r["position"],
                "status": r["status"] or "", "output_path": r["output_path"], "error": r["error"],
                "progress": 100.0 if r["status"] == "done" else 0.0, "sub": "", "status_text": ""}

    def _register(self, it: dict) -> None:
        self.items[it["id"]] = it
        if it["kind"] == "video":
            if it["video_id"]:
                self.id_by_video[it["video_id"]] = it["id"]
            self.title_key_index.setdefault(audio.norm_title(it["title"]), []).append((it["id"], it["duration"]))

    def _unregister(self, it: dict) -> None:
        self.items.pop(it["id"], None)
        if it["kind"] == "video":
            if self.id_by_video.get(it["video_id"]) == it["id"]:
                self.id_by_video.pop(it["video_id"], None)
            key = audio.norm_title(it["title"])
            lst = [x for x in self.title_key_index.get(key, []) if x[0] != it["id"]]
            if lst:
                self.title_key_index[key] = lst
            else:
                self.title_key_index.pop(key, None)

    def _is_dup(self, e: dict) -> bool:
        """Mesmo ID de vídeo, ou mesmo título normalizado com duração a ±3 s."""
        if e.get("video_id") in self.id_by_video:
            return True
        for _iid, dur in self.title_key_index.get(audio.norm_title(e["title"]), []):
            if not dur or not e.get("duration") or abs(dur - e["duration"]) <= 3:
                return True
        return False

    # ------------------------------------------------------------------ nós da árvore
    def _make_node(self, it: dict, parent: QTreeWidgetItem | None = None) -> QTreeWidgetItem:
        node = QTreeWidgetItem()
        node.setData(0, ROLE_ID, it["id"])
        for col in (0, 2):
            node.setData(col, ROLE_KIND, it["kind"])
        node.setData(0, ROLE_THUMB, it["thumb"])
        self.nodes[it["id"]] = node
        if parent is None:
            self.tree.addTopLevelItem(node)
        else:
            n = parent.childCount()
            if n and parent.child(n - 1).data(0, ROLE_KIND) == "more":
                parent.insertChild(n - 1, node)
            else:
                parent.addChild(node)
        if it["kind"] == "group" and it["group_kind"] == "mix":
            self._add_more_node(node, it["id"])
        self._refresh_node(it["id"])
        return node

    def _add_more_node(self, group_node: QTreeWidgetItem, gid: int) -> None:
        more = QTreeWidgetItem(group_node)
        more.setData(0, ROLE_ID, gid)
        more.setData(0, ROLE_KIND, "more")
        more.setText(0, "♪ Carregar mais…")
        more.setData(0, ROLE_SUB, "Clique duplo para buscar mais faixas deste Mix")

    def _more_node(self, gid: int) -> QTreeWidgetItem | None:
        g = self.nodes.get(gid)
        if g and g.childCount() and g.child(g.childCount() - 1).data(0, ROLE_KIND) == "more":
            return g.child(g.childCount() - 1)
        return None

    def _children_ids(self, gid: int) -> list[int]:
        return [i["id"] for i in self.items.values() if i.get("parent_id") == gid]

    def _refresh_node(self, iid: int) -> None:
        it, node = self.items.get(iid), self.nodes.get(iid)
        if not it or not node:
            return
        node.setText(0, it["title"])
        if it["kind"] == "group":
            kids = [self.items[k] for k in self._children_ids(iid)]
            done = sum(1 for k in kids if k["status"] == "done")
            node.setData(0, ROLE_SUB, f"{len(kids)} faixa(s)" + (" · Mix" if it["group_kind"] == "mix" else ""))
            node.setText(2, f"{done}/{len(kids)}")
            return
        parts = [it["channel"], audio.fmt_duration(it["duration"])]
        node.setData(0, ROLE_SUB, it["sub"] or " · ".join(p for p in parts if p))
        node.setData(0, ROLE_STATUS, it["status"])
        node.setData(2, ROLE_STATUS, it["status"])
        node.setData(0, ROLE_PROGRESS, it["progress"])
        node.setText(1, audio.fmt_duration(it["duration"]))
        node.setText(2, it["status_text"] or STATUS_LABELS.get(it["status"], it["status"]))
        node.setToolTip(2, it["error"] or it["output_path"] or "")

    def _refresh_group_of(self, iid: int) -> None:
        pid = self.items.get(iid, {}).get("parent_id")
        if pid:
            self._refresh_node(pid)

    def _update_empty_state(self) -> None:
        self.stack.setCurrentIndex(1 if (self.tree.topLevelItemCount() or self.pending) else 0)

    def _apply_filter(self, text: str) -> None:
        q = audio.norm_title(text)

        def match(it: dict) -> bool:
            return not q or q in audio.norm_title(it["title"] + it.get("channel", ""))

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            kind = top.data(0, ROLE_KIND)
            if kind == "group":
                any_vis = False
                for j in range(top.childCount()):
                    ch = top.child(j)
                    if ch.data(0, ROLE_KIND) == "more":
                        ch.setHidden(bool(q))
                        continue
                    vis = match(self.items[ch.data(0, ROLE_ID)])
                    ch.setHidden(not vis)
                    any_vis = any_vis or vis
                top.setHidden(bool(q) and not any_vis and not match(self.items[top.data(0, ROLE_ID)]))
            elif kind == "video":
                top.setHidden(not match(self.items[top.data(0, ROLE_ID)]))

    # ------------------------------------------------------------------ adicionar links
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        md = e.mimeData()
        text = " ".join([u.toString() for u in md.urls()] + [md.text()])
        self._analyze_text(text)
        e.acceptProposedAction()

    def add_from_input(self) -> None:
        text = self.url_edit.text()
        if not text.strip():
            clip = QGuiApplication.clipboard().text()
            if split_urls(clip):
                text = clip
        if self._analyze_text(text):
            self.url_edit.clear()
        else:
            QMessageBox.information(self, APP_NAME, "Cole um link do YouTube (vídeo, playlist ou Mix).")

    def _analyze_text(self, text: str) -> bool:
        urls = split_urls(text)
        for u in urls:
            self.start_extract(u)
        return bool(urls)

    def start_extract(self, url: str, mode: str = "auto", limit: int = 0, ctx: dict | None = None) -> None:
        rid = next(self._req)
        self.req_ctx[rid] = ctx or {}
        if mode == "auto":
            ph = QTreeWidgetItem()
            ph.setData(0, ROLE_KIND, "pending")
            ph.setText(0, f"⏳ Analisando… {url}")
            ph.setData(2, ROLE_KIND, "pending")
            self.tree.insertTopLevelItem(0, ph)
            self.pending[rid] = ph
            self._update_empty_state()
        task = ExtractTask(rid, url, self.cfg.snapshot(), self.ex_sig, mode, limit)
        self.extract_tasks[rid] = task
        self.ex_pool.start(task)

    def _drop_pending(self, rid: int) -> None:
        ph = self.pending.pop(rid, None)
        if ph is not None:
            idx = self.tree.indexOfTopLevelItem(ph)
            if idx >= 0:
                self.tree.takeTopLevelItem(idx)
        self.extract_tasks.pop(rid, None)
        self._update_empty_state()

    def _on_extract_failed(self, rid: int, msg: str) -> None:
        ctx = self.req_ctx.pop(rid, {})
        self._drop_pending(rid)
        if ctx.get("mode") == "mix_more":
            self._reset_more(ctx["group_id"])
        log.error("Falha ao analisar o link: %s", msg)
        QMessageBox.warning(self, APP_NAME, msg)

    def _reset_more(self, gid: int) -> None:
        more = self._more_node(gid)
        if more:
            more.setText(0, "♪ Carregar mais…")

    def _on_extract_done(self, rid: int, result: dict) -> None:
        ctx = self.req_ctx.pop(rid, {})
        self._drop_pending(rid)
        entries = result["entries"]
        if ctx.get("mode") == "mix_more":
            gid = ctx["group_id"]
            self._reset_more(gid)
            new = [e for e in entries if not self._is_dup(e)]
            if not new:
                QMessageBox.information(self, APP_NAME, "Nenhuma faixa nova encontrada neste Mix.")
                return
            dlg = SelectionDialog(self.items[gid]["title"],
                                  f"{len(new)} faixas novas ({len(entries) - len(new)} já estavam na lista)", new, self)
            if dlg.exec():
                added, _ = self._add_entries(dlg.selected(), gid)
                self._after_add(added)
            return

        kind = result["kind"]
        if not entries:
            QMessageBox.information(self, APP_NAME, "Nenhum vídeo disponível neste link.")
            return
        if kind == "video":
            added, skipped = self._add_entries(entries, None)
        elif kind == "mix":
            gid = self._new_group(result["title"], "mix", result["url"])
            added, skipped = self._add_entries(entries, gid)
            if not added:
                self._remove_ids([gid])
        else:
            dlg = SelectionDialog(result["title"], f"{len(entries)} itens na playlist", entries, self)
            if not dlg.exec():
                return
            gid = self._new_group(result["title"], "playlist", result["url"])
            added, skipped = self._add_entries(dlg.selected(), gid)
            if not added:
                self._remove_ids([gid])
        if skipped:
            msg = f"{skipped} item(ns) já estavam na lista e foram ignorados."
            log.info(msg)
            self.sb_label.setText(msg)
            if not added:
                QMessageBox.information(self, APP_NAME, "Este conteúdo já está na lista.")
        self._after_add(added)

    def _new_group(self, title: str, kind: str, ref: str) -> int:
        gid = self.db.add_group(title, kind, ref)
        it = {"id": gid, "parent_id": None, "kind": "group", "group_kind": kind, "group_ref": ref, "video_id": "",
              "title": title, "channel": "", "duration": 0, "url": "", "thumb": "", "index": 0, "status": "",
              "output_path": "", "error": "", "progress": 0.0, "sub": "", "status_text": ""}
        self._register(it)
        node = self._make_node(it)
        node.setExpanded(True)
        return gid

    def _add_entries(self, entries: list[dict], gid: int | None) -> tuple[list[int], int]:
        added: list[int] = []
        skipped = 0
        parent = self.nodes.get(gid) if gid else None
        with self.db.transaction():
            for e in entries:
                if self._is_dup(e):
                    skipped += 1
                    continue
                iid = self.db.add_video(e, gid)
                it = {"id": iid, "parent_id": gid, "kind": "video", "group_kind": "", "group_ref": "",
                      "video_id": e["video_id"], "title": e["title"], "channel": e.get("channel", ""),
                      "duration": e.get("duration", 0), "url": e["url"], "thumb": e.get("thumb", ""),
                      "index": e.get("index", 0), "status": "ready", "output_path": "", "error": "",
                      "progress": 0.0, "sub": "", "status_text": ""}
                self._register(it)
                self._make_node(it, parent)
                added.append(iid)
        if gid:
            self._refresh_node(gid)
        return added, skipped

    def _after_add(self, added: list[int]) -> None:
        self._update_empty_state()
        if added and self.cfg["auto_start"]:
            self.enqueue(added)

    # ------------------------------------------------------------------ fila de downloads
    def _task_item(self, it: dict) -> dict:
        parent = self.items.get(it["parent_id"]) if it.get("parent_id") else None
        total = max([self.items[k]["index"] for k in self._children_ids(parent["id"])] or [0]) if parent else 0
        return {"id": it["id"], "url": it["url"], "video_id": it["video_id"], "title": it["title"],
                "channel": it["channel"], "duration": it["duration"], "index": it["index"],
                "group_title": parent["title"] if parent else "", "group_kind": parent["group_kind"] if parent else "",
                "group_total": total}

    def enqueue(self, ids: list[int]) -> None:
        if not audio.find_ffmpeg():
            QMessageBox.critical(self, APP_NAME, "FFmpeg não encontrado. Instale com: pip install imageio-ffmpeg")
            return
        for iid in ids:
            it = self.items.get(iid)
            if not it or it["kind"] != "video" or it["status"] in ACTIVE:
                continue
            if not self._active_ids():
                self.batch_total = self.batch_done = 0
            it.update(status="queued", progress=0.0, error="", sub="", status_text="")
            task = DownloadTask(self._task_item(it), self.cfg.snapshot(), self.dl_sig)
            self.tasks[iid] = task
            self.dl_pool.start(task)
            self.batch_total += 1
            self._refresh_node(iid)

    def _active_ids(self) -> list[int]:
        return [i for i, it in self.items.items() if it["status"] in ACTIVE]

    def _terminal(self, iid: int, status: str, output_path: str = "", error: str = "", text: str = "") -> None:
        it = self.items.get(iid)
        self.tasks.pop(iid, None)
        if not it:
            return
        it.update(status=status, output_path=output_path, error=error, status_text=text, sub="",
                  progress=100.0 if status == "done" else 0.0)
        self.db.set_status(iid, status, output_path, error)
        self.batch_done += 1
        self._refresh_node(iid)
        self._refresh_group_of(iid)

    # --- signals dos workers
    def _on_stage(self, iid: int, key: str, text: str) -> None:
        it = self.items.get(iid)
        if it and it["status"] in ACTIVE:
            it["status"], it["status_text"] = key, text
            self._refresh_node(iid)

    def _on_progress(self, iid: int, pct: float, detail: str) -> None:
        it = self.items.get(iid)
        if it and it["status"] in ACTIVE:
            it["progress"] = pct
            it["sub"] = detail
            node = self.nodes.get(iid)
            if node:
                node.setData(0, ROLE_PROGRESS, pct)
                node.setData(0, ROLE_SUB, detail or " · ".join(
                    p for p in (it["channel"], audio.fmt_duration(it["duration"])) if p))
                if it["status"] == "downloading" and it["status_text"] in ("Baixando", ""):
                    node.setText(2, f"Baixando {pct / 0.9:.0f}%" if pct < 90 else "Baixando")
            self.tree.viewport().update()

    def _on_finished(self, iid: int, path: str) -> None:
        it = self.items.get(iid)
        if it:
            self.db.add_history(it["video_id"], it["title"], self.cfg["format"], self.cfg["quality"], path)
        self._terminal(iid, "done", output_path=path)
        log.info("Concluído: %s", path)

    def _on_failed(self, iid: int, msg: str) -> None:
        self._terminal(iid, "error", error=msg)
        log.error("[%s] %s", self.items.get(iid, {}).get("title", iid), msg)

    def _on_cancelled(self, iid: int) -> None:
        self._terminal(iid, "cancelled")

    def _on_skipped(self, iid: int, path: str) -> None:
        self._terminal(iid, "skipped", output_path=path)

    def _on_task_log(self, iid: int, level: str, msg: str) -> None:
        title = (self.items.get(iid, {}).get("title") or str(iid))[:40]
        lv = {"warn": logging.WARNING, "error": logging.ERROR}.get(level, logging.INFO)
        log.log(lv, "[%s] %s", title, msg)

    # --- conflitos de arquivo (o worker aguarda a resposta)
    def _on_conflict(self, iid: int, path: str) -> None:
        task = self.tasks.get(iid)
        if task is None:
            return
        if self.conflict_all:
            task.resolve_conflict(self.conflict_all)
            return
        self.conflict_queue.append((iid, path))
        QTimer.singleShot(0, self._next_conflict)

    def _next_conflict(self) -> None:
        if self.conflict_busy or not self.conflict_queue:
            return
        self.conflict_busy = True
        iid, path = self.conflict_queue.pop(0)
        task = self.tasks.get(iid)
        if task is not None and not task.cancel_event.is_set():
            choice, apply_all = self._ask_conflict(path)
            if apply_all:
                self.conflict_all = choice
            task.resolve_conflict(choice)
        self.conflict_busy = False
        QTimer.singleShot(0, self._next_conflict)

    def _ask_conflict(self, path: str) -> tuple[str, bool]:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Arquivo já existe")
        box.setText(f"Já existe um arquivo com este nome:\n\n{Path(path).name}")
        replace = box.addButton("Substituir", QMessageBox.ButtonRole.DestructiveRole)
        rename = box.addButton("Renomear", QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("Pular", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(rename)
        box.setEscapeButton(skip)
        chk = QCheckBox("Aplicar a todos os próximos conflitos")
        box.setCheckBox(chk)
        box.exec()
        clicked = box.clickedButton()
        choice = "replace" if clicked is replace else "rename" if clicked is rename else "skip"
        return choice, chk.isChecked()

    # ------------------------------------------------------------------ ações
    def _selected_video_ids(self) -> list[int]:
        ids: list[int] = []
        for node in self.tree.selectedItems():
            kind = node.data(0, ROLE_KIND)
            iid = node.data(0, ROLE_ID)
            if kind == "video":
                ids.append(iid)
            elif kind == "group":
                ids += self._children_ids(iid)
        return list(dict.fromkeys(ids))

    def start_selected(self) -> None:
        ids = [i for i in self._selected_video_ids() if self.items[i]["status"] in RESTARTABLE]
        if not ids and not self.tree.selectedItems():
            ids = [i for i, it in self.items.items() if it["kind"] == "video" and it["status"] in RESTARTABLE]
        self.enqueue(ids)

    def retry_failed(self) -> None:
        self.enqueue([i for i, it in self.items.items() if it["status"] in ("error", "cancelled")])

    def _cancel_item(self, iid: int) -> None:
        task = self.tasks.get(iid)
        if task is None:
            return
        if self.dl_pool.tryTake(task):  # ainda não começou: remove da fila direto
            self._terminal(iid, "cancelled")
        else:
            task.cancel()

    def cancel_selected(self) -> None:
        ids = self._selected_video_ids() or self._active_ids()
        for iid in ids:
            if self.items.get(iid, {}).get("status") in ACTIVE:
                self._cancel_item(iid)

    def remove_selected(self) -> None:
        ids = []
        for node in self.tree.selectedItems():
            kind = node.data(0, ROLE_KIND)
            if kind in ("video", "group"):
                ids.append(node.data(0, ROLE_ID))
        self._remove_ids(ids)

    def clear_finished(self) -> None:
        self._remove_ids([i for i, it in self.items.items() if it["kind"] == "video" and it["status"] in ("done", "skipped")])

    def _remove_ids(self, ids: list[int]) -> None:
        """Remove da árvore, dos índices em memória e do banco (que apaga os filhos em cascata)."""
        victims: list[int] = []
        for iid in ids:
            it = self.items.get(iid)
            if not it:
                continue
            victims.append(iid)
            if it["kind"] == "group":
                victims += self._children_ids(iid)
        victims = list(dict.fromkeys(victims))
        parents = {self.items[v]["parent_id"] for v in victims if v in self.items and self.items[v].get("parent_id")}
        for iid in reversed(victims):  # filhos antes do grupo (remover o grupo destrói os nós filhos)
            it = self.items.get(iid)
            if not it:
                continue
            if iid in self.tasks:
                self._cancel_item(iid)
                self.tasks.pop(iid, None)
            node = self.nodes.pop(iid, None)
            if node is not None and shiboken6.isValid(node):
                par = node.parent()
                if par is not None:
                    par.removeChild(node)
                else:
                    idx = self.tree.indexOfTopLevelItem(node)
                    if idx >= 0:
                        self.tree.takeTopLevelItem(idx)
            self._unregister(it)
        with self.db.transaction():
            for iid in victims:
                self.db.delete(iid)
        for pid in parents:  # grupos que ficaram vazios somem junto
            if pid in self.items and not self._children_ids(pid):
                self._remove_ids([pid])
            elif pid in self.items:
                self._refresh_node(pid)
        self._update_empty_state()

    def _on_double_click(self, node: QTreeWidgetItem, _col: int) -> None:
        kind = node.data(0, ROLE_KIND)
        iid = node.data(0, ROLE_ID)
        if kind == "more":
            self._mix_more(iid)
        elif kind == "video":
            it = self.items[iid]
            if it["status"] == "done" and it["output_path"]:
                self._open_file(Path(it["output_path"]))
            elif it["status"] in RESTARTABLE:
                self.enqueue([iid])
        elif kind == "group":
            node.setExpanded(not node.isExpanded())

    def _mix_more(self, gid: int) -> None:
        g = self.items[gid]
        n, ok = QInputDialog.getItem(self, "Carregar mais", "Quantas faixas novas buscar?", MIX_CHOICES, 1, False)
        if not ok:
            return
        more = self._more_node(gid)
        if more:
            more.setText(0, "⏳ Carregando…")
        have = len(self._children_ids(gid))
        self.start_extract(g["group_ref"], mode="mix_more", limit=have + int(n),
                           ctx={"mode": "mix_more", "group_id": gid})

    def _context_menu(self, pos: QPoint) -> None:
        node = self.tree.itemAt(pos)
        if node is None or node.data(0, ROLE_KIND) in ("pending",):
            return
        if not node.isSelected():
            self.tree.clearSelection()
            node.setSelected(True)
        menu = QMenu(self)
        acts: dict[QAction, callable] = {}

        def add(text: str, fn) -> None:
            acts[menu.addAction(text)] = fn

        ids = self._selected_video_ids()
        if any(self.items[i]["status"] in RESTARTABLE for i in ids):
            add("Baixar", lambda: self.enqueue([i for i in ids if self.items[i]["status"] in RESTARTABLE]))
        if any(self.items[i]["status"] in ACTIVE for i in ids):
            add("Cancelar", self.cancel_selected)
        if len(ids) == 1:
            it = self.items[ids[0]]
            if it["status"] == "done" and it["output_path"]:
                add("Abrir arquivo", lambda: self._open_file(Path(it["output_path"])))
                add("Mostrar na pasta", lambda: self._show_in_folder(Path(it["output_path"])))
            add("Copiar link", lambda: QGuiApplication.clipboard().setText(it["url"]))
            if it["error"]:
                add("Copiar mensagem de erro", lambda: QGuiApplication.clipboard().setText(it["error"]))
        menu.addSeparator()
        add("Remover da lista", self.remove_selected)
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen in acts:
            acts[chosen]()

    # ------------------------------------------------------------------ arquivos/pastas
    def _open_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_file(self, path: Path) -> None:
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(self, APP_NAME, "O arquivo não existe mais nesse local.")

    def _show_in_folder(self, path: Path) -> None:
        if sys.platform == "win32" and path.exists():
            subprocess.Popen(["explorer", f"/select,{path}"])
        else:
            self._open_dir(path.parent)

    # ------------------------------------------------------------------ barra de status
    def _update_status_bar(self) -> None:
        active = [it for it in self.items.values() if it["status"] in ACTIVE]
        if not active:
            self.batch_total = self.batch_done = 0
            self.conflict_all = None
            self.sb_bar.setVisible(False)
            if not self.sb_label.text().startswith(("Pronto", "Concluído")) and "ignorados" not in self.sb_label.text():
                self.sb_label.setText("Pronto")
            return
        running = sum(1 for it in active if it["status"] in ("downloading", "converting"))
        queued = len(active) - running
        frac = sum(it["progress"] for it in active) / 100.0
        total = max(self.batch_total, 1)
        self.sb_bar.setVisible(True)
        self.sb_bar.setValue(int(min(1.0, (self.batch_done + frac) / total) * 1000))
        self.sb_label.setText(f"{running} em andamento · {queued} na fila · {self.batch_done}/{self.batch_total} concluídos")

    # ------------------------------------------------------------------ encerramento
    def closeEvent(self, event) -> None:
        if self._active_ids():
            ans = QMessageBox.question(self, APP_NAME, "Há downloads em andamento. Cancelar tudo e sair?")
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.status_timer.stop()
        for task in list(self.tasks.values()):
            task.cancel()
        self.dl_pool.clear()
        self.ex_pool.clear()
        self.dl_pool.waitForDone(6000)
        self.ex_pool.waitForDone(2000)
        self.thumbs.shutdown()
        self.cfg.save()
        self.db.close()
        super().closeEvent(event)
