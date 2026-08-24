"""Stops exported spreadsheets carrying executable formulas.

Every candidate field in this system arrives from an uploaded spreadsheet and is exported again
later - the All Candidates export and the upload validation report both echo names, emails,
colleges and error text straight back out. openpyxl treats any string beginning with "=" as a
formula and writes it into the file as a real <f> element, so a candidate whose name is

    =cmd|'/c calc'!A1

produces a workbook that asks Excel to run a command the moment a TA opens it. The same trick
with WEBSERVICE() or HYPERLINK() quietly exfiltrates whatever else is in the sheet. The victim is
internal staff opening a file they have every reason to trust, which is what makes it worth
guarding rather than shrugging at.

The fix is to mark string cells as text explicitly, which openpyxl then writes as a shared
string instead of a formula.

Deliberately NOT the usual "prefix every cell with an apostrophe" mitigation. That advice comes
from CSV, where there is no type information in the file and Excel decides for itself. In xlsx
the cell carries its own type, and measurement confirms only "=" is auto-detected as a formula by
openpyxl - a leading "@", "+" or "-" is already written as text and is inert. Prefixing those
would visibly corrupt ordinary data for no security benefit: every Indian mobile number in the
export starts with "+91".
"""


def harden_worksheet(worksheet):
    """Force every string cell on this sheet to be text rather than a formula."""
    for row in worksheet.iter_rows():
        for cell in row:
            # Checked on the value, not on data_type, so this also covers a cell openpyxl has
            # already classified as a formula - that classification is exactly what is being
            # undone. Numbers, dates and None are left completely alone.
            if isinstance(cell.value, str):
                cell.data_type = 's'


def harden_workbook(workbook):
    """Apply harden_worksheet to every sheet. Returns the workbook for convenient chaining.

    Called at the end of each generator in services/excel_upload.py and
    services/question_bank.py rather than in the views, so a new caller of an existing generator
    cannot forget it - the view only ever receives an already-hardened workbook.
    """
    for worksheet in workbook.worksheets:
        harden_worksheet(worksheet)
    return workbook
