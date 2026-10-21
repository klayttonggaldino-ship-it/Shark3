"""Diálogos: SelectionDialog (escolher faixas) e SettingsDialog (configurações)."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QPushButton, QScrollArea, QSpinBox,
                               QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import audio
from .eq_widget import EqPanel
from .paths import DATA_DIR


# ----------------------------------------------------------------------------- seleção de faixas
class SelectionDialog(QDialog):
    def __init__(self, title: str, subtitle: str, entries: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Selecionar faixas")
        screen = self.screen().availableGeometry() if self.screen() else None
        w, h = (min(820, int(screen.width() * 0.92)), min(640, int(screen.height() * 0.85))) if screen else (820, 640)
        self.resize(w, h)
        self.entries = entries

        lay = QVBoxLayout(self)
        head = QLabel(title)
        head.setObjectName("title")
        head.setWordWrap(True)
        lay.addWidget(head)
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        lay.addWidget(sub)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Título", "Canal", "Duração"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setColumnWidth(1, 180)
        for i, e in enumerate(entries):
            it = QTreeWidgetItem([f"{e.get('index') or i + 1}. {e['title']}", e.get("channel", ""),
                                  audio.fmt_duration(e.get("duration"))])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked)
            it.setData(0, Qt.ItemDataRole.UserRole, i)
            self.tree.addTopLevelItem(it)
        self.tree.itemChanged.connect(lambda *_: self._count())
        lay.addWidget(self.tree, 1)

        row = QHBoxLayout()
        all_btn, none_btn = QPushButton("Marcar todas"), QPushButton("Desmarcar todas")
        all_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        none_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        self.counter = QLabel()
        self.counter.setObjectName("muted")
        row.addWidget(all_btn)
        row.addWidget(none_btn)
        row.addStretch(1)
        row.addWidget(self.counter)
        lay.addLayout(row)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setObjectName("primary")
        self.ok_btn.setText("Adicionar à lista")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self._count()

    def _set_all(self, state: Qt.CheckState) -> None:
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, state)
        self.tree.blockSignals(False)
        self._count()

    def _count(self) -> None:
        n = len(self.selected())
        self.counter.setText(f"{n} de {self.tree.topLevelItemCount()} selecionadas")
        self.ok_btn.setEnabled(n > 0)

    def selected(self) -> list[dict]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.checkState(0) == Qt.CheckState.Checked:
                out.append(self.entries[it.data(0, Qt.ItemDataRole.UserRole)])
        return out


# ----------------------------------------------------------------------------- configurações
BROWSERS = [("", "Nenhum"), ("chrome", "Chrome"), ("edge", "Edge"), ("firefox", "Firefox"), ("brave", "Brave"),
            ("opera", "Opera"), ("vivaldi", "Vivaldi"), ("chromium", "Chromium")]


def _page() -> tuple[QScrollArea, QFormLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    host = QWidget()
    form = QFormLayout(host)
    form.setContentsMargins(18, 16, 18, 16)
    form.setVerticalSpacing(12)
    form.setHorizontalSpacing(16)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    area.setWidget(host)
    return area, form


def _hint(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("hint")
    lb.setWordWrap(True)
    return lb


def _combo(items: list[tuple[str, str]], current: str) -> QComboBox:
    cb = QComboBox()
    for value, label in items:
        cb.addItem(label, value)
    cb.setCurrentIndex(max(0, cb.findData(current)))
    return cb


class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Configurações")
        scr = self.screen().availableGeometry() if self.screen() else None
        self.resize(*( (min(920, int(scr.width() * 0.92)), min(660, int(scr.height() * 0.88))) if scr else (920, 660) ))
        self.setMinimumSize(520, 380)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(178)
        self.stack = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        # botões ficam fora da área rolável: nunca são cobertos em telas pequenas
        bar = QHBoxLayout()
        bar.setContentsMargins(16, 10, 16, 12)
        bar.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setObjectName("primary")
        save.setText("Salvar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        bar.addWidget(buttons)
        root.addLayout(bar)

        for name, builder in (("Geral", self._general), ("Download", self._download), ("Organização", self._organize),
                              ("Áudio / EQ", self._audio), ("Avançado", self._advanced)):
            self.nav.addItem(name)
            self.stack.addWidget(builder())
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

    # --- páginas
    def _general(self) -> QWidget:
        area, form = _page()
        self.dir_edit = QLineEdit(self.cfg["download_dir"])
        browse = QPushButton("Procurar…")
        browse.clicked.connect(lambda: self._pick_dir(self.dir_edit))
        row = QHBoxLayout()
        row.addWidget(self.dir_edit, 1)
        row.addWidget(browse)
        form.addRow("Pasta de destino", row)
        self.auto_start = QCheckBox("Começar a baixar assim que o link for analisado")
        self.auto_start.setChecked(self.cfg["auto_start"])
        form.addRow("", self.auto_start)
        return area

    def _download(self) -> QWidget:
        area, form = _page()
        self.conc = QSpinBox(); self.conc.setRange(1, 8); self.conc.setValue(self.cfg["concurrency"])
        form.addRow("Downloads simultâneos", self.conc)
        self.exist = _combo([("ask", "Perguntar"), ("skip", "Pular"), ("replace", "Substituir"), ("rename", "Renomear (nome (1))")],
                            self.cfg["existing_file_action"])
        form.addRow("Se o arquivo já existir", self.exist)
        self.rate = QLineEdit(self.cfg["rate_limit"]); self.rate.setPlaceholderText("ex.: 2M  (vazio = sem limite)")
        form.addRow("Limite de velocidade", self.rate)
        self.retries = QSpinBox(); self.retries.setRange(0, 20); self.retries.setValue(self.cfg["retries"])
        form.addRow("Tentativas em caso de falha", self.retries)
        return area

    def _organize(self) -> QWidget:
        area, form = _page()
        self.org = _combo([("none", "Tudo na pasta de destino"), ("playlist", "Uma subpasta por playlist"),
                           ("channel", "Uma subpasta por canal/artista")], self.cfg["organize"])
        form.addRow("Subpastas", self.org)
        self.prefix = QCheckBox("Numerar as faixas de playlists (07 - Título)")
        self.prefix.setChecked(self.cfg["number_prefix"])
        form.addRow("", self.prefix)
        self.style = _combo([("title", "Título"), ("artist_title", "Artista - Título")], self.cfg["name_style"])
        form.addRow("Nome do arquivo", self.style)
        form.addRow("", _hint("Caracteres inválidos no Windows (\\ / : * ? \" < > |) são removidos automaticamente."))
        return area

    def _audio(self) -> QWidget:
        area, form = _page()
        self.fmt = _combo([(k, v["label"]) for k, v in audio.FORMATS.items()], self.cfg["format"])
        self.qual = QComboBox()
        self.fmt.currentIndexChanged.connect(lambda _: self._fill_quality(None))
        self._fill_quality(self.cfg["quality"])
        form.addRow("Formato", self.fmt)
        form.addRow("Qualidade", self.qual)
        form.addRow("", _hint("O YouTube entrega áudio de ~128 kbps (AAC) ou até ~160 kbps (Opus). Escolher 320 kbps "
                              "aumenta o arquivo, mas não cria qualidade que a fonte não tem. "
                              "\"Original\" copia o áudio sem reconverter."))
        self.source = _combo([("best", "Melhor disponível"), ("m4a", "Preferir M4A (AAC)"), ("opus", "Preferir Opus (WebM)")],
                             self.cfg["source"])
        form.addRow("Áudio de origem", self.source)
        self.meta = QCheckBox("Gravar tags (título, artista, álbum, faixa)"); self.meta.setChecked(self.cfg["embed_metadata"])
        self.album = QCheckBox("Usar o nome da playlist como álbum"); self.album.setChecked(self.cfg["album_from_playlist"])
        self.thumb = QCheckBox("Embutir capa"); self.thumb.setChecked(self.cfg["embed_thumbnail"])
        self.square = QCheckBox("Recortar a capa em quadrado"); self.square.setChecked(self.cfg["square_cover"])
        self.norm = QCheckBox("Normalizar o volume (EBU R128, -14 LUFS)"); self.norm.setChecked(self.cfg["normalize"])
        for cb in (self.meta, self.album, self.thumb, self.square, self.norm):
            form.addRow("", cb)
        self.eq_on = QCheckBox("Aplicar equalizador aos downloads")
        self.eq_on.setChecked(self.cfg["eq_enabled"])
        self.eq_panel = EqPanel()
        self.eq_panel.set_bands(self.cfg["eq_bands"])
        self.eq_panel.setEnabled(self.eq_on.isChecked())
        self.eq_on.toggled.connect(self.eq_panel.setEnabled)
        form.addRow("", self.eq_on)
        form.addRow(self.eq_panel)
        form.addRow("", _hint("O equalizador reconverte o áudio (não funciona com cópia direta). Ganhos positivos "
                              "recebem um limitador de picos para evitar distorção."))
        return area

    def _advanced(self) -> QWidget:
        area, form = _page()
        self.browser = _combo(BROWSERS, self.cfg["cookies_browser"])
        form.addRow("Cookies do navegador", self.browser)
        self.cookie_file = QLineEdit(self.cfg["cookies_file"]); self.cookie_file.setPlaceholderText("cookies.txt (opcional)")
        pick = QPushButton("Procurar…")
        pick.clicked.connect(lambda: self._pick_file(self.cookie_file, "Arquivo de cookies (*.txt);;Todos (*)"))
        row = QHBoxLayout(); row.addWidget(self.cookie_file, 1); row.addWidget(pick)
        form.addRow("Arquivo cookies.txt", row)
        form.addRow("", _hint("Use se o YouTube pedir login (\"confirme que não é um robô\"). Chrome/Edge recentes às vezes "
                              "bloqueiam a leitura dos cookies no Windows: Firefox ou um cookies.txt exportado costumam funcionar melhor."))
        self.proxy = QLineEdit(self.cfg["proxy"]); self.proxy.setPlaceholderText("http://host:porta (opcional)")
        form.addRow("Proxy", self.proxy)
        self.js_path = QLineEdit(self.cfg["js_runtime_path"]); self.js_path.setPlaceholderText("deno.exe / node.exe (vazio = automático)")
        jpick = QPushButton("Procurar…")
        jpick.clicked.connect(lambda: self._pick_file(self.js_path, "Executáveis (*.exe);;Todos (*)"))
        jrow = QHBoxLayout(); jrow.addWidget(self.js_path, 1); jrow.addWidget(jpick)
        form.addRow("Runtime JavaScript", jrow)
        _, desc = audio.find_js_runtimes(self.cfg.data)
        ff = audio.find_ffmpeg()
        form.addRow("", _hint(f"JavaScript detectado: {desc or 'nenhum — o YouTube pode falhar (instale o Deno)'}\n"
                              f"FFmpeg: {ff or 'não encontrado'}"))
        self.remote = QCheckBox("Permitir baixar os scripts de desafio (ejs:github) se estiverem faltando")
        self.remote.setChecked(self.cfg["allow_remote_components"])
        form.addRow("", self.remote)
        open_data = QPushButton("Abrir pasta de dados e logs")
        open_data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR))))
        form.addRow("", open_data)
        return area

    # --- helpers
    def _fill_quality(self, current: str | None) -> None:
        fmt = self.fmt.currentData()
        keep = current if current is not None else self.qual.currentData()
        self.qual.blockSignals(True)
        self.qual.clear()
        for value, label in audio.quality_options(fmt):
            self.qual.addItem(label, value)
        self.qual.setCurrentIndex(max(0, self.qual.findData(audio.normalize_quality(fmt, keep or ""))))
        self.qual.blockSignals(False)

    def _pick_dir(self, edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Escolher pasta", edit.text() or str(Path.home()))
        if d:
            edit.setText(d)

    def _pick_file(self, edit: QLineEdit, flt: str) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Escolher arquivo", edit.text() or str(Path.home()), flt)
        if f:
            edit.setText(f)

    def _save(self) -> None:
        c = self.cfg
        c["download_dir"] = os.path.expanduser(self.dir_edit.text().strip()) or c["download_dir"]
        c["auto_start"] = self.auto_start.isChecked()
        c["concurrency"] = self.conc.value()
        c["existing_file_action"] = self.exist.currentData()
        c["rate_limit"] = self.rate.text().strip()
        c["retries"] = self.retries.value()
        c["organize"] = self.org.currentData()
        c["number_prefix"] = self.prefix.isChecked()
        c["name_style"] = self.style.currentData()
        c["format"] = self.fmt.currentData()
        c["quality"] = self.qual.currentData() or ""
        c["source"] = self.source.currentData()
        c["embed_metadata"] = self.meta.isChecked()
        c["album_from_playlist"] = self.album.isChecked()
        c["embed_thumbnail"] = self.thumb.isChecked()
        c["square_cover"] = self.square.isChecked()
        c["normalize"] = self.norm.isChecked()
        c["eq_enabled"] = self.eq_on.isChecked()
        c["eq_bands"] = self.eq_panel.get_bands()
        c["cookies_browser"] = self.browser.currentData() or ""
        c["cookies_file"] = self.cookie_file.text().strip()
        c["proxy"] = self.proxy.text().strip()
        c["js_runtime_path"] = self.js_path.text().strip()
        c["allow_remote_components"] = self.remote.isChecked()
        c.save()
        audio.reset_tool_cache()
        self.accept()
