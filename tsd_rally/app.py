import os
import re
from datetime import date, datetime

from flask import Flask, Response, render_template, request
from markupsafe import Markup, escape

import export
import tsd

HERE = os.path.dirname(os.path.abspath(__file__))
# Use ./templates if present, otherwise look next to app.py (flat download)
TPL = os.path.join(HERE, "templates")
app = Flask(__name__, template_folder=TPL if os.path.isdir(TPL) else HERE)

BOLD_ITALIC_RE = re.compile(r"\*\*\*(.+?)\*\*\*")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<![\s*])\*(?![\w*])")


def rich(text):
    """Escape text, then turn ***word*** into bold italic, **word** into bold and *word* into
    italic. Safe against HTML in the input."""
    s = str(escape(text))
    s = BOLD_ITALIC_RE.sub(r"<strong><em>\1</em></strong>", s)
    s = BOLD_RE.sub(r"<strong>\1</strong>", s)
    return Markup(ITALIC_RE.sub(r"<em>\1</em>", s))


def css_text(s):
    """Text for a CSS content:"..." string (drops characters that would end the string)."""
    return Markup(re.sub(r'["\\<>\r\n]', "", s or ""))


def pretty_date(s):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            d = datetime.strptime(s.strip(), fmt).date()
            return f"{d:%A, %B} {d.day}, {d.year}"
        except ValueError:
            pass
    return s or ""   # free text is shown as typed


SAMPLE = r"""[ODOMETER CHECK]
# mileage | instruction | | | suffix | general
0.00 | Start of odometer check at mile marker 0
1.00 | Mile marker 1
2.00 | Mile marker 2
3.00 | Mile marker 3 | | | | End of check
OUTPOINT | 0.00 | Out point: Joe's Diner parking lot | TOD 09:50 | 30 | | Out time is TOD plus car number

[RALLY]
# mileage | instruction | speed | pause | suffix | general
1.20 | **Left** at stop sign onto **Oak Rd** | | | FLR
3.45 | Right at T onto County Rd 5 | 35
@4.20 | Bear left at fork (mileage hidden from participants)
NOTE | Watch for farm equipment on the road. | Note lines have no number or mileage
5.10 | Pass red barn on right | | | | Secret check: barn number
7.80 | Left at Y | 25 | NEXTMIN
8.40 | Checkpoint 1 | | | | CP 1 - hidden
9.50 | Straight at 4-way.\nSpeed zone ahead - watch for signs | 40
12.00 | Enter **transit zone**. No timing. | | | | End of timed section

[TRANSIT]
12.00 | Obey all traffic laws
15.00 | Left at light
NOTE | **No stopping** in the transit zone.
OUTPOINT | 18.00 | Out point: Fire Station | ASSIGNED 10:28 | 35

[RALLY]
18.50 | Right at stop sign | | | FLR
22.00 | Checkpoint 2 | | | | CP 2 - hidden
25.00 | FINISH | | | | Finish
"""


@app.route("/")
def index():
    return render_template("index.html", sample=SAMPLE, today=date.today().isoformat())


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


@app.route("/export", methods=["POST"])
def export_csv():
    """Spreadsheet backup: inputs plus formulas for every calculated value."""
    f = request.form
    errors = []
    text, meta, start, car = read_settings(f, errors)
    segments, perrors = tsd.parse_input(text)
    csv_text = export.build_csv(
        segments, perrors, meta.get("title", f.get("title", "Rally")),
        meta.get("subtitle", f.get("subtitle", "")).strip(),
        meta.get("date", f.get("event_date", "")), start, car)
    name = re.sub(r"\s+", "_", re.sub(r"[^\w\- ]+", "", meta.get("title", f.get("title", "rally")))).strip("_") or "rally"
    return Response(csv_text, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}_spreadsheet.csv"'})


@app.route("/generate", methods=["POST"])
def generate():
    f = request.form
    mode = f.get("mode", "participant")
    whole_min = f.get("resolution") == "minute"
    header_errors = []
    text, meta, start, car = read_settings(f, header_errors)
    segments, errors = tsd.parse_input(text)
    errors = header_errors + errors
    if mode != "measure":   # the measure sheet does no calculations (mileages may be blank)
        tsd.compute(segments, errors, start, car)
    rows = [r for s in segments for r in s.rows]

    for r in rows:   # instruction, then pause, then CAST, then suffix (e.g. FLR)
        instr = re.sub(r"(\s*\\n)+\s*$", "", r.instruction)   # ignore trailing line breaks
        bits = [instr] if instr else []
        if r.next_min:
            bits.append("**Next minute out**")
        elif r.pause:
            bits.append("**Pause %g**" % r.pause)
        if r.is_out and r.out_kind == "tod":
            bits.append("**Out time %s + car number**" % tsd.fmt_tod(r.out_time))
        elif r.is_out and r.out_kind == "assigned":
            bits.append("**Out time assigned**")
        elif r.is_out and r.out_kind == "nextmin":
            bits.append("**Next minute out**")
        if r.speed is not None:
            bits.append("**CAST %g**" % r.speed)
        if r.suffix:
            bits.append(r.suffix)
        r.lines = [rich(l) for l in tsd.split_lines(", ".join(bits))]
        r.plain = rich(" ".join(l for l in tsd.split_lines(r.instruction) if l))
        r.general = rich(r.general)

    for seg in segments:   # rally master banner: how each out time was worked out
        if seg.kind == "rally" and seg.rows and seg.rows[0].is_out and mode == "master":
            o = seg.rows[0]
            if o.out_kind == "tod":
                seg.out_note = f"TOD {tsd.fmt_tod(o.out_time)} + car number {car}"
            elif o.out_kind == "assigned":
                seg.out_note = "assigned to each car; times are shown from this reference"
            elif o.out_kind == "nextmin":
                seg.out_note = "next minute after arrival; times assume arrival at " + tsd.fmt_clock(seg.out_arrival, whole_min)
    n = 0
    for seg in segments:
        for r in seg.rows:   # instruction numbers run on through every section; CPs get none
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
                r.leg_vis = max(r.mileage - vis[i - 1].mileage, 0)
                r.hide_leg = r.hide_mileage or vis[i - 1].hide_mileage

    title = meta.get("title", f.get("title", "Rally"))
    date_text = pretty_date(meta.get("date", f.get("event_date", "")))
    label = {"master": "Rally Master Sheet", "measure": "Measure Sheet"}.get(mode, "Route Instructions")
    return render_template(
        "output.html", segments=segments, errors=errors, mode=mode, label=label,
        title=title, date_text=date_text,
        subtitle=meta.get("subtitle", f.get("subtitle", "")).strip(),
        footer_left=css_text(f"{title} - {label}"), footer_right=css_text(date_text),
        show_leg=bool(f.get("show_leg")),
        clock=lambda t: tsd.fmt_clock(t, whole_min), elapsed=tsd.fmt_elapsed,
        cptime=lambda s: tsd.fmt_ms(s, whole_min),
    )


if __name__ == "__main__":
    app.run(debug=True)
