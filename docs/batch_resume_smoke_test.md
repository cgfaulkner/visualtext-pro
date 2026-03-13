# Batch resume / checkpoint smoke-test checklist

Manual end-to-end checks for batch resume and checkpointing. **Manifest location:** Manifests and per-file artifacts live under the **input directory** at `<input_root>/staged_runs/<run_id>/manifest.json` (config: `staged_batch.staging_root`). Resume with `--resume-manifest <path>` or `--run-id <id>`. Run all commands from the **project root** unless a step says otherwise; use a dedicated test directory (e.g. `documents_to_review/`) so the run folder is under that input root.

**Prerequisites:** Config with a working ALT provider for online runs (e.g. `config.yaml`). Two or three small `.pptx` files in a test folder (e.g. `documents_to_review/` or a temp dir).

**To force a full reprocess (no manifest read or written):** Use `--force` or `--reprocess` (e.g. `python altgen.py process "documents_to_review" --force`). See [batch_manifest_skip_explained.md](batch_manifest_skip_explained.md).

---

## (1) Normal run then restart — skips COMPLETE (resume)

**Goal:** First run processes all files; second run **with `--resume-manifest`** skips them with status=COMPLETE/complete, unchanged.

1. From project root, run batch once (provider must be online):  
   `python altgen.py process documents_to_review`
2. **Expected:**  
   - Startup prints e.g. `Manifest strategy: run_id=<run_id> manifest=<input_path>/staged_runs/<run_id>/manifest.json`  
   - `Discovered N PPTX file(s).`  
   - `Processing 1 of N: <file>.pptx` for each file  
   - `Batch complete` with `Succeeded: N`, `Failed: 0`  
   - Manifest exists at `documents_to_review/staged_runs/<run_id>/manifest.json` (run_id is UTC timestamp, e.g. `20260313_153000`).
3. Run again **with resume**, using the run_id from step 1 or the manifest path:  
   `python altgen.py process documents_to_review --run-id <run_id>`  
   or `python altgen.py process documents_to_review --resume-manifest documents_to_review/staged_runs/<run_id>/manifest.json`
4. **Expected:**  
   - Startup prints e.g. `Manifest strategy: run_id=<run_id> manifest=...`  
   - `Skipping 1 of N: <file>.pptx (status=COMPLETE/complete, unchanged)` for each file  
   - `Skipped (unchanged): N`  
   - No "Processing" lines for already-complete files

---

## (2) Interrupted run — PROCESSING → PENDING then processed (resume)

**Goal:** Run is interrupted (e.g. Ctrl+C) while a file is PROCESSING; on next run **with `--resume-manifest`** that item is reset to PENDING and processed.

1. Run batch with at least 2 files:  
   `python altgen.py process <path_to_folder_with_pptx>`  
   Note the manifest path printed at start.
2. Interrupt (Ctrl+C) shortly after the first "Processing 2 of N" appears (so file 1 is COMPLETE, file 2 was PROCESSING).
3. **Expected:**  
   - A manifest file exists at `<input>/staged_runs/<run_id>/manifest.json`. One file COMPLETE, the next PROCESSING or PENDING; next run should process it when resuming.
4. Run again with that run_id or manifest:  
   `python altgen.py process <path> --run-id <run_id>` or `--resume-manifest <path>/staged_runs/<run_id>/manifest.json`
5. **Expected:**  
   - Load resets PROCESSING → PENDING (no "stale processing" left)  
   - First file skipped: `Skipping 1 of N: ... (status=COMPLETE/complete, unchanged)`  
   - Second file processed: `Processing 2 of N: ...`  
   - Batch completes with both files done

---

## (3) Lockfile present — .lock exists → LOCKED; retry after removing lock

**Goal:** If `<file>.pptx.lock` exists next to a file, run skips that file as LOCKED; after removing the lock, next run processes it. The lockfile must be in the **same directory** as the PPTX (lock check is file-adjacent).

1. Run batch once so a manifest exists in cwd (or use an existing one); note the manifest path.
2. Create a lock file next to one of the PPTX files (same directory):  
   `touch documents_to_review/<one>.pptx.lock`
3. Run batch:  
   `python altgen.py process documents_to_review`
4. **Expected:**  
   - For the locked file: `Skipping K of N: <one>.pptx (LOCKED)` (or LOCKED/locked depending on logger)  
   - Batch may process other files; manifest has one item with status `locked`
5. Remove the lock:  
   `rm documents_to_review/<one>.pptx.lock`
6. Run again with the same run_id or manifest path:  
   `python altgen.py process documents_to_review --run-id <run_id>`
7. **Expected:**  
   - That file is retried (LOCKED is retryable): `Processing K of N: <one>.pptx`  
   - No “Skipping … (LOCKED)” for that file

---

## (4) Fingerprint mismatch — touch/modify file → PENDING, reprocessed

**Goal:** After a file is COMPLETE, changing the file (e.g. touch) changes its fingerprint; next run sets status to PENDING and reprocesses it.

1. Ensure one file is already COMPLETE (e.g. run (1) once) and note the manifest path.
2. Touch (or slightly modify) that file:  
   `touch documents_to_review/<file>.pptx`  
   If touch doesn’t trigger a fingerprint change on your system, make a real edit (e.g. copy the pptx to a new filename, or modify and save).
3. Run again with that run_id or manifest:  
   `python altgen.py process documents_to_review --run-id <run_id>`
4. **Expected:**  
   - Log line like `Input changed; reprocessing: <file>.pptx`  
   - Then `Processing K of N: <file>.pptx`  
   - File is processed again; manifest updated with new fingerprint and status

---

## (5) Provider offline abort exit 2 — no manifest created/modified

**Goal:** When provider is offline and `--offline-mode=abort`, process exits with code 2 and **does not** create or modify any manifest.

1. Use a fresh run (no existing run folder for this input) or remove the run folder.
2. Make provider unavailable (e.g. stop local server or use a config pointing to an unreachable host). Ensure `offline-mode` is `abort` (default).
3. Run batch:  
   `python altgen.py process documents_to_review`  
   (non-interactive: `python altgen.py --non-interactive process documents_to_review` if needed)
4. **Expected:**  
   - Exit code **2**  
   - Message like `Discovered N files; provider offline; aborting.` and provider/health info  
   - **No** new run folder or manifest created under input (no `staged_runs/<run_id>/manifest.json` for this run).
5. If a run folder already existed from a previous run, run again with provider still offline; that manifest must be **unchanged** (no new manifest write).

---

## (6) Offline placeholder path — DEGRADED; next run skips DEGRADED if unchanged

**Goal:** With provider offline and `--offline-mode=fill-missing` (and e.g. `--yes` or `--non-interactive`), run records DEGRADED; second run skips those files when fingerprint unchanged.

1. Use a fresh run or remove the run folder for this input.
2. Ensure provider is offline; use placeholder mode and non-interactive:  
   `python altgen.py process documents_to_review --offline-mode=fill-missing --yes`
3. **Expected:**  
   - Run completes. Expect exit **1** unless you also pass `--allow-degraded-exit0`.  
   - Manifest at `documents_to_review/staged_runs/<run_id>/manifest.json` exists; queue items have status `degraded` and `file_fingerprint` in result  
   - Logs indicate placeholder/DEGRADED run
4. Run the same command again **without** changing the PPTX files.
5. **Expected:**  
   - `Skipping K of N: <file>.pptx (status=DEGRADED/degraded, unchanged)` for each previously degraded file  
   - No reprocessing of unchanged files
6. (Optional) Touch one file and run again; that file should show `Input changed; reprocessing` and then be processed again (DEGRADED + fingerprint mismatch → PENDING).

---

## (7) Run folder under input root

**Goal:** Manifest and artifacts are always under the **input directory** at `staged_runs/<run_id>/`. Running with a different input path uses a different run folder. Resume is per run_id / manifest path.

1. From project root, run batch once (e.g. (1) step 1) with `documents_to_review` as input; note the run_id and manifest path printed.
2. **Expected:** Manifest exists at `documents_to_review/staged_runs/<run_id>/manifest.json`.
3. Run batch with a **different** input path (e.g. another folder that contains PPTX files).
4. **Expected:**  
   - A **new** run folder is created under that input path (`<other_input>/staged_runs/<new_run_id>/`).  
   - The first run's manifest is **untouched**.  
   - Resume is scoped by input root and run_id.

---

## Quick reference

| Scenario              | Manifest path        | Key check |
|-----------------------|----------------------|-----------|
| (1) Normal + restart   | `<input>/staged_runs/<run_id>/manifest.json`; use `--run-id` or `--resume-manifest` on 2nd run | Second run: "Skipping … (status=COMPLETE/complete, unchanged)" |
| (2) Interrupted        | same; use `--run-id` or `--resume-manifest` on 2nd run | After restart: PROCESSING → PENDING, then "Processing" for that file |
| (3) Lockfile           | same (lockfile same dir as PPTX) | "Skipping … (LOCKED)"; after rm .lock, "Processing" for that file |
| (4) Fingerprint       | same; use `--run-id` to see skip/reprocess | "Input changed; reprocessing" then "Processing" |
| (5) Exit 2 offline     | none created/updated | Exit code 2; no new run folder or manifest |
| (6) Placeholder path   | `<input>/staged_runs/<run_id>/manifest.json` | Exit 1 unless --allow-degraded-exit0; next run "Skipping … (status=DEGRADED/degraded, unchanged)" |
| (7) Different input    | per input path (new run folder per input) | New run folder under other input; first run's manifest untouched |
