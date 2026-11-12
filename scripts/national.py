#!/usr/bin/env python3
"""Read the national food tables into one common format.

  NEVO 2025/9.0 (RIVM, Netherlands)  NEVO2025_v9.0.zip, requested at rivm.nl/nevo
  BLS 4.0 (Max Rubner-Institut)      downloaded from blsdb.de
  CoFID 2021 (McCance and Widdowson) downloaded from gov.uk

The source files are not part of this repository: NEVO must be requested
from the RIVM, the others are downloaded into the cache folder.

Values are per 100 g (NEVO: per 100 ml for its liquids). Unknown values
stay empty; "trace" counts as 0. Salt is taken from the table where given
(BLS), otherwise sodium x 2.5. Vitamins and minerals are kept in one
unit per key (see MICROS), converted where a table uses another unit.

Writes national-foods.tsv.gz to the cache folder.

Usage: python3 -I scripts/national.py [--cache DIR]
"""

import argparse
import csv
import gzip
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import xlsx  # noqa: E402

DEFAULT_CACHE = Path.home() / "Library" / "Caches" / "nutryn-data"
USER_AGENT = "Nutryn-data/1.0 (support@smallprograms.dk)"
BLS_URL = "https://blsdb.de/assets/uploads/BLS_4_0_2025_DE.zip"
COFID_URL = (
    "https://assets.publishing.service.gov.uk/media/60538b91e90e07527df82ae4/"
    "McCance_Widdowsons_Composition_of_Foods_Integrated_Dataset_2021..xlsx"
)

COLUMNS = [
    "source", "source_id", "name_local", "name_en", "group", "is_liquid",
    "kcal", "protein", "carbohydrates", "fat",
    "sugar", "saturated_fat", "fibre", "salt", "micros", "version",
]

# Our key -> unit. Every table is converted to these units.
MICROS = {
    "vitaminA": "µg", "vitaminD": "µg", "vitaminE": "mg", "vitaminK": "µg",
    "thiamin": "mg", "riboflavin": "mg", "niacin": "mg", "vitaminB6": "mg",
    "folate": "µg", "vitaminB12": "µg", "vitaminC": "mg",
    "potassium": "mg", "calcium": "mg", "magnesium": "mg", "phosphorus": "mg",
    "iron": "mg", "zinc": "mg", "iodine": "µg", "selenium": "µg",
}

# Component codes per table -> our key.
NEVO_MICROS = {
    "VITA_RAE": "vitaminA", "VITD": "vitaminD", "VITE": "vitaminE", "VITK": "vitaminK",
    "THIA": "thiamin", "RIBF": "riboflavin", "NIAEQ": "niacin", "VITB6": "vitaminB6",
    "FOL": "folate", "VITB12": "vitaminB12", "VITC": "vitaminC",
    "K": "potassium", "CA": "calcium", "MG": "magnesium", "P": "phosphorus",
    "FE": "iron", "ZN": "zinc", "ID": "iodine", "SE": "selenium",
}
BLS_MICROS = {
    "VITA": "vitaminA", "VITD": "vitaminD", "VITE": "vitaminE", "VITK": "vitaminK",
    "THIA": "thiamin", "RIBF": "riboflavin", "NIAEQ": "niacin", "VITB6": "vitaminB6",
    "FOL": "folate", "VITB12": "vitaminB12", "VITC": "vitaminC",
    "K": "potassium", "CA": "calcium", "MG": "magnesium", "P": "phosphorus",
    "FE": "iron", "ZN": "zinc", "ID": "iodine", "SE": "selenium",
}
COFID_MICROS = {
    "RETEQU": "vitaminA", "VITD": "vitaminD", "VITE": "vitaminE", "VITK1": "vitaminK",
    "THIA": "thiamin", "RIBO": "riboflavin", "NIACEQU": "niacin", "VITB6": "vitaminB6",
    "FOLT": "folate", "VITB12": "vitaminB12", "VITC": "vitaminC",
    "K": "potassium", "CA": "calcium", "MG": "magnesium", "P": "phosphorus",
    "FE": "iron", "ZN": "zinc", "I": "iodine", "SE": "selenium",
}

UNIT_FACTOR = {("µg", "mg"): 0.001, ("mg", "µg"): 1000, ("g", "mg"): 1000, ("mg", "g"): 0.001}


def number(text: str) -> float | None:
    """A table value: "" and "N" are unknown, "Tr" (trace) is 0."""
    text = (text or "").strip().strip("()[]").replace(",", ".")
    if text.lower() in ("tr", "trace"):
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def convert(value: float | None, unit: str, key: str) -> float | None:
    target = MICROS[key]
    if value is None or unit == target:
        return value
    return value * UNIT_FACTOR[(unit, target)]


def unit_of(header: str) -> str:
    """The unit in a header like "VITB6 (mg)" or "VITB6 Vitamin B6 [µg/100g]"."""
    for unit in ("µg", "mg", "kcal", "kJ", "g"):
        if f"({unit})" in header or f"[{unit}/" in header:
            return unit
    return ""


def salt(salt_g: float | None, sodium_mg: float | None) -> float | None:
    if salt_g is not None:
        return salt_g
    return None if sodium_mg is None else sodium_mg * 2.5 / 1000


def fetch(url: str, path: Path) -> Path:
    if not path.exists():
        print(f"Downloading {url} ...")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())
    return path


def read_nevo(cache: Path) -> list[dict]:
    archive = next(iter(sorted(cache.glob("NEVO*.zip"))), None)
    if archive is None:
        sys.exit("NEVO zip not found in the cache folder: request it at rivm.nl/nevo")
    with zipfile.ZipFile(archive) as book:
        # The main table carries the archive's name, e.g. NEVO2025_v9.0.csv.
        name = next(n for n in book.namelist() if Path(n).name == f"{archive.stem}.csv")
        text = book.read(name).decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text), delimiter="|")
    header = next(reader)
    code = {h.split(" (")[0].strip(): i for i, h in enumerate(header)}
    units = {h.split(" (")[0].strip(): unit_of(h) for h in header}
    foods = []
    for row in reader:
        def value(key: str) -> float | None:
            return number(row[code[key]]) if key in code else None

        micros = {}
        for column, key in NEVO_MICROS.items():
            converted = convert(value(column), units.get(column, ""), key)
            if converted is not None:
                micros[key] = converted
        version = row[code["NEVO-versie/NEVO-version"]].replace("NEVO-Online ", "").replace(" ", "/")
        foods.append({
            "source": "nevo",
            "source_id": row[code["NEVO-code"]],
            "name_local": row[code["Voedingsmiddelnaam/Dutch food name"]].strip(),
            "name_en": row[code["Engelse naam/Food name"]].strip(),
            "group": row[code["Food group"]].strip(),
            "is_liquid": "1" if "ml" in row[code["Hoeveelheid/Quantity"]] else "0",
            "kcal": value("ENERCC"),
            "protein": value("PROT"),
            "carbohydrates": value("CHO"),
            "fat": value("FAT"),
            "sugar": value("SUGAR"),
            "saturated_fat": value("FASAT"),
            "fibre": value("FIBT"),
            "salt": salt(None, value("NA")),
            "micros": micros,
            "version": version,
        })
    return foods


def read_bls(cache: Path) -> list[dict]:
    archive = fetch(BLS_URL, cache / "BLS_4_0_2025_DE.zip")
    folder = cache / "bls"
    with zipfile.ZipFile(archive) as book:
        member = next(n for n in book.namelist() if "Daten" in n and n.endswith(".xlsx"))
        target = folder / Path(member).name
        if not target.exists():
            folder.mkdir(exist_ok=True)
            target.write_bytes(book.read(member))
    rows = xlsx.rows(target)
    header = next(rows)
    # Value columns look like "FAT Fett [g/100g]"; skip "… Datenherkunft"/"… Referenz".
    code = {h.split(" ")[0]: i for i, h in enumerate(header) if "[" in h}
    units = {h.split(" ")[0]: unit_of(h) for h in header if "[" in h}
    foods = []
    for row in rows:
        if not row or not row[0]:
            continue

        def value(key: str) -> float | None:
            i = code.get(key)
            return number(row[i]) if i is not None and i < len(row) else None

        micros = {}
        for column, key in BLS_MICROS.items():
            converted = convert(value(column), units.get(column, ""), key)
            if converted is not None:
                micros[key] = converted
        foods.append({
            "source": "bls",
            "source_id": row[0],
            "name_local": row[1].strip(),
            "name_en": row[2].strip(),
            "group": row[0][:1],
            "is_liquid": "0",
            "kcal": value("ENERCC"),
            "protein": value("PROT625"),
            "carbohydrates": value("CHO"),
            "fat": value("FAT"),
            "sugar": value("SUGAR"),
            "saturated_fat": value("FASAT"),
            "fibre": value("FIBT"),
            "salt": salt(value("NACL"), value("NA")),
            "micros": micros,
            "version": "4.0",
        })
    return foods


def read_cofid(cache: Path) -> list[dict]:
    book = fetch(COFID_URL, cache / "cofid-2021.xlsx")

    def sheet(name: str) -> tuple[dict[str, list[str]], dict[str, int], dict[str, str]]:
        rows = xlsx.rows(book, name)
        titles, codes = next(rows), next(rows)
        next(rows)  # descriptions
        index = {c: i for i, c in enumerate(codes) if c}
        units = {c: unit_of(titles[i]) for c, i in index.items()}
        return {row[0]: row for row in rows if row and row[0]}, index, units

    proximates, p_index, _ = sheet("1.3 Proximates")
    inorganics, i_index, i_units = sheet("1.4 Inorganics")
    vitamins, v_index, v_units = sheet("1.5 Vitamins")

    def value(table: dict, index: dict, food: str, key: str) -> float | None:
        row = table.get(food)
        i = index.get(key)
        return number(row[i]) if row is not None and i is not None and i < len(row) else None

    foods = []
    for food, row in proximates.items():
        micros = {}
        for column, key in COFID_MICROS.items():
            if column in v_index:
                converted = convert(value(vitamins, v_index, food, column), v_units[column], key)
            else:
                converted = convert(value(inorganics, i_index, food, column), i_units.get(column, ""), key)
            if converted is not None:
                micros[key] = converted
        foods.append({
            "source": "cofid",
            "source_id": food,
            "name_local": row[1].strip(),
            "name_en": row[1].strip(),
            "group": row[3].strip(),
            "is_liquid": "0",
            "kcal": value(proximates, p_index, food, "KCALS"),
            "protein": value(proximates, p_index, food, "PROT"),
            "carbohydrates": value(proximates, p_index, food, "CHO"),
            "fat": value(proximates, p_index, food, "FAT"),
            "sugar": value(proximates, p_index, food, "TOTSUG"),
            "saturated_fat": value(proximates, p_index, food, "SATFOD"),
            "fibre": value(proximates, p_index, food, "AOACFIB"),
            "salt": salt(None, value(inorganics, i_index, food, "NA")),
            "micros": micros,
            "version": "2021",
        })
    return foods


def write(foods: list[dict], output: Path) -> None:
    def text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.4f}".rstrip("0").rstrip(".")
        if isinstance(value, dict):
            return json.dumps({k: round(v, 4) for k, v in value.items()}, separators=(",", ":")) if value else ""
        return str(value).replace("\t", " ")

    with gzip.open(output, "wt", encoding="utf-8", newline="") as file:
        file.write("\t".join(COLUMNS) + "\n")
        for food in foods:
            file.write("\t".join(text(food[column]) for column in COLUMNS) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help=f"cache folder (default {DEFAULT_CACHE})")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)

    kept: list[dict] = []
    for reader in (read_nevo, read_bls, read_cofid):
        foods = reader(args.cache)
        complete = [f for f in foods if None not in (f["kcal"], f["protein"], f["carbohydrates"], f["fat"])]
        source = foods[0]["source"] if foods else reader.__name__
        print(f"{source:6} {len(foods):>6,} foods, {len(complete):>6,} with energy and macros, "
              f"version {foods[0]['version'] if foods else '-'}")
        for key in ("sugar", "saturated_fat", "fibre", "salt"):
            print(f"         {key:14} known for {sum(f[key] is not None for f in complete):>6,}")
        print(f"         micros         known for {sum(bool(f['micros']) for f in complete):>6,}")
        kept.extend(complete)

    output = args.cache / "national-foods.tsv.gz"
    write(kept, output)
    print(f"Written {len(kept):,} foods to {output}")


if __name__ == "__main__":
    main()
