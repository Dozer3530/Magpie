# Sample import files (for testing)

Fake — but realistically shaped — input files for exercising Magpie's import
pipeline end-to-end without waiting on a real Survey123 export or lab report.

## Regenerate

```
python sample_imports/_generate.py
```

Produces, for week `2026-W22`, one of each per crop:

| File | Feeds | Notes |
|------|-------|-------|
| `<crop>_survey123_<week>.csv` | **Survey123 import** | ID + Location + Date_Time + growth stage + 3× TDR + disease presence/severity + insects + petal test. 9 rows (one per monitoring point). ~1 in 3 points carries a disease flag. |
| `<crop>_lab_PT2R_<week>.csv` | **Lab import** | `SampleID` + `ReportDate` + full nutrient panel, rate codes, and ratios. 7 rows (2 points intentionally have no lab result, like real life). |

Column names are copied verbatim from `Static <Crop> Template.xlsx`, so the
importer matches them by exact name — no manual column mapping needed. Values
are random but plausible (seeded RNG, so regeneration is reproducible).

## How to test

1. Launch a frontend — desktop (`python -m app`) **or** web (`python -m webapp`).
   Run **one at a time** (they share `data/packages.sqlite`).
2. Make sure week **2026-W22** exists (the web context bar's **+ Week** button,
   or the desktop week selector).
3. **Survey123 import** → upload `<crop>_survey123_2026-W22.csv`. The ID column
   auto-detects; commit.
4. **Lab import** → upload `<crop>_lab_PT2R_2026-W22.csv`. Assign each row to a
   monitoring point (the `SampleID` shows e.g. `CA-M1` to make this obvious),
   then commit. `SampleID`/`ReportDate` are ignored on import — same as a real
   PT2R file.
5. **Week overview** → points fill in (lime = complete, blue = partial,
   grey = empty). **Observations** → review/edit the merged rows. **Export** →
   build the weekly package.

> ⚠️ These import directly into your real `data/packages.sqlite`. To clean up
> afterwards, delete week 2026-W22 (Delete button / desktop selector) — that
> cascades the test observation rows for every crop.

## Why the CSVs aren't committed

The `Location` column holds the templates' **real** monitoring-point lat/longs,
so generated `*.csv` files are git-ignored. Only this README and the generator
script are tracked.
