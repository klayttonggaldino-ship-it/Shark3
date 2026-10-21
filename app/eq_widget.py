"""Equalizador paramétrico de 6 bandas (estilo curva de resposta, desenhado com QPainter)."""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from . import audio
from .config import DEFAULT_EQ_BANDS

F_MIN, F_MAX, G_RANGE = 20.0, 20000.0, 18.0
BAND_COLORS = ["#ff4d8d", "#ffb454", "#4cd98a", "#54c7ff", "#a78bfa", "#ff7ad9"]
FREQ_GRID = [(20, "20"), (50, "50"), (100, "100"), (200, "200"), (500, "500"), (1000, "1k"),
             (2000, "2k"), (5000, "5k"), (10000, "10k"), (20000, "20k")]

PRESETS: dict[str, list[tuple[str, float, float, float]]] = {
    "Plano": [("lowshelf", 60, 0, .71), ("bell", 170, 0, 1), ("bell", 350, 0, 1), ("bell", 1000, 0, 1), ("bell", 3500, 0, 1), ("highshelf", 10000, 0, .71)],
    "Graves reforçados": [("lowshelf", 60, 6, .71), ("bell", 170, 3, 1), ("bell", 350, -1, 1), ("bell", 1000, 0, 1), ("bell", 3500, 0, 1), ("highshelf", 10000, 0, .71)],
    "Voz / podcast": [("highpass", 80, 0, .71), ("bell", 170, -2, 1), ("bell", 350, -1.5, 1.2), ("bell", 1000, 1, 1), ("bell", 3500, 3, 1), ("highshelf", 10000, 1.5, .71)],
    "Brilho (agudos)": [("lowshelf", 60, 0, .71), ("bell", 170, 0, 1), ("bell", 350, -1, 1), ("bell", 1000, 0, 1), ("bell", 3500, 2, 1), ("highshelf", 10000, 5, .71)],
    "Loudness (V)": [("lowshelf", 60, 5, .71), ("bell", 170, 1, 1), ("bell", 350, -2, 1), ("bell", 1000, -1, 1), ("bell", 3500, 1.5, 1), ("highshelf", 10000, 4, .71)],
}


class EqWidget(QWidget):
    changed = Signal()
    selectionChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.bands: list[dict] = copy.deepcopy(DEFAULT_EQ_BANDS)
        self.sel = 0
        self._drag = False
        self._hover = -1
        self._curve: list[float] = []
        self._sel_curve: list[float] = []
        self._freqs = [F_MIN * (F_MAX / F_MIN) ** (i / 239) for i in range(240)]
        self.setMouseTracking(True)
        self.setMinimumHeight(230)
        self.setToolTip("Arraste os pontos (frequência e ganho) · Roda do mouse: largura da banda (Q) · "
                        "Duplo clique: ligar/desligar a banda")
        self._recompute()

    # ---- API
    def set_bands(self, bands: list[dict]) -> None:
        self.bands = copy.deepcopy(bands)
        self._recompute()
        self.update()

    def get_bands(self) -> list[dict]:
        return copy.deepcopy(self.bands)

    def select(self, i: int) -> None:
        if 0 <= i < len(self.bands) and i != self.sel:
            self.sel = i
            self.selectionChanged.emit(i)
            self._recompute()
            self.update()

    def update_band(self, i: int, **kw) -> None:
        self.bands[i].update(kw)
        self._recompute()
        self.update()
        self.changed.emit()

    # ---- geometria
    def _plot(self) -> QRectF:
        return QRectF(42, 12, max(50, self.width() - 56), max(50, self.height() - 12 - 28))

    def _fx(self, f: float, r: QRectF) -> float:
        return r.left() + math.log10(max(f, F_MIN) / F_MIN) / math.log10(F_MAX / F_MIN) * r.width()

    def _xf(self, x: float, r: QRectF) -> float:
        t = min(max((x - r.left()) / r.width(), 0.0), 1.0)
        return F_MIN * 10 ** (t * math.log10(F_MAX / F_MIN))

    def _gy(self, g: float, r: QRectF) -> float:
        return r.center().y() - g / G_RANGE * (r.height() / 2)

    def _yg(self, y: float, r: QRectF) -> float:
        return (r.center().y() - y) / (r.height() / 2) * G_RANGE

    def _node(self, b: dict, r: QRectF) -> QPointF:
        g = b["gain"] if b["type"] in audio.GAIN_TYPES else 0.0
        return QPointF(self._fx(b["freq"], r), self._gy(g, r))

    def _recompute(self) -> None:
        self._curve = audio.total_response_db(self.bands, self._freqs)
        b = self.bands[self.sel]
        self._sel_curve = audio.band_response_db(b, self._freqs) if b.get("on", True) else []

    # ---- desenho
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot()
        p.setPen(QPen(QColor("#2f2f32"), 1))
        p.setBrush(QColor("#161618"))
        p.drawRoundedRect(r.adjusted(-6, -6, 6, 6), 10, 10)

        small = QFont(self.font())
        small.setPointSizeF(8)
        p.setFont(small)
        for g in range(-18, 19, 6):
            y = self._gy(g, r)
            p.setPen(QPen(QColor("#4a4a50") if g == 0 else QColor("#26262a"), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor("#7a7a80"))
            p.drawText(QRectF(0, y - 8, r.left() - 10, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{g:+d}" if g else "0")
        for f, label in FREQ_GRID:
            x = self._fx(f, r)
            p.setPen(QPen(QColor("#26262a"), 1))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setPen(QColor("#7a7a80"))
            p.drawText(QRectF(x - 20, r.bottom() + 6, 40, 16), Qt.AlignmentFlag.AlignCenter, label)

        def build(vals: list[float]) -> QPainterPath:
            path = QPainterPath()
            for i, (f, v) in enumerate(zip(self._freqs, vals)):
                pt = QPointF(self._fx(f, r), min(max(self._gy(v, r), r.top()), r.bottom()))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            return path

        total = build(self._curve)
        y0 = self._gy(0, r)
        fill = QPainterPath(total)
        fill.lineTo(self._fx(self._freqs[-1], r), y0)
        fill.lineTo(self._fx(self._freqs[0], r), y0)
        fill.closeSubpath()
        grad = QLinearGradient(0, r.top(), 0, r.bottom())
        grad.setColorAt(0.0, QColor(255, 77, 141, 90))
        grad.setColorAt(0.5, QColor(255, 77, 141, 18))
        grad.setColorAt(1.0, QColor(255, 77, 141, 90))
        p.fillPath(fill, grad)
        if self._sel_curve:
            c = QColor(BAND_COLORS[self.sel])
            c.setAlpha(120)
            p.setPen(QPen(c, 1.4, Qt.PenStyle.DashLine))
            p.drawPath(build(self._sel_curve))
        p.setPen(QPen(QColor("#ff4d8d"), 2.4))
        p.drawPath(total)

        for i, b in enumerate(self.bands):
            pt = self._node(b, r)
            col = QColor(BAND_COLORS[i])
            on = b.get("on", True)
            radius = 8.5 if i == self.sel else 6.5
            if i == self.sel:
                halo = QColor(col)
                halo.setAlpha(70)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(halo)
                p.drawEllipse(pt, radius + 5, radius + 5)
            if on:
                p.setPen(QPen(QColor("#161618"), 2))
                p.setBrush(col)
            else:
                p.setPen(QPen(QColor("#6a6a70"), 2))
                p.setBrush(QColor("#161618"))
            p.drawEllipse(pt, radius, radius)
            p.setPen(QColor("#161618") if on else QColor("#8a8a90"))
            nf = QFont(small)
            nf.setBold(True)
            nf.setPointSizeF(7.5)
            p.setFont(nf)
            p.drawText(QRectF(pt.x() - 8, pt.y() - 8, 16, 16), Qt.AlignmentFlag.AlignCenter, str(i + 1))
        p.end()

    # ---- interação
    def _hit(self, pos: QPointF) -> int:
        r = self._plot()
        best, dist = -1, 16.0
        for i, b in enumerate(self.bands):
            n = self._node(b, r)
            d = math.hypot(n.x() - pos.x(), n.y() - pos.y())
            if d < dist:
                best, dist = i, d
        return best

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            i = self._hit(e.position())
            if i >= 0:
                self.select(i)
                self._drag = True

    def mouseMoveEvent(self, e) -> None:
        r = self._plot()
        if self._drag:
            b = self.bands[self.sel]
            pos = e.position()
            b["freq"] = round(min(max(self._xf(pos.x(), r), F_MIN), F_MAX), 1)
            if b["type"] in audio.GAIN_TYPES:
                b["gain"] = round(min(max(self._yg(pos.y(), r), -G_RANGE), G_RANGE) * 2) / 2
            self._recompute()
            self.update()
            self.changed.emit()
            self.selectionChanged.emit(self.sel)  # atualiza os campos numéricos
        else:
            h = self._hit(e.position())
            if h != self._hover:
                self._hover = h
                self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if h >= 0 else Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, _e) -> None:
        self._drag = False

    def mouseDoubleClickEvent(self, e) -> None:
        i = self._hit(e.position())
        if i >= 0:
            self.select(i)
            self.update_band(i, on=not self.bands[i].get("on", True))
            self.selectionChanged.emit(i)

    def wheelEvent(self, e) -> None:
        i = self._hit(e.position())
        i = i if i >= 0 else self.sel
        self.select(i)
        steps = e.angleDelta().y() / 120.0
        q = min(max(self.bands[i]["q"] * (1.12 ** steps), 0.2), 12.0)
        self.update_band(i, q=round(q, 2))
        self.selectionChanged.emit(i)
        e.accept()


class EqPanel(QWidget):
    """Gráfico + controles numéricos da banda selecionada + presets."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._busy = False
        self.eq = EqWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItem("Presets…")
        self.preset.addItems(PRESETS.keys())
        reset = QPushButton("Resetar")
        top.addWidget(QLabel("Equalizador"))
        top.addStretch(1)
        top.addWidget(self.preset)
        top.addWidget(reset)
        lay.addLayout(top)
        lay.addWidget(self.eq)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        self.lbl = QLabel("Banda 1")
        self.type = QComboBox()
        for key, label in audio.EQ_TYPES:
            self.type.addItem(label, key)
        self.freq = QDoubleSpinBox(); self.freq.setRange(F_MIN, F_MAX); self.freq.setDecimals(0); self.freq.setSuffix(" Hz")
        self.gain = QDoubleSpinBox(); self.gain.setRange(-G_RANGE, G_RANGE); self.gain.setSingleStep(0.5); self.gain.setSuffix(" dB")
        self.q = QDoubleSpinBox(); self.q.setRange(0.2, 12.0); self.q.setSingleStep(0.1); self.q.setPrefix("Q ")
        self.on = QCheckBox("Ativa")
        for w in (self.type, self.freq, self.gain, self.q):
            w.setMinimumWidth(0)
        grid.addWidget(self.lbl, 0, 0)
        grid.addWidget(self.type, 0, 1, 1, 2)
        grid.addWidget(self.on, 0, 3)
        grid.addWidget(self.freq, 1, 1)
        grid.addWidget(self.gain, 1, 2)
        grid.addWidget(self.q, 1, 3)
        for c in (1, 2, 3):
            grid.setColumnStretch(c, 1)
        lay.addLayout(grid)

        self.eq.changed.connect(self.changed)
        self.eq.selectionChanged.connect(self._load_band)
        self.type.currentIndexChanged.connect(lambda _: self._push(type=self.type.currentData()))
        self.freq.valueChanged.connect(lambda v: self._push(freq=float(v)))
        self.gain.valueChanged.connect(lambda v: self._push(gain=float(v)))
        self.q.valueChanged.connect(lambda v: self._push(q=float(v)))
        self.on.toggled.connect(lambda v: self._push(on=bool(v)))
        self.preset.activated.connect(self._apply_preset)
        reset.clicked.connect(lambda: self.set_bands(copy.deepcopy(DEFAULT_EQ_BANDS), emit=True))
        self._load_band(0)

    def set_bands(self, bands: list[dict], emit: bool = False) -> None:
        self.eq.set_bands(bands)
        self._load_band(self.eq.sel)
        if emit:
            self.changed.emit()

    def get_bands(self) -> list[dict]:
        return self.eq.get_bands()

    def _load_band(self, i: int) -> None:
        b = self.eq.bands[i]
        self._busy = True
        self.lbl.setText(f"Banda {i + 1}")
        self.type.setCurrentIndex(max(0, self.type.findData(b["type"])))
        self.freq.setValue(b["freq"])
        self.gain.setValue(b["gain"])
        self.gain.setEnabled(b["type"] in audio.GAIN_TYPES)
        self.q.setValue(b["q"])
        self.on.setChecked(b.get("on", True))
        self._busy = False

    def _push(self, **kw) -> None:
        if self._busy:
            return
        self.eq.update_band(self.eq.sel, **kw)
        if "type" in kw:
            self.gain.setEnabled(kw["type"] in audio.GAIN_TYPES)

    def _apply_preset(self, idx: int) -> None:
        name = self.preset.itemText(idx)
        if name not in PRESETS:
            return
        bands = [{"type": t, "freq": float(f), "gain": float(g), "q": float(q), "on": True} for t, f, g, q in PRESETS[name]]
        self.set_bands(bands, emit=True)
        self.preset.setCurrentIndex(0)
