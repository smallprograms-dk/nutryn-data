#!/usr/bin/env python3
"""Download the Open Food Facts export and select the products Nutryn ships.

Keeps products sold in the Nutryn 1.0 markets (NL, BE, DE, AT, CH, GB) that
have a name and plausible nutrition values per 100 g:
  - energy, protein, carbohydrates and fat present;
  - energy 0-950 kcal, each macro 0-100 g, macros together at most 105 g;
  - energy close to 4 x protein + 4 x carbohydrates + 9 x fat
    (within 25 % or 15 kcal).

Writes off-selection.tsv.gz to the cache folder (one row per barcode) and prints the
counts per country.

Usage: python3 -I scripts/off.py [--refresh] [--cache DIR]
Standard library only.
"""

import argparse
import csv
import gzip
import html
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

EXPORT_URL = "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz"
USER_AGENT = "Nutryn-data/1.0 (support@smallprograms.dk)"
DEFAULT_CACHE = Path.home() / "Library" / "Caches" / "nutryn-data"

# OFF country tag -> our country code.
MARKETS = {
    "en:netherlands": "nl",
    "en:belgium": "be",
    "en:germany": "de",
    "en:austria": "at",
    "en:switzerland": "ch",
    "en:united-kingdom": "gb",
}

COLUMNS = [
    "code", "name", "brand", "countries", "quantity", "is_liquid",
    "serving_size", "serving_grams",
    "kcal", "protein", "carbohydrates", "fat",
    "sugar", "saturated_fat", "fibre", "salt",
    "last_modified",
]

BARCODE = re.compile(r"^\d{8}$|^\d{12,14}$")
LIQUID = re.compile(r"\d\s*(ml|cl|dl|l)\b", re.IGNORECASE)
KJ_PER_KCAL = 4.184


def download(cache: Path, refresh: bool) -> Path:
    """The export in the cache; downloaded again when older than a day."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "openfoodfacts-products.csv.gz"
    if path.exists() and not refresh and time.time() - path.stat().st_mtime < 86_400:
        print(f"Using cached export from {time.ctime(path.stat().st_mtime)}")
        return path
    print(f"Downloading {EXPORT_URL} ...")
    partial = path.with_suffix(".partial")
    request = urllib.request.Request(EXPORT_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, open(partial, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if total and done % (100 << 20) < (1 << 20):
                print(f"  {done >> 20} / {total >> 20} MB")
    os.replace(partial, path)
    return path


def number(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # drops NaN


def clean(text: str) -> str:
    """Single spaces, and HTML entities ("&#039;", even "&amp;amp;amp;") as the characters they stand for."""
    text = text or ""
    for _ in range(8):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return " ".join(text.split())


def plausible(kcal: float, protein: float, carbohydrates: float, fat: float) -> bool:
    if not 0 <= kcal <= 950:
        return False
    if any(not 0 <= value <= 100 for value in (protein, carbohydrates, fat)):
        return False
    if protein + carbohydrates + fat > 105:
        return False
    expected = 4 * protein + 4 * carbohydrates + 9 * fat
    return abs(kcal - expected) <= max(15, 0.25 * expected)


def select(export: Path) -> tuple[dict[str, dict], dict[str, int]]:
    csv.field_size_limit(sys.maxsize)
    products: dict[str, dict] = {}
    stats = {"rows": 0, "in_markets": 0, "with_values": 0, "plausible": 0}
    with gzip.open(export, "rt", encoding="utf-8", errors="replace", newline="") as file:
        reader = csv.reader(file, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = next(reader)
        index = {name: i for i, name in enumerate(header)}

        def field(row: list[str], name: str) -> str:
            i = index.get(name)
            return row[i] if i is not None and i < len(row) else ""

        for row in reader:
            stats["rows"] += 1
            tags = field(row, "countries_tags").split(",")
            countries = sorted({MARKETS[tag] for tag in tags if tag in MARKETS})
            if not countries:
                continue
            stats["in_markets"] += 1

            code = field(row, "code").strip()
            name = clean(field(row, "product_name"))
            kcal = number(field(row, "energy-kcal_100g"))
            if kcal is None and (kj := number(field(row, "energy_100g"))) is not None:
                kcal = kj / KJ_PER_KCAL
            protein = number(field(row, "proteins_100g"))
            carbohydrates = number(field(row, "carbohydrates_100g"))
            fat = number(field(row, "fat_100g"))
            if not BARCODE.match(code) or not name or None in (kcal, protein, carbohydrates, fat):
                continue
            stats["with_values"] += 1
            if not plausible(kcal, protein, carbohydrates, fat):
                continue
            stats["plausible"] += 1

            serving_grams = number(field(row, "serving_quantity"))
            if serving_grams is not None and not 0 < serving_grams <= 2000:
                serving_grams = None
            quantity = clean(field(row, "quantity"))
            product = {
                "code": code,
                "name": name,
                "brand": clean(field(row, "brands").split(",")[0]),
                "countries": ",".join(countries),
                "quantity": quantity,
                "is_liquid": "1" if LIQUID.search(quantity) else "0",
                "serving_size": clean(field(row, "serving_size")) if serving_grams else "",
                "serving_grams": serving_grams,
                "kcal": kcal,
                "protein": protein,
                "carbohydrates": carbohydrates,
                "fat": fat,
                "sugar": number(field(row, "sugars_100g")),
                "saturated_fat": number(field(row, "saturated-fat_100g")),
                "fibre": number(field(row, "fiber_100g")),
                "salt": number(field(row, "salt_100g")),
                "last_modified": int(number(field(row, "last_modified_t")) or 0),
            }
            # The same barcode twice: keep the most recently edited.
            existing = products.get(code)
            if existing is None or product["last_modified"] > existing["last_modified"]:
                products[code] = product
    return products, stats


def write(products: dict[str, dict], output: Path) -> None:

    def text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.3f}".rstrip("0").rstrip(".")
        return str(value).replace("\t", " ")

    with gzip.open(output, "wt", encoding="utf-8", newline="") as file:
        file.write("\t".join(COLUMNS) + "\n")
        for code in sorted(products):
            file.write("\t".join(text(products[code][column]) for column in COLUMNS) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="download the export even if the cached one is recent")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help=f"download folder (default {DEFAULT_CACHE})")
    args = parser.parse_args()

    started = time.time()
    export = download(args.cache, args.refresh)
    products, stats = select(export)
    output = args.cache / "off-selection.tsv.gz"
    write(products, output)

    per_country = {code: 0 for code in MARKETS.values()}
    for product in products.values():
        for country in product["countries"].split(","):
            per_country[country] += 1
    print(f"Rows in export:        {stats['rows']:>10,}")
    print(f"In 1.0 markets:        {stats['in_markets']:>10,}")
    print(f"With name and values:  {stats['with_values']:>10,}")
    print(f"Plausible:             {stats['plausible']:>10,}")
    print(f"Unique barcodes:       {len(products):>10,}")
    for country, count in per_country.items():
        print(f"  {country}: {count:>10,}")
    print(f"Written to {output} in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
