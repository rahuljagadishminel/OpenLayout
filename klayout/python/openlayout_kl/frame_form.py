"""The Standard-Cell Frame window: a frame of any stack of N and P regions.

Rows are listed top to bottom, each an N or a P region (135 nm, five fin tracks) with its width in
gate pitches; *Add row*, *Remove*, *Move up* / *Move down* reshape the stack, and *All gate pitches
equal* keeps every row as wide as the one being edited. Each row's *Rail above* - and the bottom
edge's rail - is *Auto* (pcells.frame_rails: the edges carry their region's supply, two regions of
the same type share a rail, an N and a P region pair up and share their gates without a rail, so
that every region still reaches its supply) or VDD / VSS / none. The preview draws the stack with
its rails; a region left without its supply rail is warned about.
"""
import pya

from .pcells import CPP, frame_rails

RAIL_CHOICES = ["Auto", "VDD", "VSS", "None"]


def _qt_owned(widget):
    """a widget handed to a table cell: Qt deletes it with the cell, so Python must not too"""
    for name in ("_unmanage", "_keep"):
        if hasattr(widget, name):
            getattr(widget, name)()
            break
    return widget


def _get(obj, name):
    """a Qt accessor that KLayout's binding exposes as a method or as a property"""
    v = getattr(obj, name)
    return v() if callable(v) else v


class FrameForm(pya.QDialog):
    def __init__(self, parent, config, ui):
        """config: {regions: [(type, pitches)] bottom up, rails: {boundary: rail}, vt}"""
        super().__init__(parent)
        self.ui = ui
        self.windowTitle = "Standard-Cell Frame"
        n = len(config["regions"])
        # the model, top to bottom: {type, cpp, rail} with rail = the override of the boundary above
        self.rows = [{"type": t, "cpp": int(c), "rail": config["rails"].get(r + 1, "auto")}
                     for r, (t, c) in reversed(list(enumerate(config["regions"])))]
        self.bottom_rail = config["rails"].get(0, "auto")
        self.vt = config.get("vt", "rvt")
        self._building = False

        lay = pya.QVBoxLayout(self)
        intro = pya.QLabel("Rows from top to bottom: each an N or a P region (135 nm, five fin tracks).", self)
        intro.styleSheet = f"color: {ui['dim']};"
        lay.addWidget(intro)

        bar = pya.QHBoxLayout()
        for label, slot in (("Add row", self.add_row), ("Remove", self.remove_row),
                            ("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(1))):
            b = pya.QPushButton(label, self)
            b.clicked = slot
            bar.addWidget(b)
        bar.addStretch(1)
        self.equal = pya.QCheckBox("All gate pitches equal", self)
        self.equal.checked = len({r["cpp"] for r in self.rows}) == 1
        self.equal.toggled = self.on_equal
        bar.addWidget(self.equal)
        lay.addLayout(bar)

        self.table = pya.QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "Type", "Gate pitches", "Rail above"])
        _get(self.table, "verticalHeader").visible = False
        self.table.selectionBehavior = pya.QAbstractItemView.SelectRows
        self.table.selectionMode = pya.QAbstractItemView.SingleSelection
        _get(self.table, "horizontalHeader").stretchLastSection = True
        lay.addWidget(self.table)

        low = pya.QHBoxLayout()
        low.addWidget(pya.QLabel("Rail below the bottom row:", self))
        self.bottom = pya.QComboBox(self)
        self.bottom.addItems(RAIL_CHOICES)
        self.bottom.currentIndexChanged = self.on_bottom
        low.addWidget(self.bottom)
        low.addStretch(1)
        low.addWidget(pya.QLabel("Threshold voltage:", self))
        self.vt_box = pya.QComboBox(self)
        self.vt_box.addItems(["rvt", "lvt", "slvt"])
        self.vt_box.setCurrentIndex(["rvt", "lvt", "slvt"].index(self.vt) if self.vt in ("rvt", "lvt", "slvt") else 0)
        low.addWidget(self.vt_box)
        lay.addLayout(low)

        self.preview = pya.QLabel(self)
        self.preview.alignment = pya.Qt.AlignCenter
        self.preview.minimumHeight = 120
        lay.addWidget(self.preview)
        self.warn = pya.QLabel("", self)
        self.warn.wordWrap = True
        self.warn.styleSheet = f"color: {ui['warn']};"
        lay.addWidget(self.warn)

        buttons = pya.QDialogButtonBox(self)
        ok = buttons.addButton("Draw Frame", pya.QDialogButtonBox.AcceptRole)
        buttons.addButton(pya.QDialogButtonBox.Cancel)
        buttons.accepted = self.accept
        buttons.rejected = self.reject
        ok.default = True
        lay.addWidget(buttons)

        self.resize(560, 520)
        self.rebuild()

    # ---- the model ----------------------------------------------------------------------------
    def regions(self):
        """bottom up [(type, cpp)]"""
        return [(r["type"], r["cpp"]) for r in reversed(self.rows)]

    def overrides(self):
        """{boundary: "VDD" | "VSS" | None} of the rails not left on Auto"""
        n = len(self.rows)
        out = {}
        for t, r in enumerate(self.rows):
            if r["rail"] != "auto":
                out[n - t] = r["rail"]
        if self.bottom_rail != "auto":
            out[0] = self.bottom_rail
        return out

    def result(self):
        """(regions bottom up, rail overrides, vt) for stdcell.insert_frame_regions"""
        return self.regions(), self.overrides(), self.vt_box.currentText

    def plan(self):
        return frame_rails([t for t, _ in self.regions()], self.overrides())

    # ---- building the table -------------------------------------------------------------------
    def rebuild(self, select=None):
        self._building = True
        try:
            self.table.setRowCount(0)            # the old cell widgets go (Qt deletes them)
            self.table.setRowCount(len(self.rows))
            rails, _warnings = self.plan()
            n = len(self.rows)
            self.kinds, self.spins, self.rail_boxes = [], [], []   # the cell widgets, row by row
            for t, r in enumerate(self.rows):
                num = pya.QTableWidgetItem(str(t + 1))
                num.flags = pya.Qt.ItemIsEnabled | pya.Qt.ItemIsSelectable
                self.table.setItem(t, 0, num)
                kind = _qt_owned(pya.QComboBox())
                kind.addItems(["N", "P"])
                kind.setCurrentIndex(0 if r["type"] == "N" else 1)
                kind.currentIndexChanged = lambda i, t=t: self.set_field(t, "type", "N" if i == 0 else "P")
                self.table.setCellWidget(t, 1, kind)
                self.kinds.append(kind)
                spin = _qt_owned(pya.QSpinBox())
                spin.setRange(1, 400)
                spin.value = r["cpp"]
                spin.suffix = f"  ({r['cpp'] * CPP} nm)"
                spin.valueChanged = lambda v, t=t: self.set_cpp(t, v)
                self.table.setCellWidget(t, 2, spin)
                self.spins.append(spin)
                box = self.rail_box(r["rail"], rails[n - t])
                self.table.setCellWidget(t, 3, box)
                self.rail_boxes.append(box)
            self.bottom.setItemText(0, f"Auto ({rails[0] or 'no rail'})")
            self.bottom.setCurrentIndex(self.rail_index(self.bottom_rail))
            self.table.resizeColumnsToContents()
            if select is not None and 0 <= select < len(self.rows):
                self.table.selectRow(select)
        finally:
            self._building = False
        self.update_preview()

    def refresh(self):
        """the cell widgets from the model, in place (a widget whose signal is running must not be
        replaced), and the preview"""
        self._building = True
        try:
            rails, _warnings = self.plan()
            n = len(self.rows)
            for t, r in enumerate(self.rows):
                self.kinds[t].setCurrentIndex(0 if r["type"] == "N" else 1)
                if self.spins[t].value != r["cpp"]:
                    self.spins[t].value = r["cpp"]
                self.spins[t].suffix = f"  ({r['cpp'] * CPP} nm)"
                self.rail_boxes[t].setItemText(0, f"Auto ({rails[n - t] or 'no rail'})")
                self.rail_boxes[t].setCurrentIndex(self.rail_index(r["rail"]))
            self.bottom.setItemText(0, f"Auto ({rails[0] or 'no rail'})")
            self.bottom.setCurrentIndex(self.rail_index(self.bottom_rail))
        finally:
            self._building = False
        self.update_preview()

    def rail_box(self, value, auto):
        box = _qt_owned(pya.QComboBox())
        box.addItems(RAIL_CHOICES)
        box.setItemText(0, f"Auto ({auto or 'no rail'})")
        box.setCurrentIndex(self.rail_index(value))
        box.currentIndexChanged = lambda i, b=box: self.set_rail_from(b, i)
        return box

    @staticmethod
    def rail_index(value):
        return {"auto": 0, "VDD": 1, "VSS": 2, None: 3}.get(value, 0)

    @staticmethod
    def rail_value(index):
        return ["auto", "VDD", "VSS", None][index]

    def selected(self):
        t = _get(self.table, "currentRow")
        return t if 0 <= t < len(self.rows) else None

    # ---- edits --------------------------------------------------------------------------------
    def set_field(self, t, key, value):
        if self._building:
            return
        self.rows[t][key] = value
        self.refresh()

    def set_cpp(self, t, v):
        if self._building:
            return
        for i, r in enumerate(self.rows):
            if i == t or self.equal.checked:
                r["cpp"] = int(v)
        self.refresh()

    def set_rail_from(self, box, index):
        if self._building:
            return
        for t, b in enumerate(self.rail_boxes):
            if b is box:
                self.rows[t]["rail"] = self.rail_value(index)
                self.refresh()
                return

    def on_bottom(self, index):
        if self._building:
            return
        self.bottom_rail = self.rail_value(index)
        self.refresh()

    def on_equal(self, on):
        if on and self.rows:
            t = self.selected()
            width = self.rows[t if t is not None else 0]["cpp"]
            for r in self.rows:
                r["cpp"] = width
            self.refresh()

    def add_row(self):
        """a row above the selected one (else on top), of the other type than its neighbour"""
        t = self.selected()
        t = 0 if t is None else t
        near = self.rows[t] if self.rows else {"type": "P", "cpp": 4}
        self.rows.insert(t, {"type": "N" if near["type"] == "P" else "P", "cpp": near["cpp"], "rail": "auto"})
        self.rebuild(select=t)

    def remove_row(self):
        t = self.selected()
        if t is None or len(self.rows) <= 1:
            return
        del self.rows[t]
        self.rebuild(select=min(t, len(self.rows) - 1))

    def move(self, d):
        t = self.selected()
        if t is None or not 0 <= t + d < len(self.rows):
            return
        self.rows[t], self.rows[t + d] = self.rows[t + d], self.rows[t]
        self.rebuild(select=t + d)

    # ---- the preview --------------------------------------------------------------------------
    def update_preview(self):
        rails, warnings = self.plan()
        regions = self.regions()
        widest = max(c for _, c in regions)
        rh, scale = 34, min(320.0 / widest, 24.0)       # pixels per region, per gate pitch
        left, top = 70, 14
        w_img = int(left + widest * scale + 20)
        h_img = int(top * 2 + rh * len(regions))
        img = pya.QImage(w_img, h_img, pya.QImage.Format_ARGB32)
        img.fill(pya.QColor(self.ui["base"]))
        p = pya.QPainter(img)
        try:
            colors = {"N": pya.QColor("#2f5d46"), "P": pya.QColor("#6a3550")}
            for r, (t, c) in enumerate(regions):
                y = top + rh * (len(regions) - 1 - r)
                p.fillRect(left, y, int(c * scale), rh, colors[t])
                p.setPen(pya.QColor(self.ui["text"]))
                p.drawText(left + 6, y + rh // 2 + 5, f"{t}   {c} CPP")
            for b, rail in enumerate(rails):
                y = top + rh * (len(regions) - b)
                near = [regions[r][1] for r in (b - 1, b) if 0 <= r < len(regions)]
                x2 = left + int(max(near) * scale)
                if rail:
                    color = pya.QColor(self.ui["fail"] if rail == "VDD" else self.ui["accent"])
                    pen = pya.QPen(color)
                    pen.setWidth(4)
                    p.setPen(pen)
                    p.drawLine(left, y, x2, y)
                    p.drawText(8, y + 5, rail)
                elif 0 < b < len(regions):
                    pen = pya.QPen(pya.QColor(self.ui["dim"]))
                    pen.setStyle(pya.Qt.DashLine)
                    p.setPen(pen)
                    p.drawLine(left, y, x2, y)
                    p.drawText(8, y + 5, "gates")
        finally:
            p.end()
        self.preview.setPixmap(pya.QPixmap.fromImage(img))
        self.preview.minimumHeight = h_img       # grows with the stack
        self.warn.text = "\n".join(warnings)
