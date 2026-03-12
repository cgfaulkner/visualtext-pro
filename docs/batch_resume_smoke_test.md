# Batch resume / checkpoint smoke-test checklist

Manual end-to-end checks for batch resume and checkpointing. Manifest path: **current working directory** → `batch_manifest.json` (i.e. `Path.cwd() / "batch_manifest.json"`). Run all commands from the **project root** unless a step says otherwise; use a dedicated test directory so the manifest is isolated.

**Prerequisites:** Config with a working ALT provider for online runs (e.g. `config.yaml`). Two or three small `.pptx` files in a test folder (e.g. `documents_to_review/` or a temp dir).

---

## (1) Normal run then restart — skips COMPLETE

**Goal:** First run processes all files; second run skips them with status=COMPLETE/complete, unchanged.

1. From project root, remove any existing checkpoint:  
   `rm -f batch_manifest.json`
2. Run batch (provider must be online):  
   `python altgen.py batch documents_to_review`  
   (or `python altgen.py process <path_to_folder_with_pptx>`)
3. **Expected:**  
   - `Discovered N PPTX file(s).`  
   - `Processing 1 of N: <file>.pptx` … for each file  
   - `Batch complete` with `Succeeded: N`, `Failed: 0`  
   - `batch_manifest.json` exists in project root (cwd)
4. Run the same command again (same cwd).
5. **Expected:**  
   - Manifest is loaded (there may or may not be an explicit “Resumed…” log line).  
   - `Skipping 1 of N: <file>.pptx (status=COMPLETE/complete, unchanged)` for each file  
   - `Skipped (unchanged): N`  
   - No “Processing” lines for already-complete files

---

## (2) Interrupted run — PROCESSING → PENDING then processed

**Goal:** Run is interrupted (e.g. Ctrl+C) while a file is PROCESSING; on next run that item is reset to PENDING and processed.

1. Start with a clean manifest:  
   `rm -f batch_manifest.json`
2. Run batch with at least 2 files; interrupt (Ctrl+C) shortly after the first “Processing 2 of N” appears (so file 1 is COMPLETE, file 2 was PROCESSING).
3. **Expected:**  
   - `batch_manifest.json` exists. One file COMPLETE, and the next is either PROCESSING or left retryable (PENDING) depending on interruption timing; next run should process it.
4. Run the same batch command again from the same cwd.
5. **Expected:**  
   - Load resets PROCESSING → PENDING (no “stale processing” left)  
   - First file skipped: `Skipping 1 of N: ... (status=COMPLETE/complete, unchanged)`  
   - Second file processed: `Processing 2 of N: ...`  
   - Batch completes with both files done

---

## (3) Lockfile present — .lock exists → LOCKED; retry after removing lock

**Goal:** If `<file>.pptx.lock` exists next to a file, run skips that file as LOCKED; after removing the lock, next run processes it. The lockfile must be in the **same directory** as the PPTX (lock check is file-adjacent).

1. Start with a clean manifest and at least one file:  
   `rm -f batch_manifest.json`
2. Create a lock file next to one of the PPTX files (same directory):  
   `touch documents_to_review/<one>.pptx.lock`
3. Run batch:  
   `python altgen.py batch documents_to_review`
4. **Expected:**  
   - For the locked file: `Skipping K of N: <one>.pptx (LOCKED)` (or LOCKED/locked depending on logger)  
   - Batch may process other files; manifest has one item with status `locked`
5. Remove the lock:  
   `rm documents_to_review/<one>.pptx.lock`
6. Run the same batch again.
7. **Expected:**  
   - That file is retried (LOCKED is retryable): `Processing K of N: <one>.pptx`  
   - No “Skipping … (LOCKED)” for that file

---

## (4) Fingerprint mismatch — touch/modify file → PENDING, reprocessed

**Goal:** After a file is COMPLETE, changing the file (e.g. touch) changes its fingerprint; next run sets status to PENDING and reprocesses it.

1. Ensure one file is already COMPLETE (e.g. run (1) once).
2. Touch (or slightly modify) that file:  
   `touch documents_to_review/<file>.pptx`  
   If touch doesn’t trigger a fingerprint change on your system, make a real edit (e.g. copy the pptx to a new filename, or modify and save).
3. Run batch again from same cwd:  
   `python altgen.py batch documents_to_review`
4. **Expected:**  
   - Log line like `Input changed; reprocessing: <file>.pptx`  
   - Then `Processing K of N: <file>.pptx`  
   - File is processed again; manifest updated with new fingerprint and status

---

## (5) Provider offline abort exit 2 — no manifest created/modified

**Goal:** When provider is offline and `--offline-mode=abort`, process exits with code 2 and **does not** create or modify `batch_manifest.json`.

1. Remove manifest:  
   `rm -f batch_manifest.json`
2. Make provider unavailable (e.g. stop local server or use a config pointing to an unreachable host). Ensure `offline-mode` is `abort` (default).
3. Run batch:  
   `python altgen.py batch documents_to_review`  
   (non-interactive: `python altgen.py --non-interactive batch documents_to_review` if needed)
4. **Expected:**  
   - Exit code **2**  
   - Message like `Discovered N files; provider offline; aborting.` and provider/health info  
   - **No** `batch_manifest.json` created in cwd (confirm with `ls batch_manifest.json` or `test -f batch_manifest.json && echo "FAIL" || echo "OK"`)
5. If a manifest already existed from a previous run, run again with provider still offline; manifest must be **unchanged** (same content/mtime).

---

## (6) Offline placeholder path — DEGRADED; next run skips DEGRADED if unchanged

**Goal:** With provider offline and `--offline-mode=fill-missing` (and e.g. `--yes` or `--non-interactive`), run records DEGRADED; second run skips those files when fingerprint unchanged.

1. Remove manifest:  
   `rm -f batch_manifest.json`
2. Ensure provider is offline; use placeholder mode and non-interactive:  
   `python altgen.py batch documents_to_review --offline-mode=fill-missing --yes`
3. **Expected:**  
   - Run completes. Expect exit **1** unless you also pass `--allow-degraded-exit0`.  
   - `batch_manifest.json` exists; queue items have status `degraded` and `file_fingerprint` in result  
   - Logs indicate placeholder/DEGRADED run
4. Run the same command again **without** changing the PPTX files.
5. **Expected:**  
   - `Skipping K of N: <file>.pptx (status=DEGRADED/degraded, unchanged)` for each previously degraded file  
   - No reprocessing of unchanged files
6. (Optional) Touch one file and run again; that file should show `Input changed; reprocessing` and then be processed again (DEGRADED + fingerprint mismatch → PENDING).

---

## (7) Different working directory ⇒ different manifest

**Goal:** Because the manifest path is `Path.cwd() / "batch_manifest.json"`, running from a different directory uses a different manifest. Resume state is per-cwd; this is expected behavior.

1. From project root, ensure a manifest exists (e.g. run (1) once so `batch_manifest.json` is in project root).
2. **Expected:** `batch_manifest.json` exists in project root.
3. Change into a subfolder that contains (or can discover) PPTX files:  
   `cd documents_to_review`  
   (or another subdir that works with your batch target)
4. Run the same batch command (e.g. `python altgen.py batch .` from that subdir, or point at the current dir).
5. **Expected:**  
   - A **new** `batch_manifest.json` is created in the **current** (sub)directory.  
   - The manifest in project root is **untouched**.  
   - No bug — resume is scoped by working directory.

---

## Quick reference

| Scenario              | Manifest path        | Key check |
|-----------------------|----------------------|-----------|
| (1) Normal + restart   | cwd / batch_manifest.json | Second run: “Skipping … (status=COMPLETE/complete, unchanged)” |
| (2) Interrupted        | same                 | After restart: PROCESSING → PENDING, then “Processing” for that file |
| (3) Lockfile           | same (lockfile same dir as PPTX) | “Skipping … (LOCKED)”; after rm .lock, “Processing” for that file |
| (4) Fingerprint       | same                 | “Input changed; reprocessing” then “Processing” |
| (5) Exit 2 offline     | none created/updated | Exit code 2; no batch_manifest.json (or unchanged) |
| (6) Placeholder path   | cwd / batch_manifest.json | Exit 1 unless --allow-degraded-exit0; next run “Skipping … (status=DEGRADED/degraded, unchanged)” |
| (7) Different cwd      | per-cwd              | New manifest in subdir; root manifest untouched |
