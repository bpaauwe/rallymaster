"""Spreadsheet (CSV) export of a route, with Excel/Sheets formulas for every calculated value.

Layout (1-based rows): 1-5 title area (values in column B), 6 warnings, 7 column headers,
data from row 8. Columns A-M are the inputs; N-S are the sheet's display columns; T-AE are
numeric helper columns (seconds). Everything from N onward is a formula, so changing a
speed, pause, mileage, start time or car number recalculates the instruction text and times.
"""
import csv
import io

import tsd

FIRST = 8                      # first data row
HEADERS = [
    "Type", "Section", "#", "Mileage", "Hide mileage", "Instruction", "Speed", "Pause", "Suffix",
    "General", "Checkpoint", "Out type", "Out clock (minutes if REL)",
    "Full instruction", "Time to instr.", "Elapsed", "Perfect time", "Out time", "CP time",
    "Speed in effect (mph)", "Last mileage", "Leg distance", "Time to instr. (sec)",
    "Segment start clock (sec)", "Arrival elapsed (sec)", "Pause (sec)", "Departure elapsed (sec)",
    "Arrival clock (sec)", "Departure clock (sec)", "Last CP elapsed (sec)", "CP time (sec)",
]
HELP = [
    "Edit the input columns A-M (and B4 start time, B5 car number). Columns N onward are formulas and recalculate. Mileages are kept as entered; calculations round them to 0.01 mile.",
    "Type: SECTION, LINE, NOTE or OUTPOINT. Section: ODO, TRANSIT or RALLY. Checkpoint / Hide mileage: Y or blank.",
    "Pause: seconds, or NEXTMIN for a next-minute out (Richta: Flying Start Next Minute). Speed: mph, applies from that line on (CAST).",
    "Out type (OUTPOINT rows): TOD (out clock + car number minutes), ASSIGNED, NEXTMIN, FIXED, or REL (minutes after previous section).",
    "Markup in text: **bold**, *italic*, and \\n for a new line. Columns O-S are display text; T-AE are the seconds-based helpers.",
]


def _num(v):
    return "" if v is None else (f"{v:.4f}".rstrip("0").rstrip("."))


def _safe(s):
    """Stop spreadsheet programs from treating typed text as a formula."""
    s = s or ""
    return " " + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _hms(x):        # elapsed seconds -> h:mm:ss text
    r = f"ROUND({x},0)"
    return f'INT({r}/3600)&":"&TEXT(MOD(INT({r}/60),60),"00")&":"&TEXT(MOD({r},60),"00")'


def _clk(x):        # clock seconds -> hh:mm:ss text
    r = f"ROUND({x},0)"
    return f'TEXT(INT(MOD({r},86400)/3600),"00")&":"&TEXT(MOD(INT({r}/60),60),"00")&":"&TEXT(MOD({r},60),"00")'


def _formulas(r):
    """The N..AE formulas for data row r (row r-1 is the row above, or the header for the first)."""
    p = r - 1
    sec = lambda c: f"ROUND({c}*86400,0)"
    start = "ROUND($B$4*86400,0)"
    ref = f"IF(ISNUMBER(AC{p}),AC{p},{start})"          # when the previous timed section ended
    timed = f'AND(B{r}="RALLY",OR(A{r}="LINE",A{r}="OUTPOINT"))'
    cp_row = f'AND(A{r}="LINE",K{r}="Y",B{r}="RALLY")'
    pause_bit = (f'IF(H{r}="NEXTMIN","Next minute out",'
                 f'IF(ISNUMBER(H{r}),IF(H{r}>0,"Pause "&H{r},""),""))')
    out_bit = (f'IF(A{r}="OUTPOINT",IF(L{r}="TOD","Out time "&INT({sec("M"+str(r))}/3600)&":"&'
               f'TEXT(MOD(INT({sec("M"+str(r))}/60),60),"00")&" + car number",'
               f'IF(L{r}="ASSIGNED","Out time assigned",IF(L{r}="NEXTMIN","Next minute out",""))),"")')
    cast_bit = f'IF(G{r}<>"","CAST "&G{r},"")'
    base = (f'IF(A{r}<>"OUTPOINT",IF(ISNUMBER(X{p}),X{p},{start}),'
            f'IF(L{r}="TOD",{sec("M"+str(r))}+$B$5*60,'
            f'IF(L{r}="FIXED",{sec("M"+str(r))},'
            f'IF(L{r}="REL",{ref}+M{r}*60,'
            f'IF(L{r}="NEXTMIN",(INT(ROUND(IF(M{r}<>"",M{r}*86400,{ref}),0)/60)+1)*60,'
            f'IF(M{r}<>"",{sec("M"+str(r))},{ref}))))))')
    return {
        "C": f'IF(A{r}="OUTPOINT","OUT",IF(A{r}="LINE",IF(K{r}="Y","CP",'
             f'COUNTIFS(A${FIRST}:A{r},"LINE",K${FIRST}:K{r},"<>Y")),""))',
        "N": (f'IF(OR(A{r}="LINE",A{r}="OUTPOINT",A{r}="NOTE"),'
              f'MID(IF(F{r}<>"",", "&F{r},"")&IF({pause_bit}<>"",", "&{pause_bit},"")'
              f'&IF({out_bit}<>"",", "&{out_bit},"")&IF({cast_bit}<>"",", "&{cast_bit},"")'
              f'&IF(I{r}<>"",", "&I{r},""),3,9999),"")'),
        "O": f'IF({timed},{_hms("W"+str(r))},"")',
        "P": f'IF({timed},{_hms("Y"+str(r))},"")',
        "Q": f'IF({timed},{_clk("AB"+str(r))}&IF(K{r}="Y"," (CP)",""),"")',
        "R": f'IF(AND({timed},A{r}="LINE",Z{r}>0),{_clk("AC"+str(r))},"")',
        "S": f'IF(AE{r}="","",INT(ROUND(AE{r},0)/60)&":"&TEXT(MOD(ROUND(AE{r},0),60),"00"))',
        "T": f'IF(G{r}<>"",G{r},IF(ISNUMBER(T{p}),T{p},""))',
        "U": f'IF(AND(OR(A{r}="LINE",A{r}="OUTPOINT"),ISNUMBER(D{r})),ROUND(D{r},2),IF(ISNUMBER(U{p}),U{p},""))',
        "V": f'IF(AND(B{r}="RALLY",A{r}="LINE",ISNUMBER(D{r}),ISNUMBER(U{p})),ROUND(MAX(ROUND(D{r},2)-U{p},0),2),0)',
        "W": f'IF(AND(V{r}>0,ISNUMBER(T{p})),INT(V{r}/T{p}*3600),0)',
        "X": base,
        "Y": f'IF(A{r}="OUTPOINT",0,IF(ISNUMBER(AA{p}),AA{p},0)+W{r})',
        "Z": (f'IF(H{r}="NEXTMIN",(INT(ROUND(AB{r},0)/60)+1)*60-AB{r},'
              f'IF(ISNUMBER(H{r}),H{r},0))'),
        "AA": f"Y{r}+Z{r}",
        "AB": f"X{r}+Y{r}",
        "AC": f"X{r}+AA{r}",
        "AD": f'IF(A{r}="OUTPOINT",0,IF({cp_row},Y{r},IF(ISNUMBER(AD{p}),AD{p},0)))',
        "AE": f'IF({cp_row},Y{r}-IF(ISNUMBER(AD{p}),AD{p},0),"")',
    }


LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R",
           "S", "T", "U", "V", "W", "X", "Y", "Z", "AA", "AB", "AC", "AD", "AE"]


def _row(r, inputs):
    f = _formulas(r)
    cells = []
    for letter in LETTERS:
        if letter in f:
            cells.append("=" + f[letter])
        else:
            cells.append(inputs.get(letter, ""))
    return cells


def _clock_text(sec):
    return tsd.fmt_clock(sec)


def build_csv(segments, errors, title, subtitle, date_text, start_sec, car):
    rows = [
        ["Title", _safe(title), "", HELP[0]],
        ["Subtitle", _safe(subtitle), "", HELP[1]],
        ["Date", _safe(date_text), "", HELP[2]],
        ["Start time", _clock_text(start_sec), "", HELP[3]],
        ["Car number", car, "", HELP[4]],
        ["WARNING: not exported: " + " | ".join(errors) if errors else ""],
        HEADERS,
    ]
    r = FIRST
    for seg in segments:
        kind = {"odo": "ODO", "transit": "TRANSIT", "rally": "RALLY"}[seg.kind]
        rows.append(_row(r, {"A": "SECTION", "B": kind, "F": seg.title}))
        r += 1
        for x in seg.rows:
            inp = {"B": kind, "F": _safe(x.instruction), "J": _safe(x.general)}
            if x.is_note:
                inp["A"] = "NOTE"
            else:
                inp["A"] = "OUTPOINT" if x.is_out else "LINE"
                inp["D"] = x.mileage_raw        # exactly as entered (e.g. 3.456)
                inp["E"] = "Y" if x.hide_mileage else ""
                inp["G"] = _num(x.speed)
                inp["I"] = _safe(x.suffix)
                inp["K"] = "Y" if x.is_cp else ""
                if x.next_min:
                    inp["H"] = "NEXTMIN"
                elif x.pause:
                    inp["H"] = _num(x.pause)
                if x.is_out:
                    inp["L"] = x.out_kind.upper()
                    if x.out_kind == "rel":
                        inp["M"] = _num(x.out_rel / 60)
                    elif x.out_time is not None:
                        inp["M"] = _clock_text(x.out_time)
            rows.append(_row(r, inp))
            r += 1
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerows(rows)
    return "\ufeff" + out.getvalue()      # BOM so Excel reads UTF-8
