# Why Batch Process Skips Files (status=complete, unchanged)

## What you see

When you run with **resume** (e.g. `--resume-manifest <path>`) and the manifest already has completed entries, the tool may skip files with:

```text
Skipping 1 of N: filename.pptx (status=complete, unchanged)
...
Skipped (unchanged): N
```

## Manifest location and default behaviour

- **Default (no flags):** Each run creates a **new** run folder under the **input directory** at `<staging_root>/<run_id>/manifest.json` (default `staged_runs`). Run_id is UTC (e.g. `20260313_153000`). Per-file artifacts go under `staged_runs/<run_id>/outputs/<relative_path>/`.- **Running from different folders:** The manifest is always in CWD. So if you run from project root you get a manifest in the project root; if you run from another folder you get a manifest there. Different working directories therefore use different manifests—which is intended so runs from different places don’t share state.
- **Resume:** Skipping as “complete, unchanged” only happens when you **explicitly** pass `--resume-manifest <path>`. Then the tool loads that manifest and skips completed/unchanged files.

## Root cause (when using --resume-manifest)

1. **Which manifest is used**  
   When you pass `--resume-manifest PATH`, the batch resume state is read from that file. Entries there were written by a previous run that used that same path.

2. **How entries are keyed**  
   Each manifest entry is keyed by **file path** (stored as given; matching uses the path string or the **resolved absolute path**). So:
   - Entries are **not** keyed by filename only; different paths (e.g. different folders) do not collide.
   - If a previous run from the same CWD processed the same path (e.g. `documents_to_review/file.pptx`), that path’s entry is reused.

3. **What “unchanged” means**  
   “Unchanged” means the **file fingerprint** of the input file matches the fingerprint stored in the manifest for that path. The fingerprint is **mtime (nanoseconds) + size**. So:
   - If the file’s modification time and size have not changed since it was last marked complete, it is skipped.
   - This avoids reprocessing when nothing changed; it can also skip files you expect to process if the manifest is from an earlier run and the files really haven’t changed.

4. **How files got marked complete**  
   They were marked **complete** (or degraded/failed/skipped) in a **previous run** that wrote to the manifest you are now loading with `--resume-manifest`. That run processed those paths and stored fingerprints. This run reuses that manifest, so any path whose fingerprint still matches is skipped.

## What you can do

### 1. Default: fresh run (no resume)

Each run gets a new run folder under the input directory and processes all files:

```bash
python altgen.py process "documents_to_review"
```

Manifest and artifacts live under `documents_to_review/staged_runs/<run_id>/`.

### 2. Force reprocess (no manifest at all)

Ignore any manifest for this run: do not read or write a manifest; process all discovered files:

```bash
python altgen.py process "documents_to_review" --force
```

Or:

```bash
python altgen.py process "documents_to_review" --reprocess
```

No manifest is read or written; no files are skipped as “unchanged”.

### 3. Resume from a specific manifest

To reuse a previous run’s state (skip completed/unchanged, reprocess changed):

```bash
python altgen.py process "documents_to_review" --resume-manifest path/to/batch_20260312_120017_a1b2c3d4_manifest.json
```

### 4. Inspect why something was skipped (debug)

To see which manifest is used and the fingerprint comparison when a file is skipped, run with **verbose** so debug logs are enabled:

```bash
python altgen.py process "documents_to_review" --verbose
```

When a file is skipped, the log will include:
- The **manifest path** (e.g. `.../batch_<timestamp>_<id>_manifest.json`) in an info-level message.
- At **debug** level: **current** and **stored** fingerprint for that file (mtime_ns and size), so you can confirm they match.

## Summary

| Item              | Detail                                                                 |
|-------------------|------------------------------------------------------------------------|
| Default manifest  | New file per run: `batch_<timestamp>_<id>_manifest.json` in **CWD**   |
| Manifest location | CWD = where you run the command; different folders → different manifests |
| Resume            | Only when you pass `--resume-manifest PATH`                           |
| Entry keying      | File path (string + resolved absolute path for matching)              |
| “Unchanged”       | Input file fingerprint (mtime_ns + size) equals stored fingerprint    |
| Why skipped       | When resuming: manifest has COMPLETE + matching fingerprint           |
| Force             | `--force` or `--reprocess` → no manifest read or written; all files processed |
| Debug skip logic  | `--verbose` → manifest path and (at DEBUG) fingerprint comparison     |
