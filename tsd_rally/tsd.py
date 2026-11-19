"""TSD rally calculations. Distances in miles, speeds in mph, pauses in seconds."""
import re
from dataclasses import dataclass, field

CP_RE = re.compile(r"\b(cp|checkpoint|check point)\b", re.I)
UNTIMED = ("odo", "transit")                      # sections with no speeds, timing or checkpoints
TITLES = {"odo": "Odometer Check", "transit": "Transit Zone", "rally": "Rally"}
NEXTMIN = {"NEXTMIN", "NM", "NEXT MINUTE", "NEXT-MINUTE"}


@dataclass
class Row:
    line_no: int
    mileage: float
    instruction: str = ""
    speed: float | None = None
    pause: float = 0.0           # seconds (computed for NEXTMIN)
    suffix: str = ""             # participant-visible text appended after pause and CAST (e.g. FLR)
    general: str = ""            # rally master notes / checkpoint flag (never on participant output)
    leg_dist: float = 0.0
    leg_sec: float = 0.0
    arrive: float = 0.0          # elapsed seconds since segment start, at arrival
    depart: float = 0.0          # elapsed seconds after any pause
    arrive_clock: float = 0.0    # absolute clock seconds
    depart_clock: float = 0.0
    is_cp: bool = False
    master_only: bool = False
    hide_mileage: bool = False   # mileage shown on rally master output only
    hide_leg: bool = False
    next_min: bool = False       # Richta next-minute out: wait for the next whole minute
    is_out: bool = False         # out point that starts a timed leg
    out_time: float | None = None   # absolute clock seconds, or
    out_rel: float | None = None    # seconds after the start of the preceding section


@dataclass
class Segment:
    kind: str                    # 'odo' | 'transit' | 'rally'
    rows: list = field(default_factory=list)
    has_out: bool = False
    base: float = 0.0            # absolute clock seconds at the start of a timed segment
    line_no: int = 0

    @property
    def title(self):
        return TITLES[self.kind]


def parse_pause(text: str) -> float:
    """Accepts seconds ('30'), 'mm:ss', or '30s' / '2m'."""
    t = text.strip().lower()
    if not t:
        return 0.0
    if ":" in t:
        m, s = t.split(":", 1)
        return int(m) * 60 + float(s)
    if t.endswith("m"):
        return float(t[:-1]) * 60
    return float(t.rstrip("s"))


def parse_clock(text: str) -> float:
    parts = [float(p) for p in (text or "00:00:00").split(":")]
    parts += [0] * (3 - len(parts))
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_out_time(text: str):
    """'09:51:00' -> (clock seconds, None); '+20' -> (None, 1200) = 20 min after section start."""
    t = text.strip()
    if t.startswith("+"):
        return None, float(t[1:]) * 60
    return parse_clock(t), None


def _mile(text):
    """'4.20' -> (4.2, False); '@4.20' -> (4.2, True) = mileage for rally master only."""
    t = text.strip()
    return float(t.lstrip("@")), t.startswith("@")


def _finish(row):
    g = row.general
    if g.startswith("@"):                 # legacy marker; general is master-only anyway
        row.master_only, g = True, g[1:].strip()
    row.is_cp = bool(CP_RE.search(g))
    row.general = g
    return row


def parse_input(text: str):
    """Returns (segments, errors).

    Sections: [ODOMETER CHECK], [TRANSIT], [RALLY]  (lines before any header are rally lines)
    Line:      mileage | instruction | speed | pause | suffix | general
    Out point: OUTPOINT | mileage | instruction | out time | speed | suffix | general
               out time = clock time (09:51:00) or +minutes after the section starts (+20)
    A leading @ on a mileage shows it on the rally master output only.
    Blank lines and lines starting with # are skipped."""
    segments, errors = [], []
    cur = None

    def begin(kind, n):
        nonlocal cur
        if kind == "rally" and cur is not None and cur.kind == "rally":
            return                        # consecutive rally headers continue the same timed run
        cur = Segment(kind, line_no=n)
        segments.append(cur)

    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"\[(.*)\]", line)
        if m:
            name = m.group(1).lower()
            if "odo" in name:
                begin("odo", n)
            elif "transit" in name:
                begin("transit", n)
            elif "rally" in name:
                begin("rally", n)
            else:
                errors.append(f"Line {n}: unknown section '{line}'")
            continue
        parts = [p.strip() for p in line.split("|")]
        try:
            if parts[0].upper() == "OUTPOINT":
                parts += [""] * (7 - len(parts))
                if not parts[3] or not parts[4]:
                    raise ValueError("OUTPOINT needs an out time and a speed")
                speed = float(parts[4])
                if speed <= 0:
                    raise ValueError("speed must be > 0")
                mile, hide = _mile(parts[1])
                t, rel = parse_out_time(parts[3])
                out = _finish(Row(n, mile, parts[2], speed=speed, suffix=parts[5], general=parts[6],
                                  is_out=True, out_time=t, out_rel=rel, hide_mileage=hide))
                if cur is not None and cur.kind in UNTIMED:
                    cur.has_out = True
                cur = Segment("rally", rows=[out], line_no=n)   # an out point always starts a timed leg
                segments.append(cur)
                continue
            parts += [""] * (6 - len(parts))
            if cur is None:
                begin("rally", n)
            mile, hide = _mile(parts[0])
            row = Row(n, mile, parts[1], suffix=parts[4], general=parts[5], hide_mileage=hide)
            if cur.kind in UNTIMED:
                if parts[2] or parts[3]:
                    errors.append(f"Line {n}: speed/pause ignored in {cur.title.lower()}")
                _finish(row)
                if row.is_cp:
                    errors.append(f"Line {n}: checkpoints are not allowed in a {cur.title.lower()}")
                    row.is_cp = False
                cur.rows.append(row)
                continue
            if parts[3].upper() in NEXTMIN:
                row.next_min = True
            else:
                row.pause = parse_pause(parts[3])
            row.speed = float(parts[2]) if parts[2] else None
            if row.speed is not None and row.speed <= 0:
                raise ValueError("speed must be > 0")
            _finish(row)
            if row.is_cp and (row.speed is not None or row.pause or row.next_min or row.suffix):
                errors.append(f"Line {n}: checkpoint lines are hidden from participants, so its "
                              f"speed/pause/suffix will not be printed for them")
            cur.rows.append(row)
        except ValueError as e:
            errors.append(f"Line {n}: {e} -> '{raw}'")
    for seg in segments:
        if seg.kind in UNTIMED and not seg.has_out:
            errors.append(f"Line {seg.line_no}: {seg.title} has no OUTPOINT to end it")
    segments = [s for s in segments if s.rows or s.kind in UNTIMED]
    return segments, errors


def compute(segments, errors, start=0.0):
    """Fill in leg and clock times for each timed (rally) segment. Odometer checks and
    transit zones are never calculated; their OUTPOINT sets the next timed segment's clock.
    `start` is the clock (seconds) that relative out times in the first section count from."""
    ref = start
    for seg in segments:
        if seg.kind != "rally":
            continue
        first = seg.rows[0]
        if first.is_out:
            seg.base = first.out_time if first.out_rel is None else ref + first.out_rel
        else:
            seg.base = ref
        speed, elapsed, prev = None, 0.0, None
        for r in seg.rows:
            if prev is not None:
                if r.mileage < prev:
                    errors.append(f"Line {r.line_no}: mileage {r.mileage} is less than previous {prev}")
                r.leg_dist = max(r.mileage - prev, 0)
                if r.leg_dist and speed:
                    r.leg_sec = r.leg_dist / speed * 3600
            elapsed += r.leg_sec
            r.arrive = elapsed
            r.arrive_clock = seg.base + elapsed
            if r.speed is not None:
                speed = r.speed
            elif speed is None:
                errors.append(f"Line {r.line_no}: no speed set yet")
            if r.next_min:                # Richta next-minute out: next whole minute after arrival
                arr = round(r.arrive_clock)
                r.pause = ((arr // 60) + 1) * 60 - r.arrive_clock
            elapsed += r.pause
            r.depart = elapsed
            r.depart_clock = seg.base + elapsed
            prev = r.mileage
        ref = seg.base + elapsed          # next section's relative times count from here
    return segments, errors


def fmt_clock(t: float, whole_minutes=False) -> str:
    t = round(t) % 86400
    if whole_minutes:
        t = round(t / 60) * 60 % 86400
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}" if whole_minutes else f"{h:02d}:{m:02d}:{s:02d}"


def fmt_elapsed(sec: float) -> str:
    t = round(sec)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def split_lines(text: str):
    """Instruction text -> list of lines. A literal backslash-n starts a new line;
    two in a row leave a blank line (paragraph break)."""
    return [p.strip() for p in text.split("\\n")]
