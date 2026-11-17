"""Extract the old channel calibrations from IC_channel_calibration.xlsx.

Writes ``calibration.csv`` (one row per measurement, for review) and, from that
CSV, the maintenance script ``src/data/sql/maintenance/import_calibration_history.sql``
that loads them into ``icm.channel_calibration``.

    python src/data/calibration_export/extract_calibration.py [path/to/workbook.xlsx]
    python src/data/calibration_export/extract_calibration.py --sql-only   # CSV -> SQL again

Workbook layout: one sheet per channel ("1-1" ... "8-8", plus the lab stations
"Lab 1-1" ...), two header rows, then Date | IC number | Measured by | Applied
current | 6 potentials (1, 1.5, 2, 3.3, 4, 5 ohm) | 6 delta-V % formulas |
"Approved?" formula | Note (on some sheets). Columns are found by their header
("Lab 2-1" has no IC number). "Recent state" (latest per channel) is only a
tie-breaker and cross-check.
"""
import csv
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_XLSX = ROOT / "IC_channel_calibration.xlsx"
OUT_CSV = Path(__file__).resolve().parent / "calibration.csv"
OUT_SQL = ROOT / "src" / "data" / "sql" / "maintenance" / "import_calibration_history.sql"

FIELDS = ["channel", "measured_date", "ic_number", "measured_by", "applied_current",
          "p_1_0", "p_1_5", "p_2_0", "p_3_3", "p_4_0", "p_5_0", "decision", "note",
          "source_row"]
POTENTIALS = FIELDS[5:11]
DECISIONS = {"yes": "Pass", "no": "Fail"}
PLACEHOLDERS = {"", "x", "-"}  # "no IC number" in the IC number column


def date_candidates(value, today=None):
    """Possible dates for a Date cell. PCs with US settings turned a typed dd/mm into
    mm/dd when the day was 12 or less (and left later days as text), so a real date
    with day and month both <= 12 may be swapped: then both readings are returned."""
    day = parse_date(value)
    if day is None:
        return []
    if isinstance(value, (datetime, date)) and day.day <= 12 and day.month <= 12 \
            and day.day != day.month:
        swapped = date(day.year, day.day, day.month)
        return [d for d in (day, swapped) if today is None or d <= today] or [day]
    return [day]


def resolve_dates(sheets: dict, today: date, recent: dict = None) -> dict:
    """{(sheet, row): (date, how)} for every measurement row.

    Rows are kept in date order within a sheet, so an ambiguous date takes the
    reading that fits between its settled neighbours. A channel's latest row
    still open takes the reading the "Recent state" sheet lists for it. Any other
    takes the reading chosen for the same stored date + 'Measured by' on another
    sheet (one session covers many channels); otherwise it keeps the stored date."""
    recent = recent or {}
    chosen, open_ = {}, []
    for name, rows in sheets.items():
        fixed = [c[0] if len(c) == 1 else None for _, c, _, _ in rows]
        for k, (row, cands, raw, by) in enumerate(rows):
            if len(cands) == 1:
                chosen[(name, row)] = (cands[0], "as stored" if cands[0] == parse_date(raw)
                                       else "stored date is in the future")
                continue
            prev = next((fixed[j] for j in range(k - 1, -1, -1) if fixed[j]), None)
            nxt = next((fixed[j] for j in range(k + 1, len(rows)) if fixed[j]), None)
            fit = [d for d in cands if (prev is None or d >= prev) and (nxt is None or d <= nxt)]
            if len(fit) == 1:
                fixed[k] = fit[0]
                chosen[(name, row)] = (fit[0], "order")
            elif k == len(rows) - 1 and recent.get(name.strip()) in cands:
                chosen[(name, row)] = (recent[name.strip()], "Recent state sheet")
            else:
                open_.append((name, row, cands, raw, by))
    by_session = {}
    for (name, row), (d, how) in chosen.items():
        raw, by = next((r, b) for rw, _, r, b in sheets[name] if rw == row)
        if how in ("order", "Recent state sheet"):
            by_session.setdefault((raw, by), set()).add(d)
    for name, row, cands, raw, by in open_:
        known = by_session.get((raw, by), set())
        if len(known) == 1:
            chosen[(name, row)] = (known.pop(), "same session elsewhere")
            by_session[(raw, by)] = {chosen[(name, row)][0]}
        else:
            chosen[(name, row)] = (cands[0], "UNRESOLVED, kept as stored")
    return chosen


def parse_date(value):
    """A date from a datetime, a dd/mm/yyyy text or an Excel serial; None if not a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and 30000 < value < 60000:
        return date(1899, 12, 30) + timedelta(days=int(value))  # Excel day number
    if isinstance(value, str):
        m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", value)
        if m:
            day, month, year = map(int, m.groups())
            return date(year, month, day)
    return None


def split_ic_number(value):
    """(ic_number, note text): real IDs padded to IC####, clip remarks go to the note."""
    if value is None:
        return "", ""
    if isinstance(value, (int, float)):
        return f"IC{int(value):04d}", ""
    text = str(value).strip()
    m = re.fullmatch(r"IC\s*(\d+)", text, re.IGNORECASE)
    if m:
        return f"IC{int(m.group(1)):04d}", ""
    if text.lower() in PLACEHOLDERS:
        return "", ""
    return "", text


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def column_map(header: tuple) -> dict:
    """Column index per field, from a sheet's first header row ("Lab 2-1" has no
    IC number column); None for a column the sheet doesn't have."""
    names = [re.sub(r"\s+", " ", str(h or "")).strip().lower() for h in header]
    find = lambda prefix: next((i for i, h in enumerate(names) if h.startswith(prefix)), None)
    return {"date": find("date"), "ic": find("ic number"), "by": find("measured by"),
            "current": find("applied current"), "pots": find("measured potential"),
            "approved": find("approved"), "note": find("note")}


def extract(xlsx: Path):
    import openpyxl  # only needed for this step

    wb = openpyxl.load_workbook(xlsx, data_only=True, read_only=True)
    today = date.today()
    skipped, fixes, date_log = [], Counter(), []
    # Cell channels ("1-1") and the lab stations ("Lab 1-1"), which exist only in calibration.
    channel_sheets = [n for n in wb.sheetnames if re.fullmatch(r"(Lab )?\d+-\d+", n.strip())]
    measurements, by_sheet = [], {}
    for name in channel_sheets:
        sheet_rows = wb[name].iter_rows(values_only=True)
        col = column_map(next(sheet_rows))
        next(sheet_rows)  # second header row (resistances / delta-V labels)
        get = lambda row, key: row[col[key]] if col[key] is not None else None
        for i, raw in enumerate(sheet_rows, start=3):
            raw = list(raw) + [None] * 20
            r = {k: get(raw, k) for k in ("date", "ic", "by", "current", "approved", "note")}
            pots = [number(v) for v in raw[col["pots"]:col["pots"] + 6]]
            shown = raw[:col["pots"] + 6]
            if r["date"] in (None, "") and all(p is None for p in pots):
                continue  # empty template row
            where = f"{name.strip()}!{i}"
            cands = date_candidates(r["date"], today)
            if not cands:
                skipped.append((where, "no date (not a measurement)", shown))
                continue
            if any(p is None for p in pots) or number(r["current"]) is None:
                skipped.append((where, "missing current or a potential", shown))
                continue
            if all(p == 0 for p in pots):
                skipped.append((where, "all six potentials are 0 (nothing measured)", shown))
                continue
            if DECISIONS.get(str(r["approved"] or "").strip().lower()) is None:
                skipped.append((where, f"'Approved?' is {r['approved']!r}", shown))
                continue
            by = str(r["by"]).strip() if r["by"] is not None else ""
            measurements.append((name, i, r, pots))
            by_sheet.setdefault(name, []).append((i, cands, r["date"], by))
    # The latest date per channel as entered in "Recent state" (a tie-breaker + cross-check).
    recent = {}
    if "Recent state" in wb.sheetnames:
        for r in wb["Recent state"].iter_rows(min_row=3, values_only=True):
            if r[2] and parse_date(r[0]):
                recent[str(r[2]).strip()] = parse_date(r[0])
    dates = resolve_dates(by_sheet, today, recent)

    rows = []
    for name, i, r, pots in measurements:
        channel, where = name.strip(), f"{name.strip()}!{i}"
        raw_date, ic_raw, by, current, approved, note = (
            r["date"], r["ic"], r["by"], r["current"], r["approved"], r["note"])
        day, how = dates[(name, i)]
        if not isinstance(raw_date, (datetime, date)):
            fixes[f"date read from {type(raw_date).__name__}"] += 1
        elif day != parse_date(raw_date) or how != "as stored":
            fixes[f"ambiguous date: {how}" + (", swapped" if day != parse_date(raw_date) else "")] += 1
            date_log.append((where, parse_date(raw_date).isoformat(), day.isoformat(), how))
        decision = DECISIONS[str(approved).strip().lower()]
        ic_number, ic_note = split_ic_number(ic_raw)
        if ic_note:
            fixes["IC number text moved to note"] += 1
        notes = [str(note).strip()] if note not in (None, "") else []
        if ic_note and ic_note.lower() not in (n.lower() for n in notes):
            notes.insert(0, ic_note)
        rows.append({
            "channel": channel, "measured_date": day.isoformat(), "ic_number": ic_number,
            "measured_by": str(by).strip() if by is not None else "",
            "applied_current": repr(number(current)),
            **{k: repr(p) for k, p in zip(POTENTIALS, pots)},
            "decision": decision, "note": "; ".join(notes), "source_row": where,
        })
    return rows, skipped, fixes, channel_sheets, recent, date_log


def write_csv(rows):
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def read_csv():
    with open(OUT_CSV, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def sql_text(value: str) -> str:
    return "NULL" if value in (None, "") else "N'" + value.replace("'", "''") + "'"


def write_sql(rows):
    values = []
    for r in rows:
        values.append("    (" + ", ".join([
            sql_text(r["channel"]), f"'{r['measured_date']}'", sql_text(r["ic_number"]),
            sql_text(r["measured_by"]), r["applied_current"],
            *[r[k] for k in POTENTIALS], sql_text(r["decision"]), sql_text(r["note"]),
        ]) + ")")
    body = ",\n".join(values)
    OUT_SQL.parent.mkdir(parents=True, exist_ok=True)
    OUT_SQL.write_text(f"""-- import_calibration_history.sql  (maintenance, not a migration)
-- Loads the old channel calibrations from IC_channel_calibration.xlsx into
-- icm.channel_calibration: {len(rows)} measurements.
-- GENERATED by src/data/calibration_export/extract_calibration.py; regenerate, don't edit.
--
-- Decision: the workbook's "Approved?" (Yes/No) as Pass/Fail, decided by
-- 'Excel import' on the measurement date.
-- A channel's current calibration never changes: on a channel that already has
-- calibrations, only rows older than its latest are added (the latest stays the
-- latest). A measurement already stored (same channel, date and six potentials)
-- is skipped, so the script is safe to re-run.
-- Run with an admin login on dataloggingTest first, then dataloggingDev.

IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
    THROW 50000, N'Refusing to run: not an expected database.', 1;

IF NOT EXISTS (SELECT 1 FROM [icm].[schema_migrations]
               WHERE filename = N'014_create_calibration_table_and_procs.sql')
    THROW 50000, N'Run migration 014 first (creates icm.channel_calibration).', 1;

SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @import TABLE (
    [channel] NVARCHAR(32), [measured_date] DATE, [ic_number] NVARCHAR(64),
    [measured_by] NVARCHAR(256), [applied_current] FLOAT,
    [p_1_0] FLOAT, [p_1_5] FLOAT, [p_2_0] FLOAT, [p_3_3] FLOAT, [p_4_0] FLOAT, [p_5_0] FLOAT,
    [decision] NVARCHAR(32), [note] NVARCHAR(MAX));

INSERT INTO @import VALUES
{body};

BEGIN TRAN;

-- Each channel's latest date before the import (NULL: no calibrations yet).
DECLARE @latest TABLE ([channel] NVARCHAR(32) PRIMARY KEY, [latest] DATE);
INSERT INTO @latest
SELECT [channel], MAX([measured_date]) FROM [icm].[channel_calibration] GROUP BY [channel];

DECLARE @already INT = (
    SELECT COUNT(*) FROM @import i
     WHERE EXISTS (
           SELECT 1 FROM [icm].[channel_calibration] c
            WHERE c.[channel] = i.[channel] AND c.[measured_date] = i.[measured_date]
              AND c.[p_1_0] = i.[p_1_0] AND c.[p_1_5] = i.[p_1_5] AND c.[p_2_0] = i.[p_2_0]
              AND c.[p_3_3] = i.[p_3_3] AND c.[p_4_0] = i.[p_4_0] AND c.[p_5_0] = i.[p_5_0]));

INSERT INTO [icm].[channel_calibration]
    ([channel], [measured_date], [ic_number], [measured_by], [applied_current],
     [p_1_0], [p_1_5], [p_2_0], [p_3_3], [p_4_0], [p_5_0],
     [decision], [decided_by], [decided_at], [note])
SELECT i.[channel], i.[measured_date], i.[ic_number], i.[measured_by], i.[applied_current],
       i.[p_1_0], i.[p_1_5], i.[p_2_0], i.[p_3_3], i.[p_4_0], i.[p_5_0],
       i.[decision], N'Excel import', CAST(i.[measured_date] AS DATETIME2), i.[note]
  FROM @import i
  LEFT JOIN @latest l ON l.[channel] = i.[channel]
 WHERE (l.[latest] IS NULL OR i.[measured_date] < l.[latest])  -- never a new latest
   AND NOT EXISTS (
       SELECT 1 FROM [icm].[channel_calibration] c
        WHERE c.[channel] = i.[channel] AND c.[measured_date] = i.[measured_date]
          AND c.[p_1_0] = i.[p_1_0] AND c.[p_1_5] = i.[p_1_5] AND c.[p_2_0] = i.[p_2_0]
          AND c.[p_3_3] = i.[p_3_3] AND c.[p_4_0] = i.[p_4_0] AND c.[p_5_0] = i.[p_5_0]);
DECLARE @inserted INT = @@ROWCOUNT;
COMMIT;

SELECT @inserted AS inserted, @already AS already_there,
       {len(rows)} - @inserted - @already AS skipped_not_older_than_latest;
GO
""", encoding="utf-8-sig", newline="\n")  # BOM: SSMS then reads the accents (Balázs) right


def report(rows, skipped, fixes, sheets, recent, date_log):
    per = Counter(r["channel"] for r in rows)
    print(f"{len(rows)} measurements from {len(sheets)} channel sheets -> {OUT_CSV}")
    print("  per channel:", " ".join(f"{c.strip()}:{per[c.strip()]}" for c in sheets))
    print("  Pass/Fail:", dict(Counter(r["decision"] for r in rows)))
    for what, n in fixes.items():
        print(f"  {what}: {n}")
    print(f"\nAmbiguous dates settled ({len(date_log)}; stored -> used):")
    for where, stored, used, how in date_log:
        print(f"  {where:<8} {stored} -> {used}  ({how})")
    print(f"\nSkipped {len(skipped)} rows:")
    for where, why, data in skipped:
        print(f"  {where:<8} {why}  {[v for v in data if v is not None]}")
    latest = {}
    for r in rows:
        latest[r["channel"]] = max(latest.get(r["channel"], ""), r["measured_date"])
    diff = {c: (latest.get(c), d.isoformat()) for c, d in recent.items() if latest.get(c) != d.isoformat()}
    print(f"\nCross-check with 'Recent state' ({len(recent)} channels): "
          + ("latest dates all match" if not diff else f"differences {diff}"))


def main():
    if "--sql-only" in sys.argv:
        rows = read_csv()
        write_sql(rows)
        print(f"{len(rows)} measurements from {OUT_CSV} -> {OUT_SQL}")
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    xlsx = Path(args[0]) if args else DEFAULT_XLSX
    rows, skipped, fixes, sheets, recent, date_log = extract(xlsx)
    rows.sort(key=lambda r: (r["channel"], r["measured_date"]))
    write_csv(rows)
    write_sql(read_csv())  # the SQL always comes from the (reviewable) CSV
    report(rows, skipped, fixes, sheets, recent, date_log)
    print(f"\nSQL written: {OUT_SQL}")


if __name__ == "__main__":
    main()
