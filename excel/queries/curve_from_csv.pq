// Power Query: load the compact booking-curve mart from a CSV export.
// STATUS: not yet run in Excel (written on a machine without it). Test before relying on it.
//
// Setup: Data > Get Data > From Other Sources > Blank Query > Advanced Editor, paste this,
// name the query tblCurve, then Close & Load To > Table > Existing worksheet > Data!$A$1
// (delete the static table on the Data sheet first).
// The folder comes from the named cell DataFolder on the Settings sheet.
let
    Folder = Excel.CurrentWorkbook(){[Name = "DataFolder"]}[Content]{0}[Column1],
    Path = if Text.EndsWith(Folder, "\") then Folder else Folder & "\",
    Source = Csv.Document(
        File.Contents(Path & "mart_booking_curve_compact.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(
        Promoted,
        {
            {"property_code", type text},
            {"stay_year_month", Int64.Type},
            {"is_fri_sat", Int64.Type},
            {"business_source", type text},
            {"days_before_stay", Int64.Type},
            {"rn_booked", Int64.Type},
            {"rn_canceled", Int64.Type},
            {"rn_stayed", Int64.Type},
            {"rev_booked", type number},
            {"rev_canceled", type number}
        },
        "en-US"
    ),
    // Column order is what the Curves sheet formulas rely on (A..J).
    Ordered = Table.SelectColumns(
        Typed,
        {"property_code", "stay_year_month", "is_fri_sat", "business_source", "days_before_stay",
         "rn_booked", "rn_canceled", "rn_stayed", "rev_booked", "rev_canceled"}
    )
in
    Ordered
