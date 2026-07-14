---
    name: Google Sheets append() column-shift quirk
    description: values().append() can silently write a row one column off when the leading column is entirely blank/unheaded — use explicit update() instead.
    ---

    When writing rows to a Google Sheet via the Sheets API, `spreadsheets.values().append()`
    auto-detects which column the existing "table" starts in by scanning for
    non-empty cells within the given range. If the leading column (e.g. column A)
    has no header text and is empty in every existing row, append() can decide the
    table actually starts one column to the right, and will write the new row
    shifted by one column — silently misaligning every field and dropping the
    last field off the end of the row range.

    **Why:** Discovered writing to a real spreadsheet where column A was
    historically always blank (an unused "Date" column). append() shifted a new
    row from A:W to B:X, corrupting the write and appearing to insert at row 2
    even when hundreds of real rows already existed (it also shifted existing
    data down when insertDataOption=INSERT_ROWS).

    **How to apply:** For deterministic column alignment, don't rely on
    append()'s auto-detection. Instead: compute the exact target row number
    yourself (e.g. count existing rows via values().get on the full column
    range, +1), then write with `values().update()` using an explicit
    `A{row}:W{row}`-style range. This is the same technique needed for
    update-in-place/upsert logic, so one code path covers both insert and update
    safely.
    