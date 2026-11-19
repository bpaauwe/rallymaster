import os
import re
from datetime import date, datetime

from flask import Flask, render_template, request
from markupsafe import Markup, escape

import tsd

HERE = os.path.dirname(os.path.abspath(__file__))
# Use ./templates if present, otherwise look next to app.py (flat download)
TPL = os.path.join(HERE, "templates")
app = Flask(__name__, template_folder=TPL if os.path.isdir(TPL) else HERE)

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def rich(text):
    """Escape text, then turn **word** into bold. Safe against HTML in the input."""
    return Markup(BOLD_RE.sub(r"<strong>\1</strong>", str(escape(text))))


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
OUTPOINT | 0.00 | Out point: Joe's Diner parking lot.\nOut time is 9:30 + car number + 20 minutes | +20 | 30 | | Car 1 out at 9:51

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
OUTPOINT | 18.00 | Out point: Fire Station.\nYou have **15 minutes** from the start of the zone | +15 | 35

[RALLY]
18.50 | Right at stop sign | | | FLR
22.00 | Checkpoint 2 | | | | CP 2 - hidden
25.00 | FINISH | | | | Finish
"""


@app.route("/")
def index():
    return render_template("index.html", sample=SAMPLE, today=date.today().isoformat())


@app.route("/generate", methods=["POST"])
def generate():
    f = request.form
    mode = f.get("mode", "participant")
    whole_min = f.get("resolution") == "minute"
    # Header lines in the text (Title:, Subtitle:, Date:, Start time:) override the form fields
    meta, text = tsd.extract_header(f.get("data", ""))
    segments, errors = tsd.parse_input(text)
    try:
        start = tsd.parse_time_text(meta["start"]) if "start" in meta else None
    except ValueError as e:
        errors.append(f"Header: {e}; using the form's start time")
        start = None
    if start is None:
        start = tsd.parse_clock(f.get("start_time") or "09:00:00")
    if mode != "measure":   # the measure sheet does no calculations (mileages may be blank)
        tsd.compute(segments, errors, start)
    rows = [r for s in segments for r in s.rows]

    for r in rows:   # instruction, then pause, then CAST, then suffix (e.g. FLR)
        instr = re.sub(r"(\s*\\n)+\s*$", "", r.instruction)   # ignore trailing line breaks
        bits = [instr] if instr else []
        if r.next_min:
            bits.append("**Next minute out**")
        elif r.pause:
            bits.append("**Pause %g**" % r.pause)
        if r.speed is not None:
            bits.append("**CAST %g**" % r.speed)
        if r.suffix:
            bits.append(r.suffix)
        r.lines = [rich(l) for l in tsd.split_lines(", ".join(bits))]
        r.plain = rich(" ".join(l for l in tsd.split_lines(r.instruction) if l))
        r.general = rich(r.general)

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

    return render_template(
        "output.html", segments=segments, errors=errors, mode=mode,
        label={"master": "Rally Master Sheet", "measure": "Measure Sheet"}.get(mode, "Route Instructions"),
        title=meta.get("title", f.get("title", "Rally")),
        subtitle=meta.get("subtitle", f.get("subtitle", "")).strip(),
        date_text=pretty_date(meta.get("date", f.get("event_date", ""))),
        show_leg=bool(f.get("show_leg")),
        clock=lambda t: tsd.fmt_clock(t, whole_min), elapsed=tsd.fmt_elapsed,
        cptime=lambda s: tsd.fmt_ms(s, whole_min),
    )


if __name__ == "__main__":
    app.run(debug=True)
