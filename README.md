# TSD Route Sheets

A small Flask web app that turns a time-speed-distance (TSD) rally route, typed or pasted as plain text, into printable **participant instructions**, **rally master sheets** and **measure sheets**. Edit the text, regenerate, and every time recalculates.

It doesn't create a route for you. It takes a route you already have and keeps the paperwork in step as the route changes.

## Why

- **Easier route maintenance.** Clubs often keep routes in spreadsheets where the time formulas depend on the mileage difference between rows, so adding or deleting a row means fixing formulas. Here a route is just lines of text: add, move or delete a line and everything recalculates.
- **Easier for first-time rally masters.** A built-in tutorial walks through a simple route (start, turn-by-turn instructions, finish) to a full set of sheets.

## Features

- Plain-text route input, one instruction per line (also load `.txt` / `.csv`, save as text or CSV)
- Participant, rally master and measure outputs, printable or as a **PDF** (US Letter)
- Odometer check, timed rally sections, transit zones and notes
- Speed changes (CAST), pauses, suffix text, checkpoints, and out points (`TOD` + car number, `NEXTMIN`)
- Mileages entered to 1/1000 mile are kept as typed and calculated at 1/100 mile
- Times in seconds or decimal minutes (1/100 min)
- **Spreadsheet download**: a CSV with Excel/Sheets formulas for every calculated value, so a route can be backed up and edited outside the app
- Bold / italic markup, multi-line instructions, large-print layout for reading in a moving vehicle
- In-app help and tutorial (`/tutorial`)

## Quick start

Requires Python 3.10 or newer.

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. Click **Tutorial** for a walkthrough.

## Input format

One item per line, fields separated by `|` (trailing fields optional):

```
mileage | instruction | speed | pause | suffix | general
```

```
0.00 | START: Leave parking lot, turn right on Main St | 30
1.20 | Left at stop sign onto Oak Rd
3.45 | Right at T onto County Rd 5 | 35
7.80 | Left at Y | 25 | 30
8.40 | Checkpoint 1 | | | | CP 1
12.00 | FINISH
```

`[ODOMETER CHECK]`, `[RALLY]` and `[TRANSIT]` section headers, `OUTPOINT` and `NOTE` lines, and markers such as `@` (master-only mileage) and `**bold**` are covered in the in-app **Help** section.

## Project layout

| File | Purpose |
|---|---|
| `app.py` | Flask routes, example routes |
| `tsd.py` | Parsing and time/speed/distance calculations |
| `sheet.py` | Builds the printable sheet as a data model (shared by HTML and PDF) |
| `pdf_output.py` | PDF output (reportlab) |
| `export.py` | Spreadsheet CSV with formulas |
| `templates/` | Main page, printable output, tutorial |
| `fonts/` | Bundled Liberation Sans for the PDF (see `fonts/LICENSE-LiberationSans.txt`) |

## Deployment

Any WSGI host works. For Passenger (e.g. cPanel "Setup Python App"), use a `passenger_wsgi.py` such as:

```python
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from app import app as application
```

Install `requirements.txt` into the app's virtual environment. If `reportlab` is missing, only the PDF download is affected.

## License

Add a license file before publishing. The bundled fonts keep their own license in `fonts/`.
