#!/usr/bin/env python3
"""Build nutryn-foods.sqlite, the read-only product database of the app.

Input (run off.py and national.py first):
  off-selection.tsv.gz    Open Food Facts selection        (cache folder)
  national-foods.tsv.gz   NEVO, BLS and CoFID, one format   (cache folder)
  FoodData/               names, keywords and portions      (--food-data)

FoodData lives in the private app repository, because the names are
derived from NEVO. Without it the database is built without NEVO and
without portions for the national tables (a warning says so). With it,
every NEVO food must have a name, or the build stops.

The built database contains NEVO data and must never be published.

Tables
  food        one row per product, values per 100 g (or 100 ml, is_liquid)
  micro       vitamins and minerals per 100 g (national tables)
  portion     named portions per product
  portion_name  portion key -> Dutch, German, English
  food_fts    full-text index over names, keywords and brand
  meta        versions and counts, shown in the app under Sources

Usage: python3 -I scripts/build.py [--cache DIR] [--food-data DIR] [--output FILE]
Standard library only.
"""

import argparse
import csv
import gzip
import json
import os
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

DEFAULT_CACHE = Path.home() / "Library" / "Caches" / "nutryn-data"
DEFAULT_FOOD_DATA = Path(__file__).resolve().parents[2] / "Nutryn" / "FoodData"
SCHEMA_VERSION = 1
VALUES = ["kcal", "protein", "carbohydrates", "fat", "sugar", "saturated_fat", "fibre", "salt"]

SCHEMA = f"""
CREATE TABLE food (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,          -- nevo, bls, cofid, off
    source_id TEXT NOT NULL,
    barcode TEXT,
    name TEXT NOT NULL,            -- fallback display name
    name_nl TEXT, name_de TEXT, name_en TEXT,
    source_name TEXT,              -- name as published by the source
    brand TEXT,
    countries TEXT,                -- off: comma-separated country codes
    quantity TEXT,                 -- off: package size as printed
    is_liquid INTEGER NOT NULL DEFAULT 0,
    {", ".join(f"{v} REAL" for v in VALUES)}
);
CREATE TABLE micro (
    food_id INTEGER NOT NULL REFERENCES food(id),
    key TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (food_id, key)
) WITHOUT ROWID;
CREATE TABLE portion (
    food_id INTEGER NOT NULL REFERENCES food(id),
    key TEXT,                      -- translated via portion_name
    label TEXT,                    -- free text (off serving size)
    millilitres REAL,
    grams REAL NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE portion_name (key TEXT PRIMARY KEY, nl TEXT, de TEXT, en TEXT) WITHOUT ROWID;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;
"""

INDEXES = """
CREATE UNIQUE INDEX food_barcode ON food(barcode) WHERE barcode IS NOT NULL;
CREATE INDEX food_source ON food(source, source_id) WHERE source != 'off';  -- off: by barcode
CREATE INDEX portion_food ON portion(food_id);
CREATE VIRTUAL TABLE food_fts USING fts5(
    name, name_nl, name_de, name_en, keywords, brand,
    content='',
    tokenize='unicode61 remove_diacritics 2'
);
"""


def read_tsv(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    csv.field_size_limit(sys.maxsize)
    with opener(path, "rt", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file, delimiter="\t", quoting=csv.QUOTE_NONE))


def number(text: str) -> float | None:
    return float(text) if text not in ("", None) else None


def fail(message: str) -> None:
    sys.exit(f"Build stopped: {message}")


def load_food_data(folder: Path) -> dict | None:
    if not folder.is_dir():
        return None
    data = {}
    for name in ("nevo-names", "nevo-portions", "bls-portions", "cofid-portions", "portion-names"):
        path = folder / f"{name}.tsv"
        if not path.exists():
            fail(f"{path} is missing")
        data[name] = read_tsv(path)
    return data


def build(cache: Path, food_data: dict | None, output: Path, accept_changes: bool) -> dict:
    national = read_tsv(cache / "national-foods.tsv.gz")
    off = read_tsv(cache / "off-selection.tsv.gz")

    names = {r["nevo_code"]: r for r in food_data["nevo-names"]} if food_data else {}
    if food_data:
        nevo_codes = {r["source_id"] for r in national if r["source"] == "nevo"}
        if missing := sorted(nevo_codes - names.keys(), key=int):
            fail(f"{len(missing)} NEVO foods without a name in nevo-names.tsv: {', '.join(missing[:10])}")
        if stale := sorted(names.keys() - nevo_codes, key=int):
            print(f"Note: {len(stale)} names for NEVO codes that no longer exist: {', '.join(stale[:10])}")

    partial = output.with_suffix(".partial")
    partial.unlink(missing_ok=True)
    db = sqlite3.connect(partial)
    db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA page_size=4096;" + SCHEMA)

    ids: dict[tuple[str, str], int] = {}
    fts_rows: list[tuple] = []
    counts: dict[str, int] = {}

    def insert(source, source_id, *, barcode=None, name, name_nl=None, name_de=None, name_en=None,
               source_name=None, brand=None, countries=None, quantity=None, is_liquid=0, values, keywords=""):
        cursor = db.execute(
            f"INSERT INTO food (source, source_id, barcode, name, name_nl, name_de, name_en, source_name, brand, "
            f"countries, quantity, is_liquid, {', '.join(VALUES)}) VALUES ({', '.join('?' * (12 + len(VALUES)))})",
            (source, source_id, barcode, name, name_nl, name_de, name_en, source_name, brand or None,
             countries, quantity or None, is_liquid, *values))
        ids[(source, source_id)] = cursor.lastrowid
        fts_rows.append((cursor.lastrowid, name, name_nl or "", name_de or "", name_en or "", keywords, brand or ""))
        counts[source] = counts.get(source, 0) + 1
        return cursor.lastrowid

    # National tables
    micro_rows = []
    for r in national:
        values = [number(r[v]) for v in VALUES]
        if r["source"] == "nevo":
            if not food_data:
                continue
            n = names[r["source_id"]]
            food_id = insert("nevo", r["source_id"], name=n["name_nl"], name_nl=n["name_nl"], name_en=n["name_en"],
                             source_name=r["name_local"], is_liquid=int(r["is_liquid"]), values=values,
                             keywords=" ".join(filter(None, [n["keywords_nl"], n["keywords_en"]])).replace(",", " "))
        elif r["source"] == "bls":
            food_id = insert("bls", r["source_id"], name=r["name_local"], name_de=r["name_local"],
                             name_en=r["name_en"] or None, source_name=r["name_local"], values=values)
        else:
            food_id = insert("cofid", r["source_id"], name=r["name_en"], name_en=r["name_en"],
                             source_name=r["name_en"], values=values)
        for key, value in (json.loads(r["micros"]) if r["micros"] else {}).items():
            micro_rows.append((food_id, key, value))
    db.executemany("INSERT INTO micro VALUES (?, ?, ?)", micro_rows)

    # Open Food Facts
    for r in off:
        insert("off", r["code"], barcode=r["code"], name=r["name"], brand=r["brand"], countries=r["countries"],
               quantity=r["quantity"], is_liquid=int(r["is_liquid"]), values=[number(r[v]) for v in VALUES])

    # Portions
    portion_rows = []
    orphans: list[str] = []
    if food_data:
        keys = {r["portion"]: (r["nl"], r["de"], r["portion"]) for r in food_data["portion-names"]}

        def nevo_key(r: dict) -> str:
            # NEVO portions carry their own Dutch label. One English key can
            # stand for several Dutch words (slice: snee, plak, plakje), so a
            # different Dutch label gets its own key.
            en, nl = r["portion_en"], r["portion_nl"]
            vocabulary = keys.get(en)
            if vocabulary and vocabulary[0] == nl:
                return en
            key = f"{en}#{nl}"
            keys.setdefault(key, (nl, vocabulary[1] if vocabulary else None, en))
            return key

        for source, rows, code in (("nevo", food_data["nevo-portions"], "nevo_code"),
                                   ("bls", food_data["bls-portions"], "source_id"),
                                   ("cofid", food_data["cofid-portions"], "source_id")):
            for r in rows:
                food_id = ids.get((source, r[code]))
                if food_id is None:
                    orphans.append(f"{source} {r[code]}")
                    continue
                key = nevo_key(r) if source == "nevo" else r["portion"]
                portion_rows.append((food_id, key, None, number(r["millilitres"]), float(r["grams"]), int(r["is_default"])))
        if untranslated := sorted(k for k, (nl, de, _) in keys.items() if not nl or not de):
            fail(f"portion keys without Dutch or German name: {', '.join(untranslated)}")
        db.executemany("INSERT INTO portion_name VALUES (?, ?, ?, ?)", [(k, *v) for k, v in keys.items()])
    for r in off:
        if r["serving_grams"]:
            portion_rows.append((ids[("off", r["code"])], None, r["serving_size"], None, float(r["serving_grams"]), 1))
    db.executemany("INSERT INTO portion VALUES (?, ?, ?, ?, ?, ?)", portion_rows)

    # Indexes, full-text search, meta
    db.executescript(INDEXES)
    db.executemany("INSERT INTO food_fts (rowid, name, name_nl, name_de, name_en, keywords, brand) VALUES (?, ?, ?, ?, ?, ?, ?)", fts_rows)
    db.execute("INSERT INTO food_fts(food_fts) VALUES ('optimize')")
    versions = {r["source"]: r["version"] for r in national}
    off_export = cache / "openfoodfacts-products.csv.gz"
    meta = {
        "schema_version": str(SCHEMA_VERSION),
        "built": date.today().isoformat(),
        "version_nevo": versions.get("nevo", "") if food_data else "",
        "version_bls": versions.get("bls", ""),
        "version_cofid": versions.get("cofid", ""),
        "version_off": date.fromtimestamp(off_export.stat().st_mtime).isoformat() if off_export.exists() else "",
        **{f"count_{source}": str(count) for source, count in counts.items()},
        "count_portion": str(len(portion_rows)),
    }
    db.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
    db.commit()
    db.execute("ANALYZE")
    db.execute("VACUUM")
    problems = check(db, meta, previous_meta(output), food_data is not None, orphans, accept_changes)
    db.close()
    size = partial.stat().st_size
    if size > MAX_SIZE:
        problems.append(f"database is {size / 1e6:.0f} MB, more than {MAX_SIZE / 1e6:.0f} MB")
    if problems:
        fail("checks failed; the previous database is kept.\n  - " + "\n  - ".join(problems))
    os.replace(partial, output)
    return meta


# Checks (D6). A failing check stops the build before the new file replaces
# the old one. Known barcodes: popular products in each market; when one
# disappears from Open Food Facts for good, replace it here.
MIN_COUNTS = {"nevo": 2000, "bls": 7000, "cofid": 2500, "off": 500_000}
MAX_DROP = 0.05  # largest allowed drop per source compared with the previous build
MAX_SIZE = 150e6
KNOWN_BARCODES = {
    "8718906888463": "AH halfvolle melk (NL)",
    "8710956001151": "Hertog Jan Pilsener (NL)",
    "4001686028636": "Haribo Goldbären (DE)",
    "7622201775421": "Milka Alpenmilch (DE)",
    "4002044039103": "Dr. Oetker Ristorante (DE)",
    "5000157024909": "Heinz Baked Beans (GB)",
    "5000159407236": "Mars (GB)",
}
KNOWN_SEARCHES = [("appel", "nevo"), ("Vollkornbrot", "bls"), ("haggis", "cofid"), ("halfvolle melk", "off")]


def previous_meta(output: Path) -> dict:
    if not output.exists():
        return {}
    try:
        with sqlite3.connect(f"file:{output}?mode=ro", uri=True) as old:
            return dict(old.execute("SELECT key, value FROM meta"))
    except sqlite3.Error:
        return {}


def check(db: sqlite3.Connection, meta: dict, previous: dict, with_nevo: bool, orphans: list[str], accept_changes: bool) -> list[str]:
    problems = []
    for source, minimum in MIN_COUNTS.items():
        if source == "nevo" and not with_nevo:
            continue
        count = int(meta.get(f"count_{source}", 0))
        if count < minimum:
            problems.append(f"{source}: {count:,} foods, expected at least {minimum:,}")
        before = int(previous.get(f"count_{source}", 0))
        if before and count < before * (1 - MAX_DROP) and not accept_changes:
            problems.append(f"{source}: {count:,} foods, {before:,} in the previous build (use --accept-changes if expected)")
    for barcode, label in KNOWN_BARCODES.items():
        if not db.execute("SELECT 1 FROM food WHERE barcode = ?", (barcode,)).fetchone():
            problems.append(f"known barcode missing: {barcode} {label}")
    for term, source in KNOWN_SEARCHES:
        if with_nevo or source != "nevo":
            match = " ".join(f'"{word}"*' for word in term.split())
            hit = db.execute("SELECT 1 FROM food_fts JOIN food f ON f.id = food_fts.rowid "
                             "WHERE food_fts MATCH ? AND f.source = ? LIMIT 1", (match, source)).fetchone()
            if not hit:
                problems.append(f'search "{term}" finds nothing in {source}')
    foods = db.execute("SELECT count(*) FROM food").fetchone()[0]
    indexed = db.execute("SELECT count(*) FROM food_fts").fetchone()[0]
    if indexed != foods:
        problems.append(f"search index has {indexed:,} rows, food has {foods:,}")
    # Carbohydrates up to 110 g: CoFID gives them as monosaccharide equivalents,
    # so sugar comes to 105 g per 100 g.
    bad_values = db.execute("SELECT count(*) FROM food WHERE kcal NOT BETWEEN 0 AND 950 OR protein NOT BETWEEN 0 AND 100 "
                            "OR carbohydrates NOT BETWEEN 0 AND 110 OR fat NOT BETWEEN 0 AND 100").fetchone()[0]
    if bad_values:
        problems.append(f"{bad_values} foods with energy or macros out of range")
    defaults = db.execute("SELECT count(*) FROM (SELECT food_id FROM portion GROUP BY food_id HAVING sum(is_default) != 1)").fetchone()[0]
    if defaults:
        problems.append(f"{defaults} foods without exactly one default portion")
    bad_portions = db.execute("SELECT count(*) FROM portion WHERE grams <= 0 OR grams > 2000").fetchone()[0]
    if bad_portions:
        problems.append(f"{bad_portions} portions weigh 0 g or more than 2 kg")
    if orphans:
        problems.append(f"{len(orphans)} portions for foods that are not in the tables: {', '.join(orphans[:5])}")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help=f"cache folder (default {DEFAULT_CACHE})")
    parser.add_argument("--food-data", type=Path, default=DEFAULT_FOOD_DATA, help="FoodData folder of the app repository")
    parser.add_argument("--output", type=Path, help="database file (default: cache folder/nutryn-foods.sqlite)")
    parser.add_argument("--accept-changes", action="store_true", help="allow counts to drop more than 5 %% compared with the previous build")
    args = parser.parse_args()
    output = args.output or args.cache / "nutryn-foods.sqlite"

    started = time.time()
    food_data = load_food_data(args.food_data)
    if food_data is None:
        print(f"Warning: {args.food_data} not found. Building without NEVO and without portions for the national tables.")
    meta = build(args.cache, food_data, output, args.accept_changes)
    for key, value in meta.items():
        print(f"  {key:16} {value}")
    print(f"Checks passed. Written {output} ({output.stat().st_size / 1e6:.0f} MB) in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
