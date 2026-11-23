import os
import re
from datetime import date

from flask import Flask, Response, jsonify, render_template, request, send_from_directory, url_for
from markupsafe import Markup, escape

import export
import sheet
import tsd

HERE = os.path.dirname(os.path.abspath(__file__))
# Use ./templates if present, otherwise look next to app.py (flat download)
TPL = os.path.join(HERE, "templates")
app = Flask(__name__, template_folder=TPL if os.path.isdir(TPL) else HERE)
app.config["MAX_FORM_MEMORY_SIZE"] = 2_000_000

def rich(text):
    """Escape text, then turn ***word*** into bold italic, **word** into bold and *word* into
    italic. Safe against HTML in the input."""
    return Markup(sheet.apply_markup(str(escape(text)), r"<strong><em>\1</em></strong>",
                                     r"<strong>\1</strong>", r"<em>\1</em>"))


app.jinja_env.filters["rich"] = rich


def css_text(s):
    """Text for a CSS content:"..." string (drops characters that would end the string)."""
    return Markup(re.sub(r'["\\<>\r\n]', "", s or ""))


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
OUTPOINT | 18.00 | Out point: Fire Station | TOD 10:28 | 35

[RALLY]
18.50 | Right at stop sign | | | FLR
22.00 | Checkpoint 2 | | | | CP 2 - hidden
25.00 | FINISH | | | | Finish
"""


SIMPLE = r"""0.00 | START: Leave parking lot, turn right on Main St | 30
1.20 | Left at stop sign onto Oak Rd
3.45 | Right at T onto County Rd 5
5.10 | Pass red barn on right
7.80 | Left at Y
9.50 | Straight at 4-way
12.00 | FINISH
"""

EXTRAS = r"""0.00 | START: Leave parking lot, turn right on Main St | 30
1.20 | **Left** at stop sign onto **Oak Rd** | | | FLR
3.45 | Right at T onto County Rd 5 | 35
NOTE | Watch for farm equipment on the road.
5.10 | Pass red barn on right | | | | Secret check: barn number
7.80 | Left at Y | 25 | 30
9.50 | Straight at 4-way.\nSpeed zone ahead - watch for signs | 40
12.00 | FINISH
"""

CHECKPOINT = EXTRAS.replace("9.50 | Straight", "8.40 | Checkpoint 1 | | | | CP 1\n9.50 | Straight")

MEASURE = r""" | START: Leave parking lot, turn right on Main St | 30
 | Left at stop sign onto Oak Rd
 | Right at T onto County Rd 5 | 35
 | Pass red barn on right
 | Left at Y | 25 | 30
 | Checkpoint 1 | | | | CP 1
 | Straight at 4-way
 | FINISH
"""

# Example routes: used by the tutorial and by /?example=name (which fills the form with them)
EXAMPLES = {
    "sample": {"text": SAMPLE, "title": "My TSD Rally", "subtitle": "Autumn Classic - Route 2", "start_time": "09:30:00"},
    "simple": {"text": SIMPLE, "title": "Simple Route", "subtitle": "Tutorial example", "start_time": "09:30:00"},
    "extras": {"text": EXTRAS, "title": "Simple Route", "subtitle": "Tutorial example", "start_time": "09:30:00"},
    "checkpoint": {"text": CHECKPOINT, "title": "Simple Route", "subtitle": "Tutorial example", "start_time": "09:30:00"},
    "measure": {"text": MEASURE, "title": "Simple Route", "subtitle": "Tutorial example", "start_time": "09:30:00"},
}


@app.route("/")
def index():
    ex = EXAMPLES.get(request.args.get("example", ""), EXAMPLES["sample"])
    return render_template("index.html", sample=ex["text"], today=date.today().isoformat(), form=ex)


@app.route("/tutorial")
def tutorial():
    def preview(name, mode):
        e = EXAMPLES[name]
        return render_output({"data": e["text"], "mode": mode, "title": e["title"], "subtitle": e["subtitle"],
                              "start_time": e["start_time"], "car": "1"}, preview=True)

    segs, errs = tsd.parse_input(CHECKPOINT)
    tsd.compute(segs, errs, tsd.parse_clock("09:30:00"), 1)
    cp = next(r for s in segs for r in s.rows if r.is_cp)
    facts = {"cp_time": tsd.fmt_ms(cp.cp_sec), "cp_time_dec": tsd.fmt_ms(cp.cp_sec, True)}
    previews = {
        "simple_participant": preview("simple", "participant"), "simple_master": preview("simple", "master"),
        "extras_participant": preview("extras", "participant"),
        "checkpoint_master": preview("checkpoint", "master"), "checkpoint_participant": preview("checkpoint", "participant"),
        "sample_master": preview("sample", "master"), "sample_participant": preview("sample", "participant"),
        "measure_sheet": preview("measure", "measure"),
    }
    return render_template("tutorial.html", ex={k: v["text"] for k, v in EXAMPLES.items()},
                           previews=previews, facts=facts)


@app.route("/favicon.ico")
def favicon():
    """Browsers ask for /favicon.ico at the site root even when no <link> points there."""
    return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/x-icon")


@app.route("/site.webmanifest")
def webmanifest():
    icon = lambda size: {"src": url_for("static", filename=f"android-chrome-{size}x{size}.png"),
                         "sizes": f"{size}x{size}", "type": "image/png"}
    return jsonify({"name": "TSD Route Sheets", "short_name": "Route Sheets",
                    "icons": [icon(192), icon(512)], "theme_color": "#ffffff",
                    "background_color": "#ffffff", "display": "browser"})


@app.route("/pdf", methods=["POST"])
def pdf():
    """The printable sheet as a PDF file (same layout as the print output)."""
    try:
        import pdf_output            # imported here so a missing reportlab only affects this page
    except ImportError:
        return Response("PDF output needs the reportlab package: pip install reportlab", status=501,
                        mimetype="text/plain")
    model = sheet.build_sheet(request.form)
    name = re.sub(r"\s+", "_", re.sub(r"[^\w\- ]+", "", f"{model['title']} {model['label']}")).strip("_") or "sheet"
    return Response(pdf_output.build_pdf(model), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})


@app.route("/export", methods=["POST"])
def export_csv():
    """Spreadsheet backup: inputs plus formulas for every calculated value."""
    f = request.form
    errors = []
    text, meta, start, car = sheet.read_settings(f, errors)
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
    return render_output(request.form)


FORM_KEYS = ("data", "mode", "title", "subtitle", "event_date", "start_time", "car", "resolution", "show_leg",
             "hide_headings", "logo")


def render_output(f, preview=False):
    """Build a printable sheet from form-like data (a dict works). preview=True hides the
    Print button so the sheet can be embedded in the tutorial."""
    model = sheet.build_sheet(f)
    model["footer_left"] = css_text(model["footer_left"])
    model["footer_right"] = css_text(model["footer_right"])
    fields = {k: f.get(k) for k in FORM_KEYS if f.get(k) is not None}
    return render_template("output.html", preview=preview, fields=fields, **model)


if __name__ == "__main__":
    app.run(debug=True)
