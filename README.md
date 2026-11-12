# nutryn-data

The scripts that build the food database shipped with [Nutryn](https://smallprograms.dk), a food diary for iPhone by Small Programs (a trading name of INVAR IT ApS).

Work in progress: the Open Food Facts selection and the national food tables are done; names in three languages and the SQLite build follow.

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

## Licences

- **Code** in this repository: [MIT](LICENSE).
- **Open Food Facts data**, and the selection built from it: [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/); individual contents under the [Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/). Contains information from Open Food Facts, which is made available under the ODbL. The data is contributed by volunteers and may contain errors.
- **National food tables** keep their own terms and are not redistributed by this repository:
  - NEVO-online version 2025/9.0, RIVM, Bilthoven. © RIVM; used with permission of the RIVM.
  - Max Rubner-Institut (2025): Bundeslebensmittelschlüssel (BLS), Version 4.0 – Deutsche Nährstoffdatenbank. Karlsruhe. DOI: [10.25826/Data20251217-134202-0](https://doi.org/10.25826/Data20251217-134202-0). Licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Nutryn edits the data in part: selection of nutrients, conversion to portions and own translations of food names.
  - McCance and Widdowson's Composition of Foods Integrated Dataset (CoFID) 2021, Public Health England. Contains public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
