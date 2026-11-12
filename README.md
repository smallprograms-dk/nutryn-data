# nutryn-data

The scripts that build the food database shipped with [Nutryn](https://smallprograms.dk), a food diary for iPhone by Small Programs (a trading name of INVAR IT ApS).

Work in progress: the Open Food Facts selection is done; the national food tables and the SQLite build follow.

## Open Food Facts selection

`scripts/off.py` downloads the [Open Food Facts](https://world.openfoodfacts.org) export and keeps the products sold in the Netherlands, Belgium, Germany, Austria, Switzerland and the United Kingdom that have a name and plausible nutrition values per 100 g (energy, protein, carbohydrates and fat present; energy 0–950 kcal; each macro 0–100 g; energy within 25 % or 15 kcal of 4 × protein + 4 × carbohydrates + 9 × fat).

```sh
python3 -I scripts/off.py
```

Python 3.11 or later, standard library only. The export (±1.5 GB) and the result go to `~/Library/Caches/nutryn-data` (`--cache` to change).

## Licences

- **Code** in this repository: [MIT](LICENSE).
- **Open Food Facts data**, and the selection built from it: [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/); individual contents under the [Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/). Contains information from Open Food Facts, which is made available under the ODbL. The data is contributed by volunteers and may contain errors.
- **National food tables** (NEVO, BLS, CoFID) keep their own terms, listed here once they are added.
