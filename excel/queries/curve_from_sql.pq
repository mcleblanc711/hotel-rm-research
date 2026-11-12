// Power Query: load the compact booking-curve mart straight from a SQL database.
// STATUS: not yet run in Excel or against SQL Server. Test before relying on it.
//
// Assumes the canonical SQL has been run in that database so the table
// mart_booking_curve_compact exists. Server and database come from the named
// cells SqlServer and SqlDatabase on the Settings sheet. Uses your Windows login;
// no credentials are stored in the workbook.
// Load the same way as curve_from_csv.pq (query name tblCurve, to Data!$A$1).
let
    Server = Excel.CurrentWorkbook(){[Name = "SqlServer"]}[Content]{0}[Column1],
    Database = Excel.CurrentWorkbook(){[Name = "SqlDatabase"]}[Content]{0}[Column1],
    Source = Sql.Database(
        Server,
        Database,
        [Query = "SELECT property_code, stay_year_month, is_fri_sat, business_source, days_before_stay, "
            & "rn_booked, rn_canceled, rn_stayed, rev_booked, rev_canceled "
            & "FROM mart_booking_curve_compact"]
    )
in
    Source
