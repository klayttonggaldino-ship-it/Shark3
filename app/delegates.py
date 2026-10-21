"""Delegate da árvore de downloads (miniaturas, progresso, status colorido)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

ROLE_ID = int(Qt.ItemDataRole.UserRole)
ROLE_KIND = ROLE_ID + 1      # video | group | more | pending
ROLE_STATUS = ROLE_ID + 2
ROLE_PROGRESS = ROLE_ID + 3
ROLE_SUB = ROLE_ID + 4
ROLE_THUMB = ROLE_ID + 5

STATUS_LABELS = {
    "analyzing": "Analisando…", "ready": "Pronto", "queued": "Na fila", "downloading": "Baixando",
    "converting": "Convertendo", "done": "Concluído", "error": "Erro", "cancelled": "Cancelado",
    "skipped": "Já existe",
}
STATUS_COLORS = {
    "analyzing": "#9a9a9a", "ready": "#8ab4f8", "queued": "#ffb454", "downloading": "#ff4d8d",
    "converting": "#c792ea", "done": "#4cd98a", "error": "#ff5c5c", "cancelled": "#9a9a9a", "skipped": "#6ecbf5",
}
ACTIVE = ("queued", "downloading", "converting")
ROW_H = 56
ACCENT = QColor("#ff4d8d")
MUTED = QColor("#9a9a9a")


class ItemDelegate(QStyledItemDelegate):
    def __init__(self, thumbs, parent=None):
        super().__init__(parent)
        self.thumbs = thumbs

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, QColor("#2c2c33"))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor("#252529"))
        kind = index.data(ROLE_KIND)
        col = index.column()
        if col == 0:
            self._paint_title(painter, rect, index, kind)
        elif col == 2:
            self._paint_status(painter, rect, index, kind)
        else:
            painter.setPen(MUTED)
            painter.drawText(rect.adjusted(6, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
        painter.restore()

    # -- coluna 0: miniatura + título + subtítulo + progresso
    def _paint_title(self, p: QPainter, rect, index, kind) -> None:
        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        sub = str(index.data(ROLE_SUB) or "")
        x = rect.left() + 8
        if kind == "video":
            thumb = QRectF(x, rect.center().y() - 18, 64, 36)
            path = QPainterPath()
            path.addRoundedRect(thumb, 5, 5)
            pm = self.thumbs.get(index.data(ROLE_THUMB) or "")
            if pm is not None:
                p.save()
                p.setClipPath(path)
                p.drawPixmap(thumb.toRect(), pm, pm.rect())
                p.restore()
            else:
                p.fillPath(path, QColor("#2d2d30"))
                p.setPen(QColor("#55555a"))
                p.drawText(thumb, Qt.AlignmentFlag.AlignCenter, "♪")
            x += 76
        font = QFont(option_font(p))
        font.setWeight(QFont.Weight.DemiBold if kind in ("video", "group") else QFont.Weight.Normal)
        if kind == "more":
            font.setItalic(True)
        p.setFont(font)
        p.setPen(ACCENT if kind == "more" else QColor("#ececec") if kind != "pending" else MUTED)
        fm = p.fontMetrics()
        w = rect.right() - x - 8
        top = rect.top() + (10 if sub else 18)
        p.drawText(QRectF(x, top, w, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(title, Qt.TextElideMode.ElideRight, int(w)))
        if sub:
            f2 = QFont(font)
            f2.setPointSizeF(max(8.0, font.pointSizeF() - 1.5))
            f2.setWeight(QFont.Weight.Normal)
            f2.setItalic(False)
            p.setFont(f2)
            p.setPen(MUTED)
            p.drawText(QRectF(x, top + 20, w, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, int(w)))
        status = index.data(ROLE_STATUS)
        if kind == "video" and status in ("downloading", "converting"):
            pct = float(index.data(ROLE_PROGRESS) or 0.0)
            bar = QRectF(x, rect.bottom() - 6, w, 3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3a3a3f"))
            p.drawRoundedRect(bar, 1.5, 1.5)
            p.setBrush(ACCENT)
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * max(0.0, min(pct, 100.0)) / 100, 3), 1.5, 1.5)

    # -- coluna 2: ponto colorido + texto
    def _paint_status(self, p: QPainter, rect, index, kind) -> None:
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        status = index.data(ROLE_STATUS) or ""
        if kind != "video" or not status:
            p.setPen(MUTED)
            p.drawText(rect.adjusted(6, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            return
        color = QColor(STATUS_COLORS.get(status, "#9a9a9a"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(rect.left() + 8, rect.center().y() - 3.5, 7, 7))
        p.setPen(QPen(QColor("#d8d8d8")))
        p.drawText(rect.adjusted(24, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width() - 30))


def option_font(painter: QPainter) -> QFont:
    return painter.font()
