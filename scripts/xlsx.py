"""Minimal .xlsx reader (standard library only): rows of a sheet as strings.

Enough for the national food tables: shared and inline strings, numbers,
empty cells. No formulas are evaluated (the cached value is read), no dates.
"""

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
COLUMN = re.compile(r"[A-Z]+")


def sheet_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as book:
        workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
    return [sheet.get("name") for sheet in workbook.iterfind("m:sheets/m:sheet", NS)]


def rows(path: Path, sheet: str | int = 0):
    """Yields each row as a list of strings ("" for empty cells)."""
    with zipfile.ZipFile(path) as book:
        shared = _shared_strings(book)
        with book.open(_sheet_path(book, sheet)) as file:
            for _, element in ElementTree.iterparse(file):
                if element.tag != f"{{{NS['m']}}}row":
                    continue
                values: list[str] = []
                for cell in element.iterfind("m:c", NS):
                    column = _column_index(COLUMN.match(cell.get("r")).group())
                    values.extend([""] * (column - len(values)))
                    values.append(_value(cell, shared))
                yield values
                element.clear()


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
    return ["".join(text.text or "" for text in item.iter(f"{{{NS['m']}}}t")) for item in root.iterfind("m:si", NS)]


def _sheet_path(book: zipfile.ZipFile, sheet: str | int) -> str:
    workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
    sheets = list(workbook.iterfind("m:sheets/m:sheet", NS))
    chosen = sheets[sheet] if isinstance(sheet, int) else next(s for s in sheets if s.get("name") == sheet)
    relations = ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    target = next(r.get("Target") for r in relations if r.get("Id") == chosen.get(REL_NS))
    return target.lstrip("/") if target.startswith("/") else f"xl/{target}"


def _column_index(letters: str) -> int:
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - 64
    return index - 1


def _value(cell, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(f"{{{NS['m']}}}t"))
    value = cell.find("m:v", NS)
    if value is None or value.text is None:
        return ""
    if kind == "s":
        return shared[int(value.text)]
    return value.text
