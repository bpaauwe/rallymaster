"""The printable sheet as a plain data model.

build_sheet() turns the form fields into a dict of headings, banners and tables. The HTML page
(templates/output.html) and the PDF (pdf_output.py) both draw from this one model, so they
always show the same text.
"""
import re
from datetime import datetime

import tsd

# **bold**, *italic* and ***bold italic*** markup (used by the HTML page and the PDF)
BOLD_ITALIC_RE = re.compile(r"\*\*\*(.+?)\*\*\*")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<![\s*])\*(?![\w*])")


def apply_markup(escaped, bold_italic, bold, italic):
    """Replace the markup in already-escaped text. Each argument is a re.sub template using \\1."""
    s = BOLD_ITALIC_RE.sub(bold_italic, escaped)
    s = BOLD_RE.sub(bold, s)
    return ITALIC_RE.sub(italic, s)


def pretty_date(s):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            d = datetime.strptime(s.strip(), fmt).date()
            return f"{d:%A, %B} {d.day}, {d.year}"
        except ValueError:
            pass
    return s or ""   # free text is shown as typed


def read_settings(f, errors):
    """Header lines in the text (Title:, Subtitle:, Date:, Start time:) override the form fields.
    Returns (text without header lines, meta, start seconds, car number)."""
    meta, text = tsd.extract_header(f.get("data", ""))
    try:
        start = tsd.parse_time_text(meta["start"]) if "start" in meta else None
    except ValueError as e:
        errors.append(f"Header: {e}; using the form's start time")
        start = None
    if start is None:
        start = tsd.parse_clock(f.get("start_time") or "09:00:00")
    try:
        car = max(int(float(f.get("car") or 0)), 0)
    except ValueError:
        car = 0
    return text, meta, start, car


def _mile_text(r, mode):
    if r.is_note or r.mileage is None:
        return ""
    if r.hide_mileage and mode == "participant":
        return ""
    return "%.2f" % r.mileage + ("*" if r.hide_mileage else "")


def build_sheet(f):
    mode = f.get("mode", "participant")
    decimal = f.get("resolution") in ("decimal", "minute")   # decimal minutes (1/100 min)
    show_leg = bool(f.get("show_leg"))
    header_errors = []
    text, meta, start, car = read_settings(f, header_errors)
    segments, errors = tsd.parse_input(text)
    errors = header_errors + errors
    if mode != "measure":   # the measure sheet does no calculations (mileages may be blank)
        tsd.compute(segments, errors, start, car)

    clock = lambda t: tsd.fmt_clock(t, decimal)
    elapsed = lambda s: tsd.fmt_elapsed(s, decimal)
    cptime = lambda s: "" if s is None else tsd.fmt_ms(s, decimal)

    # Text of each instruction: instruction, then pause, out time, CAST, suffix (e.g. FLR)
    for seg in segments:
        for r in seg.rows:
            instr = re.sub(r"(\s*\\n)+\s*$", "", r.instruction)   # ignore trailing line breaks
            bits = [instr] if instr else []
            if r.next_min:
                bits.append("**Next minute out**")
            elif r.pause:
                bits.append("**Pause %g**" % r.pause)
            if r.is_out and r.out_kind == "tod":
                bits.append("**Out time %s + car number**" % tsd.fmt_tod(r.out_time))
            elif r.is_out and r.out_kind == "nextmin":
                bits.append("**Next minute out**")
            if r.speed is not None:
                bits.append("**CAST %g**" % r.speed)
            if r.suffix:
                bits.append(r.suffix)
            r.raw_lines = tsd.split_lines(", ".join(bits))

    # Instruction numbers run on through every section; checkpoints and notes get none
    n = 0
    for seg in segments:
        for r in seg.rows:
            r.leg_vis, r.hide_leg = r.leg_dist, r.hide_mileage
            if r.is_note:
                r.num = ""
            elif r.is_out:
                r.num = "OUT"
            elif r.is_cp:
                r.num = "CP"
            else:
                n += 1
                r.num = n
        # Participant legs skip the hidden checkpoint rows, and a leg next to a hidden mileage
        # would give that mileage away.
        vis = [r for r in seg.rows if not r.is_cp and not r.is_note and r.mileage is not None]
        for i, r in enumerate(vis if mode != "measure" else []):
            if i > 0:
                r.leg_vis = round(max(r.mileage - vis[i - 1].mileage, 0), 2)
                r.hide_leg = r.hide_mileage or vis[i - 1].hide_mileage

    master = mode == "master"
    has_leg = master or (mode == "participant" and show_leg)
    min_ = " (min)" if decimal else ""
    blocks = []
    for seg in segments:
        if seg.kind != "rally":
            blocks.append({"type": "heading", "text": seg.title + (" (not timed)" if master else "")})
            if not seg.rows:
                continue
            head = [{"t": "#", "cls": "c"}, {"t": "Mileage"}, {"t": "Instruction"}] + ([{"t": "Notes"}] if master else [])
            rows = []
            for r in seg.rows:
                cells = [{"t": str(r.num), "cls": "c"}, {"t": _mile_text(r, mode), "cls": "n"},
                         {"lines": r.raw_lines}]
                if master:
                    cells.append({"t": r.general, "rich": True})
                rows.append({"cls": "", "cells": cells})
            blocks.append({"type": "table", "head": head, "rows": rows})
            continue
        first = seg.rows[0]
        shown = seg.rows if mode in ("master", "measure") else [r for r in seg.rows if not r.is_cp]
        if len(segments) > 1:
            blocks.append({"type": "heading", "text": "Rally"})
        if first.is_out and master:
            if first.out_kind == "tod":
                note = f"TOD {tsd.fmt_tod(first.out_time)} + car number {car}"
            elif first.out_kind == "nextmin":
                note = "next minute after arrival; times assume arrival at " + clock(seg.out_arrival)
            else:
                note = ""
            blocks.append({"type": "banner", "parts": [
                {"label": "Out point:", "text": " ".join(l for l in tsd.split_lines(first.instruction) if l), "rich": True},
                {"label": "Out time:", "text": clock(seg.base) + (f" ({note})" if note else "")},
                {"label": "First leg speed:", "text": "%g mph" % first.speed}]})
        head = [{"t": "#", "cls": "c"}, {"t": "Mileage"}]
        if has_leg:
            head.append({"t": "Leg"})
        head.append({"t": "Instruction"})
        if master:
            head += [{"t": "Time to instr." + min_}, {"t": "Elapsed" + min_}, {"t": "Perfect time"},
                     {"t": "Out time"}, {"t": "CP time" + min_}, {"t": "Notes"}]
        rows = []
        for r in shown:
            cells = [{"t": str(r.num), "cls": "c"}, {"t": _mile_text(r, mode), "cls": "n"}]
            if has_leg:
                blank = r.is_note or r.mileage is None or (mode == "participant" and r.hide_leg)
                leg = r.leg_dist if master else r.leg_vis
                cells.append({"t": "" if blank else "%.2f" % leg, "cls": "n"})
            cells.append({"lines": r.raw_lines})
            if master:
                timed = not r.is_note
                cells += [
                    {"t": elapsed(r.leg_sec) if timed else "", "cls": "n"},
                    {"t": elapsed(r.arrive) if timed else "", "cls": "n"},
                    {"t": (clock(r.arrive_clock) + (" (CP)" if r.is_cp else "")) if timed else "", "cls": "n"},
                    {"t": clock(r.depart_clock) if timed and r.depart != r.arrive else "", "cls": "n"},
                    {"t": cptime(r.cp_sec) if r.is_cp else "", "cls": "n"},
                    {"t": r.general, "rich": True},
                ]
            cls = "out" if r.is_out else ("cp" if r.is_cp and mode in ("master", "measure") else "")
            rows.append({"cls": cls, "cells": cells})
        blocks.append({"type": "table", "head": head, "rows": rows})

    title = meta.get("title", f.get("title", "Rally"))
    date_text = pretty_date(meta.get("date", f.get("event_date", "")))
    label = {"master": "Rally Master Sheet", "measure": "Measure Sheet"}.get(mode, "Route Instructions")
    notes = []
    if mode in ("master", "measure"):
        notes.append("* = mileage is not shown to participants")
    if master and decimal:
        notes.append("Decimal minutes: clock times are hh:mm.hh (hundredths of a minute); durations are in minutes.")
    return {
        "mode": mode, "label": label, "title": title,
        "subtitle": meta.get("subtitle", f.get("subtitle", "")).strip(),
        "date_text": date_text, "notes": notes, "errors": errors, "blocks": blocks,
        "footer_left": f"{title} - {label}", "footer_right": date_text,
    }
