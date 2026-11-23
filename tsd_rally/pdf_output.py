"""PDF version of the printable sheets, drawn with reportlab (pure Python, no system libraries).

It lays out the same sheet model (sheet.py) the HTML page uses, with the same sizes, padding,
shading and footer as the page's print styles, on US Letter paper.
"""
import io
import os
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily, stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (CondPageBreak, HRFlowable, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

import sheet

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 36, 36, 54          # .5in, .5in, .75in
PAGE_W = letter[0] - 2 * MARGIN_X

_fonts = None


def fonts():
    """(regular, bold) font names. Liberation Sans (Arial-compatible) if its files are bundled,
    otherwise the built-in Helvetica."""
    global _fonts
    if _fonts is None:
        try:
            faces = {"LS": "Regular", "LS-Bold": "Bold", "LS-Italic": "Italic", "LS-BoldItalic": "BoldItalic"}
            for name, style in faces.items():
                pdfmetrics.registerFont(TTFont(name, os.path.join(FONT_DIR, f"LiberationSans-{style}.ttf")))
            registerFontFamily("LS", normal="LS", bold="LS-Bold", italic="LS-Italic", boldItalic="LS-BoldItalic")
            _fonts = ("LS", "LS-Bold")
        except Exception:
            _fonts = ("Helvetica", "Helvetica-Bold")
    return _fonts


def rl(text):
    """Sheet text (with ** and * markup) -> reportlab paragraph markup."""
    return sheet.apply_markup(escape(text), r"<b><i>\1</i></b>", r"<b>\1</b>", r"<i>\1</i>")


def plain(text):
    """Text without the markup characters (for measuring widths)."""
    return re.sub(r"\*+", "", text)


def style(size, bold=False, align=TA_LEFT, leading=None):
    reg, bld = fonts()
    return ParagraphStyle("s", fontName=bld if bold else reg, fontSize=size,
                          leading=leading or size * 1.25, alignment=align, textColor=colors.black)


def _width(text, size, bold):
    reg, bld = fonts()
    return stringWidth(text, bld if bold else reg, size)


def _longest_word(text, size, bold):
    return max((_width(w, size, bold) for w in text.split()), default=0)


BORDER = 1.5   # table border width in points
LH = 1.149     # a browser's 'normal' line height for Arial-style text (table cells set 1.25 explicitly)


def _sizes(mode):
    """Font size, header font size, vertical and horizontal cell padding for each sheet type."""
    master, measure = mode == "master", mode == "measure"
    return (14 if master else 16, 11 if master else 12, 8 if master else (14 if measure else 10),
            6 if master else 8)


def _measure(block, mode):
    """Natural ('max-content') and narrowest ('min-content') width of each column, in points.
    Number columns never wrap; text columns can wrap between words."""
    size, th_size, _, pad_h = _sizes(mode)
    bold_cells = mode != "master"            # number columns are bold on participant / measure
    head, rows = block["head"], block["rows"]
    min_first = 1.3 * 72 if mode == "measure" else None
    nat, mn, is_text = [], [], []
    for j, h in enumerate(head):
        cells = [r["cells"][j] for r in rows]
        head_min = _longest_word(h["t"], th_size, True) + 2 * pad_h + BORDER
        text = any(c.get("lines") or c.get("rich") for c in cells)
        if not text:
            w = max([_width(c["t"], size, bold_cells and c.get("cls") in ("n", "c") or r["cls"] in ("out", "cp"))
                     for c, r in zip(cells, rows)] + [0]) + 2 * pad_h + BORDER
            w = max(w, head_min)
            if j == 1 and min_first:
                w = max(w, min_first)
            nat.append(w)
            mn.append(w)
        else:
            full = word = 0
            for c, r in zip(cells, rows):
                bold = r["cls"] in ("out", "cp")
                for line in (c.get("lines") or [c.get("t", "")]):
                    full = max(full, _width(plain(line), size, bold))
                    word = max(word, _longest_word(plain(line), size, bold))
            nat.append(max(full + 2 * pad_h + BORDER, head_min))
            mn.append(max(word + 2 * pad_h + BORDER, head_min))
        is_text.append(text)
    return nat, mn, is_text


def _distribute(nat, mn, is_text, total):
    """Column widths for a table `total` points wide, as a browser's automatic layout would:
    columns start at their narrowest and the spare room is shared out by how much more text
    each would like to hold."""
    spare = total - sum(mn)
    want = sum(n - m for n, m in zip(nat, mn))
    if want <= 0:                                        # only number columns: stretch evenly
        return [m + spare * m / sum(mn) for m in mn]
    share = min(spare / want, 1.0)
    widths = [m + (n - m) * share for n, m in zip(nat, mn)]
    left = total - sum(widths)                           # still room after everyone has what they want
    if left > 0:
        grow = [j for j, t in enumerate(is_text) if t] or list(range(len(widths)))
        weight = sum(nat[j] for j in grow)
        for j in grow:
            widths[j] += left * nat[j] / weight
    return widths


def _table(block, mode, total, k):
    """total = layout width in points before scaling; k = scale applied to everything."""
    size, th_size, pad_v, pad_h = _sizes(mode)
    bold_cells = mode != "master"
    head, rows = block["head"], block["rows"]
    nat, mn, is_text = _measure(block, mode)
    widths = [w * k for w in _distribute(nat, mn, is_text, total)]
    th_style = {True: style(th_size * k, True, TA_CENTER), False: style(th_size * k, True)}
    data = [[Paragraph(escape(h["t"]), th_style[h.get("cls") == "c"]) for h in head]]
    for r in rows:
        line = []
        for c in r["cells"]:
            cls = c.get("cls", "")
            bold = r["cls"] in ("out", "cp") or (bold_cells and cls in ("n", "c"))
            st = style(size * k, bold, {"c": TA_CENTER, "n": TA_RIGHT}.get(cls, TA_LEFT))
            if c.get("lines"):
                line.append([Paragraph(rl(l), st) if l else Spacer(1, 8 * k) for l in c["lines"]])
            else:
                line.append(Paragraph(rl(c["t"]) if c.get("rich") else escape(c["t"]), st))
        data.append(line)
    t = Table(data, colWidths=widths, repeatRows=1)
    cmds = [("GRID", (0, 0), (-1, -1), BORDER * k, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), (pad_v + BORDER / 2) * k),    # collapsed borders add
            ("BOTTOMPADDING", (0, 0), (-1, -1), (pad_v + BORDER / 2) * k),   # their width to each row
            ("LEFTPADDING", (0, 0), (-1, -1), pad_h * k), ("RIGHTPADDING", (0, 0), (-1, -1), pad_h * k),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd"))]
    for i, r in enumerate(rows, 1):                      # zebra stripes, then highlights on top
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f0f0f0")))
        if r["cls"] == "cp":
            cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fff3b0")))
        elif r["cls"] == "out":
            cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#cfe6ff")))
    t.setStyle(TableStyle(cmds))
    return t


def _banner(block, k):
    html = " &mdash; ".join(f"<b>{escape(p['label'])}</b> " + (rl(p["text"]) if p.get("rich") else escape(p["text"]))
                            for p in block["parts"])
    t = Table([[Paragraph(html, style(16 * k, leading=16 * k * LH))]], colWidths=[PAGE_W])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 3 * k, colors.black), ("LEFTPADDING", (0, 0), (-1, -1), 8 * k),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 8 * k), ("TOPPADDING", (0, 0), (-1, -1), 8 * k),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 8 * k)]))
    return t


def _fit(text, font, size, max_w):
    if stringWidth(text, font, size) <= max_w:
        return text
    while text and stringWidth(text + "…", font, size) > max_w:
        text = text[:-1]
    return text + "…"


def _canvas_class(left, right):
    reg, bld = fonts()

    class NumberedCanvas(canvas.Canvas):
        """Draws 'Page N of M' in the footer: pages are held back until the total is known."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self._footer(total)
                super().showPage()
            super().save()

        def _footer(self, total):
            y = 22
            self.setFillColor(colors.black)
            self.setFont(reg, 10)
            self.drawString(MARGIN_X, y, _fit(left, reg, 10, 200))
            self.drawRightString(letter[0] - MARGIN_X, y, _fit(right, reg, 10, 200))
            self.setFont(bld, 11)
            self.drawCentredString(letter[0] / 2, y, f"Page {self._pageNumber} of {total}")

    return NumberedCanvas


def build_pdf(model):
    """model = sheet.build_sheet(...). Returns the PDF as bytes.

    Like a browser printing the page, if the widest table can't fit between the margins at full
    size, everything on the page is scaled down together until it does."""
    mode = model["mode"]
    tables = [b for b in model["blocks"] if b["type"] == "table"]
    need = max([sum(_measure(b, mode)[1]) for b in tables] + [PAGE_W])
    k = PAGE_W / need                                    # 1 unless a table is too wide
    total = need                                         # layout width before scaling
    story = [Paragraph(escape(model["title"]), style(26 * k, True, leading=26 * k * LH))]
    if model["subtitle"]:
        story += [Spacer(1, 3 * k), Paragraph(escape(model["subtitle"]), style(18 * k, leading=18 * k * LH))]
    meta = (model["date_text"] + " &middot; " if model["date_text"] else "") + escape(model["label"])
    story += [Spacer(1, 4.2 * k), Paragraph(meta, style(14 * k, leading=14 * k * LH)), Spacer(1, 6 * k),
              HRFlowable(width="100%", thickness=2.25 * k, color=colors.black, spaceBefore=0, spaceAfter=0)]

    # Space between blocks works like CSS margins: the gap is the larger of the margin below one
    # block and the margin above the next (they collapse), not the two added together.
    last_bottom = 12                                     # the title area's bottom margin
    def add(flowable, top, bottom, keep=False):
        nonlocal last_bottom
        gap = max(last_bottom, top) * k
        if gap:
            story.append(Spacer(1, gap))
        story.append(flowable)
        last_bottom = bottom

    for n in model["notes"]:
        add(Paragraph(escape(n), style(12 * k, leading=12 * k * LH)), 12, 12)
    h2 = style(18 * k, True, leading=18 * k * LH)
    prev = None
    for b in model["blocks"]:
        if b["type"] in ("heading", "banner") and prev not in ("heading", "banner"):
            story.append(CondPageBreak(170))             # never leave a heading alone at the page bottom
        if b["type"] == "heading":
            add(Paragraph(escape(b["text"]), h2), 14, 6)
        elif b["type"] == "banner":
            add(_banner(b, k), 12, 12)
        else:
            add(_table(b, mode, total, k), 14 if prev == "table" else 0, 0)   # tables with no heading between
        prev = b["type"]
    buf = io.BytesIO()
    pad = 6   # reportlab's default frame padding; subtracted so content sits exactly at the margins
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=MARGIN_X - pad, rightMargin=MARGIN_X - pad,
                            topMargin=MARGIN_TOP - pad, bottomMargin=MARGIN_BOTTOM - pad,
                            title=f"{model['title']} - {model['label']}")
    doc.build(story, canvasmaker=_canvas_class(model["footer_left"], model["footer_right"]))
    return buf.getvalue()
