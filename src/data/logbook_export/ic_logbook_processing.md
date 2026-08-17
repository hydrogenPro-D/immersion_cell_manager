# IC Logbook, processing notes

How the **IC Logbook** tab's data is produced from `src/data/IC_Logbook.xlsx`, the
decisions behind it, and the known data quirks to remember when a **newer version
of the Excel** is dropped in and re-processed.

> Keep this file up to date whenever the source workbook or the extraction changes.

---

## Source & pipeline

- **Source workbook:** `src/data/IC_Logbook.xlsx` (maintained by the team in Excel).
- **Extraction script:** `src/data/logbook_export/extract_logbook.py`
  (run from the repo root: `python src/data/logbook_export/extract_logbook.py`).
  Requires `openpyxl`.
- **Outputs (all UTF-8):** `src/data/logbook_export/`
  - `ic_logbook.csv`, all experiments, one row each, with a `category` column. **DB-ready.**
  - `by_category/<category>.csv`, same rows split per category.
  - `summary_scoreboard.csv`, the manual snapshots from the Summary sheet.
- **App reads:** `src/data/logbook_manager.py` (`LogbookManager`) loads the CSVs;
  `src/gui/logbook_gui.py` (`LogbookTab`) renders them. **Phase 1 = CSV.** The plan is
  to later import into the DB (`icm.ic_logbook` + `usp_ic_logbook_*` procs) and swap the
  manager's backing store, the GUI is source-agnostic and won't change.

### Workbook shape (as of 2026-08)
- 1 **Summary** sheet + **19** project-category logbook sheets.
- **~1,908** experiments total (rows with an `IC_ID`).
- Every logbook sheet shares 11 columns:
  `IC_ID · Owner · Assembled by · Disassembled by · Test length [h] · Protocol · Format ·
  Experiment finished on · Notes · Archived in · Plot`.
- **Sulfidized** additionally has 4 columns: `Synthesis recipe · Synthesis time (h) ·
  Synthesis temperature (°C) · Coating test on`, preserved and shown only on that tab.

---

## Decisions (locked in)

- **Storage:** build the UI on CSV first, then import into the DB.
- **Editable** in the app (add/edit/delete), once on the DB.
- **Summary is computed live** from the rows (not copied from the Excel dashboard).
- **Preserve per-category extra columns** (a column shows on a tab only if that category
  has data in it).
- **Key:** DB uses an **auto-increment `id`**; `ic_id` is a plain, **non-unique** text
  column (ids are neither unique nor consistent, see below).

---

## Normalization the extractor applies

- **Headers** normalized to snake_case fields; source header typos/spacing unified
  (`"Archived in" / "Archived in " / "Arhived in"` → `archived_in`).
- **Sheet names** trimmed (`"Gen3-Gen3 "` → `Gen3-Gen3`, `"MLF "` → `MLF`) → used as `category`.
- **Dates** (`Experiment finished on`): normalized to ISO `YYYY-MM-DD` in
  `experiment_finished_on`, with the original kept verbatim in
  `experiment_finished_on_raw`. Text dates are read as **European `dd/mm/yyyy`**.
- **Whitespace** trimmed on cell values (e.g. `"Anders "` → `"Anders"`).
- **Encoding:** written UTF-8; accented names (Balázs, Péter, Ákos) are correct in the
  files (a terminal may *display* them as `�`, that's not corruption).

---

## Known data quirks, CHECK THESE on every new Excel version

### Rows with a missing `IC_ID` are kept (H2-FOAM = 61)
The extractor **keeps a row that has any real experiment field even when the `IC_ID` is
missing**, those are still experiments, and the DB's auto-increment `id` is the key. A row
is skipped only if it has **no experiment field at all**. H2-FOAM had one such no-ID row
(owner Paolo, protocol `QnD_RT_3h_v2`, finished 2025-03-14, notes "0,5 mm PTFE"), so the
live count is **61**, matching the Excel summary.
- **Clean stray annotation cells in the source Excel.** Because any populated experiment
  field keeps the row, a stray value in a data column reads as a phantom experiment.
  H2-FOAM once had a bare `60` typed into a Notes cell (a mis-entry, since removed) that
  briefly pushed the count to 62. If a category count looks one-too-high, look for a stray
  cell in the sheet.
- Takeaway: the Excel Summary numbers are hand-maintained and can still differ from the
  live count; the app shows the true count of actual rows.

### Test-length mis-entries, fix in the source Excel too
Three `Test length [h]` cells were typed as **times** (`h:mm:ss`) instead of hours. These
are data-entry mistakes; the intended run lengths are below. They are **corrected
automatically on every extraction** by the `CORRECTIONS` map in `extract_logbook.py`, so
re-running the extractor stays correct even though the Excel still holds the times:

| category | IC_ID | in sheet | corrected to |
|---|---|---|---|
| Gen2-Gen2 | `IC0570_CatNNF_AnoNNF_rho1276_AUX1Cat_AUX2Ano_3-8` | `19:05:00` | **168** |
| Gen2-Gen2 | `IC0571_CatNNF_AnoNNF_rho1276_AUX1Cat_AUX2Ano_3-7` | `19:05:00` | **168** |
| Gen3Cat-Gen2 | `IC1355_CatB8111-TR-P2_AnoNNF_rho1281_4-4` | `01:15:00` | **48** |

Fixing them in `IC_Logbook.xlsx` eventually is still nice (then drop the entry from
`CORRECTIONS`). The loader also converts any *other* leftover `h:mm:ss` value to decimal
hours as a fallback.

### `ic_id` is not unique / not always standard
- **14 duplicate `ic_id`s** (each appears 2×). Some are the *same* experiment cross-listed
  in two category sheets (often also "Long term testing"); others are genuinely different
  rows sharing an id. → this is exactly why the key is an auto-increment `id`.
- **51 `ic_id`s** don't match the `IC####_…` pattern (e.g. `IC0401A/B/C…` variants, a stray
  `C1300…`, descriptive ids like `CatAWJ_004, AnoNNF`).
- **32 rows** have no `experiment_finished_on`.

### Other
- **Summary sheet, stray value:** cell **`O4`** (`36400`, in the
  "Still running tests cumulated length [h]" row) **can be removed / ignored**, it's
  leftover and not used by the app.
- **Owner-name inconsistencies:** `Balázs` vs `Balazs`, `Filippo` vs `Filippo?`, `Gergo`,
  trailing spaces. Left **as-is** (didn't want to merge people/typos silently).
- **Multi-line Notes:** some `notes` contain line breaks, the CSV quotes them correctly;
  load with a **CSV-aware** importer (not naive line splitting).
- **Summary category order:** the app's Summary per-category table follows the Excel
  "1. Summary" sheet's matrix order (`SUMMARY_CATEGORY_ORDER` in `logbook_manager.py`),
  not the sheet-tab order. The matrix uses different labels, mapping assumed:
  `Gen2 I Gen3 → Gen2-Gen3Ano`, `Gen3 I Gen2 → Gen3Cat-Gen2`. The matrix also **omits**
  `Gen4Cat-Gen2`, `External | Meshes`, `Iron tests`; these are appended after the listed
  ones. Re-verify if categories are added/renamed.

---

## Re-processing a newer Excel (checklist)

1. Replace `src/data/IC_Logbook.xlsx` with the new version (close it in Excel first, the
   file locks while open and the extractor can't read it).
2. Run `python src/data/logbook_export/extract_logbook.py`.
3. Check the printed report: per-category counts, total, and any **unparseable dates**
   (kept in `_raw`).
4. Re-check the quirks above, especially:
   - new/renamed **categories** (update `SUMMARY_CATEGORY_ORDER`),
   - new **per-category extra columns** (add to `EXTRA_COLUMNS` in `logbook_manager.py`),
   - any **rows with data but no `IC_ID`** (decide keep vs skip),
   - Summary counts vs live counts (expected to differ; live is truth).
5. Once on the DB: re-import via the pyodbc loader (Azure SQL can't `BULK INSERT` local
   files, see `src/data/sql/integration/MIGRATION_PLAYBOOK.md`).
