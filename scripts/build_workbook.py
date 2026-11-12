"""Build excel/booking_curves.xlsx from the compact booking-curve mart.

The workbook uses only classic worksheet functions (SUMIFS over whole columns
of the Data sheet), so it recalculates in any Excel 365 install with no
add-ins, macros or connections. To point it at other data, replace the Data
sheet's contents with the same ten columns (see excel/README.md).

    uv run --with duckdb --with openpyxl scripts/build_workbook.py --source antonio
"""
import argparse
import json
import pathlib

import duckdb
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--source", default="antonio")
ap.add_argument("--out", default=None)
ap.add_argument("--horizon", type=int, default=120)
args = ap.parse_args()

src = ROOT / "out" / args.source
con = duckdb.connect(str(src / "canonical.duckdb"), read_only=True)
manifest = json.loads((src / "manifest.json").read_text())
COLS = ["property_code", "stay_year_month", "is_fri_sat", "business_source", "days_before_stay",
        "rn_booked", "rn_canceled", "rn_stayed", "rev_booked", "rev_canceled"]
data = con.execute(
    f"SELECT {', '.join(COLS)} FROM mart_booking_curve_compact ORDER BY 1, 2, 3, 4, 5"
).fetchall()
props = [r[0] for r in con.execute("SELECT DISTINCT property_code FROM mart_booking_curve_compact ORDER BY 1").fetchall()]
sources = [r[0] for r in con.execute("SELECT DISTINCT business_source FROM mart_booking_curve_compact ORDER BY 1").fetchall()]
as_of_ym = int(manifest["as_of_date"][:4]) * 100 + int(manifest["as_of_date"][5:7])
ym_min, ym_max = con.execute("SELECT MIN(stay_year_month), MAX(stay_year_month) FROM mart_booking_curve_compact").fetchone()
# Stay months after the last arrival month only hold the tail of earlier arrivals, so stop there.
arr_ym = con.execute("SELECT MAX(EXTRACT(YEAR FROM arrival_date) * 100 + EXTRACT(MONTH FROM arrival_date)) "
                     "FROM fact_reservation WHERE arrival_date <= (SELECT as_of_date FROM run_context)").fetchone()[0]
ym_to = min(int(ym_max), as_of_ym, int(arr_ym))

wb = Workbook()
ws = wb.active
ws.title = "Curves"
bold, head = Font(bold=True), Font(bold=True, size=14)
inp = PatternFill("solid", start_color="FFF2CC")   # cells the user changes
calc = PatternFill("solid", start_color="EDEDED")  # helper cells
grey = Font(color="666666", italic=True)

ws["A1"], ws["A1"].font = "Booking curves", head
ws["A2"] = ("Reconstructed from final booking records unless the source has true history. "
            "Change the yellow cells; everything else recalculates.")
ws["A2"].font = grey
ws["A4"], ws["B4"], ws["C4"] = "Setting", "Series A", "Series B"
for c in ("A4", "B4", "C4"):
    ws[c].font = bold
settings = [
    ("Property", props[0] if len(props) > 1 else "All", props[1] if len(props) > 1 else "All"),
    ("Source of business", "All", "All"),
    ("Stay month from (YYYYMM)", int(ym_min), int(ym_min)),
    ("Stay month to (YYYYMM)", ym_to, ym_to),
    ("Stay nights", "All", "All"),
]
for i, (label, a, b) in enumerate(settings):
    r = 5 + i
    ws.cell(r, 1, label)
    for col, v in ((2, a), (3, b)):
        ws.cell(r, col, v).fill = inp
helpers = [
    ("property criterion", '=IF({c}5="All","*",{c}5)'),
    ("source criterion", '=IF({c}6="All","*",{c}6)'),
    ("fri/sat flag from", '=IF({c}9="Fri-Sat",1,0)'),
    ("fri/sat flag to", '=IF({c}9="Sun-Thu",0,1)'),
]
for i, (label, f) in enumerate(helpers):
    r = 10 + i
    ws.cell(r, 1, label).font = grey
    for col in "BC":
        ws[f"{col}{r}"] = f.format(c=col)
        ws[f"{col}{r}"].fill = calc


def crit(c):
    """SUMIFS criteria shared by every measure for the series whose settings are in column c."""
    return (f"Data!$A:$A,{c}$10,Data!$D:$D,{c}$11,"
            f'Data!$B:$B,">="&{c}$7,Data!$B:$B,"<="&{c}$8,'
            f'Data!$C:$C,">="&{c}$12,Data!$C:$C,"<="&{c}$13')


summary = [
    ("Room-nights stayed", "=SUMIFS(Data!$H:$H,{k})", "#,##0"),
    ("Room-nights booked (gross)", "=SUMIFS(Data!$F:$F,{k})", "#,##0"),
    ("Canceled, % of gross", '=IFERROR(SUMIFS(Data!$G:$G,{k})/{c}16,"")', "0.0%"),
]
ws["A14"], ws["A14"].font = "Summary", bold
for i, (label, f, fmt) in enumerate(summary):
    r = 15 + i
    ws.cell(r, 1, label)
    for c in "BC":
        ws[f"{c}{r}"] = f.format(k=crit(c), c=c)
        ws[f"{c}{r}"].number_format = fmt

HDR, FIRST = 20, 21
LAST = FIRST + args.horizon
blocks = (("A", "B", 2), ("B", "C", 7))  # (series name, settings column, first output column)
ws.cell(HDR, 1, "Days out").font = bold
for name, c, col0 in blocks:
    titles = [f"{name}: net on the books", f"{name}: % of final stayed", f"{name}: gross booked",
              f"{name}: canceled so far", f"{name}: ADR on the books"]
    for j, t in enumerate(titles):
        cell = ws.cell(HDR, col0 + j, t)
        cell.font, cell.alignment = bold, Alignment(wrap_text=True, vertical="top")
ws.row_dimensions[HDR].height = 32
for i in range(args.horizon + 1):
    r = FIRST + i
    ws.cell(r, 1, args.horizon - i)  # far out at the top, stay night at the bottom
    for name, c, col0 in blocks:
        L = [ws.cell(r, col0 + j).column_letter for j in range(5)]
        day = f'Data!$E:$E,">="&$A{r}'
        ws[f"{L[2]}{r}"] = f"=SUMIFS(Data!$F:$F,{crit(c)},{day})"
        ws[f"{L[3]}{r}"] = f"=SUMIFS(Data!$G:$G,{crit(c)},{day})"
        ws[f"{L[0]}{r}"] = f"={L[2]}{r}-{L[3]}{r}"
        ws[f"{L[1]}{r}"] = f'=IF({c}$15>0,{L[0]}{r}/{c}$15,NA())'
        ws[f"{L[4]}{r}"] = (f"=IF({L[0]}{r}>=30,(SUMIFS(Data!$I:$I,{crit(c)},{day})"
                            f"-SUMIFS(Data!$J:$J,{crit(c)},{day}))/{L[0]}{r},NA())")
        for j, fmt in enumerate(["#,##0", "0.0%", "#,##0", "#,##0", "#,##0.00"]):
            ws[f"{L[j]}{r}"].number_format = fmt
ws.freeze_panes = ws.cell(FIRST, 2)
ws.column_dimensions["A"].width = 30
for col in "BCDEFGHIJK":
    ws.column_dimensions[col].width = 15


def line_chart(title, y_title, cols, anchor, fmt):
    ch = LineChart()
    ch.title, ch.height, ch.width = title, 9, 20
    ch.y_axis.title, ch.x_axis.title = y_title, "Days before stay night"
    ch.y_axis.number_format = fmt
    ch.x_axis.tickLblSkip = 10
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    for col in cols:
        ch.add_data(Reference(ws, min_col=col, min_row=HDR, max_row=LAST), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=FIRST, max_row=LAST))
    for s in ch.series:
        s.smooth = False
        s.graphicalProperties.line.width = 22000
    ws.add_chart(ch, anchor)


line_chart("Net on the books, % of final stayed", "% of final stayed", (3, 8), "M3", "0%")
line_chart("Net on the books, room-nights", "Room-nights", (2, 7), "M22", "#,##0")

# Lists for the dropdowns
wl = wb.create_sheet("Lists")
wl["A1"], wl["B1"], wl["C1"] = "Property", "Source of business", "Stay nights"
for i, v in enumerate(["All"] + props):
    wl.cell(2 + i, 1, v)
for i, v in enumerate(["All"] + sources):
    wl.cell(2 + i, 2, v)
for i, v in enumerate(["All", "Fri-Sat", "Sun-Thu"]):
    wl.cell(2 + i, 3, v)
for rng, formula in (("B5:C5", f"Lists!$A$2:$A${1 + len(props) + 1}"),
                     ("B6:C6", f"Lists!$B$2:$B${1 + len(sources) + 1}"),
                     ("B9:C9", "Lists!$C$2:$C$4")):
    dv = DataValidation(type="list", formula1=f"={formula}", allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(rng)

# Data
wd = wb.create_sheet("Data")
wd.append(COLS)
for row in data:
    wd.append([float(v) if hasattr(v, "as_tuple") else v for v in row])
tbl = Table(displayName="tblCurve", ref=f"A1:J{len(data) + 1}")
tbl.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=False)
wd.add_table(tbl)

# Settings for the Power Query files
wsx = wb.create_sheet("Settings")
rows = [("DataFolder", r"C:\path\to\out\antonio", "Folder holding mart_booking_curve_compact.csv (CSV query)"),
        ("SqlServer", "", "Server name (SQL query)"),
        ("SqlDatabase", "", "Database name (SQL query)")]
wsx.append(["Name", "Value", "Used by"])
for i, (n, v, note) in enumerate(rows):
    wsx.append([n, v, note])
    wb.defined_names[n] = DefinedName(n, attr_text=f"Settings!$B${i + 2}")
    wsx.cell(i + 2, 2).fill = inp
wsx.column_dimensions["A"].width, wsx.column_dimensions["B"].width, wsx.column_dimensions["C"].width = 16, 44, 60

# About
wa = wb.create_sheet("About")
about = [
    "Booking curves workbook",
    "",
    f"Data source: {manifest['source_system']}  |  schema v{manifest['schema_version']}  |  as of {manifest['as_of_date']}",
    f"Source file SHA-256: {manifest['source_sha256']}",
    "",
    "How to use",
    "1. On the Curves sheet, change the yellow cells for Series A and Series B.",
    "2. The table and both charts recalculate. The right-hand end of each chart is the stay night.",
    "",
    "Definitions",
    "Net on the books at N days out = room-nights booked N or more days ahead, minus those canceled by then.",
    "% of final stayed = net on the books / room-nights that ended as checked-out. Above 100% means wash still to come.",
    "ADR on the books is hidden where fewer than 30 room-nights are on the books.",
    "Days out of 366 means 366 or more.",
    "",
    "Limitations of this data source",
    *["- " + s for s in manifest["known_limitations"]],
    "",
    "Using your own data",
    "Replace the rows of the Data sheet with the same ten columns, produced by sql/marts/booking_curve.sql",
    "(table mart_booking_curve_compact). See excel/README.md for the Power Query route.",
    "Update the Lists sheet if your property or source codes differ.",
]
for line in about:
    wa.append([line])
wa["A1"].font = head
wa.column_dimensions["A"].width = 120

out = pathlib.Path(args.out) if args.out else ROOT / "excel" / "booking_curves.xlsx"
wb.save(out)
print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(data):,} data rows)")
