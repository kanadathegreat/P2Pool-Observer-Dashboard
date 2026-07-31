"""
graph_widget.py
----------------
A small custom widget that draws a line graph of hashrate history.

We're NOT using matplotlib here on purpose. matplotlib is a heavy
dependency (tens of MB) for something this simple, and embedding it
inside a Qt window needs extra glue code. Since we only need a plain
line going up and down, drawing it ourselves with Qt's own painting
tools (QPainter) is lighter and simpler. This is a common pattern:
reach for a big library only when you need what makes it big.
"""

from collections import deque

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor

import theme

# How many data points to keep. At one point every 300 seconds, 200
# points covers about 16 hours of history -- plenty for "since the
# program was opened," and small enough to never be a memory concern.
MAX_POINTS = 200


class HashrateGraphWidget(QWidget):
    """
    Call add_point(hashrate_hs) each time you have a fresh reading.
    The widget redraws itself automatically.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        # deque = a list that's efficient at dropping old items off
        # the front once it hits maxlen -- exactly what we want for
        # "keep only the most recent N points."
        self._history = deque(maxlen=MAX_POINTS)

    def add_point(self, hashrate_hs: float):
        self._history.append(hashrate_hs)
        self.update()  # tells Qt "redraw this widget soon"

    def paintEvent(self, event):
        """
        Qt calls this automatically whenever the widget needs to be
        (re)drawn -- after add_point(), after a resize, etc. We never
        call this ourselves directly.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # smooth line, not jagged

        if len(self._history) < 2:
            # Not enough data yet for a line -- show a friendly
            # message instead of an empty box.
            painter.setPen(QColor(theme.TEXT_SECONDARY))
            painter.drawText(
                self.rect(), Qt.AlignCenter, "Collecting hashrate history..."
            )
            return

        width = self.width()
        height = self.height()
        padding = 10

        min_value = min(self._history)
        max_value = max(self._history)
        if max_value == min_value:
            # Avoid dividing by zero below if hashrate hasn't changed
            # at all yet (e.g. only 2 identical readings so far).
            max_value = min_value + 1

        usable_width = width - (2 * padding)
        usable_height = height - (2 * padding)
        step_x = usable_width / (len(self._history) - 1)

        def point_for(index, value):
            x = padding + (index * step_x)
            # Note the flip: a HIGHER value should draw HIGHER on
            # screen, but screen Y coordinates count DOWN from the
            # top, so we subtract the normalized value from height
            # instead of adding it.
            normalized = (value - min_value) / (max_value - min_value)
            y = height - padding - (normalized * usable_height)
            return QPointF(x, y)

        path = QPainterPath()
        points = [point_for(i, v) for i, v in enumerate(self._history)]
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)

        pen = QPen(QColor(theme.ORANGE))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawPath(path)
