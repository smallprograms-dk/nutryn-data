# nutryn-data

The scripts that build the food database shipped with [Nutryn](https://smallprograms.dk), a food diary for iPhone by Small Programs (a trading name of INVAR IT ApS).

Each app release ships a database built with these scripts. The repository is tagged with the build date (for example `2026.11.12`, the same date as `built` in the database's `meta` table), so the data in any app version can be traced back to the code that made it.

## Open Food Facts selection

`scripts/off.py` downloads the [Open Food Facts](https://world.openfoodfacts.org) export and keeps the products sold in the Netherlands, Belgium, Germany, Austria, Switzerland and the United Kingdom that have a name and plausible nutrition values per 100 g (energy, protein, carbohydrates and fat present; energy 0–950 kcal; each macro 0–100 g; energy within 25 % or 15 kcal of 4 × protein + 4 × carbohydrates + 9 × fat).

```sh
python3 -I scripts/off.py
```

Python 3.11 or later, standard library only. The export (±1.5 GB) and the result go to `~/Library/Caches/nutryn-data` (`--cache` to change).

## National food tables

`scripts/national.py` reads three national food tables into one format (per 100 g; unknown values stay empty, "trace" counts as 0; salt from the table or sodium × 2.5; vitamins and minerals converted to one unit per nutrient):

| Table | Publisher | Version | Source file |
|---|---|---|---|
| NEVO | RIVM, Bilthoven (Netherlands) | 2025/9.0 | Not included. Request it at [rivm.nl/nevo](https://www.rivm.nl/en/dutch-food-composition-database) and put the zip in the cache folder |
| BLS | Max Rubner-Institut (Germany) | 4.0 | Downloaded from [blsdb.de](https://blsdb.de) |
| CoFID | McCance and Widdowson (UK) | 2021 | Downloaded from [gov.uk](https://www.gov.uk/government/publications/composition-of-foods-integrated-dataset-cofid) |

```sh
python3 -I scripts/national.py
```

## Building the database

`scripts/build.py` combines the Open Food Facts selection, the national tables and the app's own names, keywords and portions into `nutryn-foods.sqlite` (±127 MB): one `food` table, vitamins and minerals in `micro`, named portions in `portion` (with Dutch, German and English names in `portion_name`), full-text indexes `national_fts` and `off_fts` (diacritics ignored; split so the small national tables are searched instantly) and a `meta` table with versions and counts.

```sh
python3 -I scripts/off.py
python3 -I scripts/national.py
python3 -I scripts/build.py --food-data ../Nutryn/FoodData
```

The names, keywords and portions (`--food-data`) are kept in the private app repository, because the names are derived from NEVO. Without that folder the build leaves out NEVO and the portions for the national tables, and says so.

### Checks

The build stops, and keeps the previous database, when:
- a source has fewer foods than expected, or more than 5 % fewer than in the previous build (`--accept-changes` when that is expected, for example a new table version);
- a known barcode is missing (popular products in each market, listed in `KNOWN_BARCODES`) or a known search finds nothing;
- energy or macros are out of range, a food has no single default portion, a portion weighs 0 g or more than 2 kg, or a portion belongs to a food that is not in the tables;
- the database is larger than 150 MB.

The Open Food Facts names are cleaned of HTML entities (`&#039;` → `'`), sometimes encoded several times.

### Publication

**The built database contains NEVO data and is never published** (not committed, not attached to a release). Only the scripts and the Open Food Facts selection are public: from the first app release on, the selection used by each app version is attached to the GitHub release of its tag (ODbL share-alike).

## Licences

- **Code** in this repository: [MIT](LICENSE).
- **Open Food Facts data**, and the selection built from it: [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/); individual contents under the [Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/). Contains information from Open Food Facts, which is made available under the ODbL. The data is contributed by volunteers and may contain errors.
- **National food tables** keep their own terms and are not redistributed by this repository:
  - NEVO-online version 2025/9.0, RIVM, Bilthoven. © RIVM; used with permission of the RIVM.
  - Max Rubner-Institut (2025): Bundeslebensmittelschlüssel (BLS), Version 4.0 – Deutsche Nährstoffdatenbank. Karlsruhe. DOI: [10.25826/Data20251217-134202-0](https://doi.org/10.25826/Data20251217-134202-0). Licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Nutryn edits the data in part: selection of nutrients, conversion to portions and own translations of food names.
  - McCance and Widdowson's Composition of Foods Integrated Dataset (CoFID) 2021, Public Health England. Contains public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
