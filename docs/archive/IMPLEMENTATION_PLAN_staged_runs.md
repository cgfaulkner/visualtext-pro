# Implementation Plan: Staged Runs (Manifest & Per-File Artifacts)

**Status: Implemented.** Current behavior is documented in [batch_completion_criteria.md](batch_completion_criteria.md) and the root README (batch/staged runs).

**Goal:** Move batch manifests and per-file artifacts out of project CWD into a per-input-root staged run folder for directory inputs. Keep non-staged single-file behavior unchanged when `manifest_path` is None.

**Reference:** Existing staged_runs plan; this document is the canonical implementation spec.

**Single source of truth:** All artifact path construction must go through `RunArtifacts(base_dir=...)`; no ad-hoc path joins elsewhere.

**Named constants (use in both shared/batch_manifest.py and shared/batch_queue.py so they do not drift):**

- `MANIFEST_REPLACE_RETRIES = 3` — number of retries for `os.replace` before fallback.
- `MANIFEST_RETRY_DELAYS_S = (0.1, 0.2, 0.4)` — delay in seconds before each retry (exponential backoff: 0.1 s, then 0.2 s, then 0.4 s). Use the same sequence in both modules.

**Cross-FS copy verification (single minimal rule for tests and implementation):**

- **Verify (artifact dir):** After copying the per-file artifact directory to the target, the target is valid iff it contains at least these paths (relative to the artifact dir root): `scan/visual_index.json` and `resolve/final_alt_map.json`. If either is missing, verification fails and sources must not be removed.
- **Verify (staged PPTX):** Target file exists and has suffix `.pptx`. Use this same rule everywhere (e.g. _commit_file cross-FS path and tests) so behavior is consistent.

---

## 1. Numbered Implementation Plan (File-Level)

### Phase A: Config and manifest atomicity (small PR)

1. **config.yaml**  
   Add top-level key `staged_batch` with single key `staging_root` (string, default `staged_runs`). Document in comments that it is under input root and visible (not hidden).

2. **shared/batch_manifest.py**  
   - In `save()`: write to `manifest.json.tmp` in same directory as `manifest_path` (i.e. `manifest_path.parent / (manifest_path.name + ".tmp")`). After write: fsync the file handle where available (e.g. `os.fsync(f.fileno())`), then `os.replace(temp_path, manifest_path)`. If `os.replace` fails: retry up to **MANIFEST_REPLACE_RETRIES** times with delays **MANIFEST_RETRY_DELAYS_S** (exponential backoff) to handle transient Windows locks or permissions; then try fallback copy-to-temp-on-same-dir, fsync, replace once. If replace still fails: do not delete the .tmp file; raise a clear error (e.g. "Manifest atomic replace failed: ... (close other processes holding the file?)") and fail safe. If `OSError` is `EXDEV` (cross-device), treat as unexpected when temp is in same dir as manifest—raise with guidance to ensure temp and manifest are on same volume.  
   - Ensure `output_dir` used for manifest parent is the run directory when called from staged flow.

3. **shared/batch_queue.py**  
   Same atomic write pattern as batch_manifest: use **MANIFEST_REPLACE_RETRIES** and **MANIFEST_RETRY_DELAYS_S**; temp path = `manifest_path.name + ".tmp"` in same dir, fsync, `os.replace`, retry with backoff, then same fallback; on unrecoverable failure leave .tmp and raise. EXDEV when temp is in same dir: treat as unexpected and error with guidance.

4. **Docs**  
   Add one-line note in batch_completion_criteria.md (or batch_manifest_skip_explained.md): "Manifest is written atomically to manifest.json.tmp then renamed to manifest.json; replace uses os.replace with fallback."

### Phase B: Run folder and manifest path resolution (altgen)

**Run folder & manifest — unambiguous rule**

- **inputs/ folder:** The `inputs/` directory under run_dir is currently **unused and reserved**; it will be empty. Create it for consistent layout and future use (e.g. staged input copies); no requirement to populate it in this implementation.
- **--manifest-dir and run_dir (chosen rule A):** When `--manifest-dir` is used, **run_dir equals manifest_dir** (artifacts colocate). So: `manifest_path = manifest_dir / "manifest.json"` and `run_dir = manifest_dir`; per-file artifacts live under `run_dir/outputs/<relative_path>/`. Resolution: if the value is absolute, use as-is; otherwise resolve relative to `input_root`. No requirement that manifest_dir be under input_root; when it is not, run_dir is still that directory and artifacts live under it. See **Examples** below for path combinations.
- **Examples (paths for flag combinations):**
  - **New run (no flags):** `run_id = "20260313_153000"` (UTC), `run_dir = input_root / "staged_runs" / "20260313_153000"`, `manifest_path = run_dir / "manifest.json"`, artifacts under `run_dir/outputs/<rel>/`.
  - **--run-id R:** `run_dir = input_root / "staged_runs" / "R"`, `manifest_path = run_dir / "manifest.json"`, artifacts under `run_dir/outputs/<rel>/`.
  - **--resume-manifest /abs/path/to/manifest.json:** `manifest_path = /abs/path/to/manifest.json`, `run_dir = manifest_path.parent` (so artifacts colocate under that parent: `run_dir/outputs/<rel>/`).
  - **--manifest-dir /abs/custom:** `run_dir = /abs/custom`, `manifest_path = /abs/custom/manifest.json`, artifacts under `run_dir/outputs/<rel>/`.
  - **--manifest-dir rel/subdir:** `run_dir = input_root / "rel/subdir"`, `manifest_path = run_dir / "manifest.json"`, artifacts under `run_dir/outputs/<rel>/`.

5. **shared/run_folder.py (new)**  
   New module with single responsibility: resolve run folder and manifest path.  
   - Function `resolve_run_folder_and_manifest(...)` (or equivalent name) with parameters: `input_root: Path`, `staging_root: str`, `run_id: Optional[str]`, `resume_manifest: Optional[Path]`, `manifest_dir: Optional[Path]`, `force: bool`.  
   - Precedence (explicit): `resume_manifest` (absolute path) > `run_id` (resume under input_root/staging_root) > `manifest_dir` (explicit dir) > new run with auto run_id.  
   - If both `run_id` and `resume_manifest` provided: use `resume_manifest`, log warning "resume_manifest overrides --run-id; using manifest at <path>".  
   - Auto run_id: UTC timestamp `datetime.utcnow().strftime("%Y%m%d_%H%M%S")`. If `run_dir = input_root / staging_root / run_id` already exists, try atomic suffixes `run_id + "-1"`, `"-2"`, ... up to N=10 using `run_dir.mkdir(parents=True, exist_ok=False)` in a loop; on first successful mkdir use that path. **Escape hatch after 10:** append a short random suffix (e.g. 4–8 hex chars) to the base run_id and retry mkdir (e.g. one attempt or until success with a small max retries); do not raise "could not create after 10 attempts" without trying the random-suffix fallback.  
   - For `manifest_dir`: resolve as absolute if passed absolute; otherwise resolve relative to `input_root`. Set `manifest_path = manifest_dir / "manifest.json"` and **run_dir = manifest_dir** (rule A: artifacts colocate).  
   - Return a small dataclass or tuple: `(run_dir: Path | None, manifest_path: Path | None, run_id: str | None, used_resume_manifest: bool)`.  
   - When `force` is True: return `(None, None, None, False)`.

6. **altgen.py**  
   - In `create_parser()` (process subparser): add `--run-id` (metavar ID, help: resume or create run folder under input_root/staged_runs/<id>; manifest at .../manifest.json). Add `--resume-manifest` (existing). Add `--manifest-dir` (metavar DIR, help: directory for manifest; resolved relative to input root unless absolute). Optionally add `--staging-root` (override config staged_batch.staging_root for this run).  
   - In `run_batch()`: when `args.path` is a directory (or glob base is a dir), set `input_root`; load config and get `staging_root = config.get("staged_batch", {}).get("staging_root", "staged_runs")`; override with `args.staging_root` if present. Call `resolve_run_folder_and_manifest(input_root, staging_root, getattr(args, "run_id", None), Path(args.resume_manifest) if getattr(args, "resume_manifest", None) else None, Path(args.manifest_dir) if getattr(args, "manifest_dir", None) else None, getattr(args, "force_reprocess", False))`. If `force_reprocess`: pass `manifest_path=None` to `process_batch` and log "Manifest strategy: ignored (--force); no manifest read or written." Else: create run_dir subdirs `inputs/` (reserved, empty), `outputs/` if run_dir is not None (mkdir parents, exist_ok). Log at start: "run_id=%s run_dir=%s manifest_path=%s" (info). Pass `manifest_path`, `input_root`, `run_dir` to `processor.process_batch(...)`.

7. **core/batch_processor.py**  
   - Extend `process_batch(self, files, manifest_path=None, input_root=None, run_dir=None)`. When `input_root` and `run_dir` are both provided, for each file: resolve `file_path` and `input_root` (e.g. `.resolve()`) and validate containment with `file_path.resolve().relative_to(input_root.resolve())` (catch ValueError); **symlink policy: resolve-and-validate containment**—no lexical-only checks. Then `rel = file_path.relative_to(input_root).parent` (or Path(".") if file at input_root). Set `artifact_base = run_dir / "outputs" / rel`. Pass artifact base to _process_single (Phase C). When manifest_path is None, do not pass run_dir/input_root (no artifact base).

### Phase C: Per-file artifact base (subprocess)

8. **core/batch_processor.py**  
   - Prefer CLI flag: extend subprocess invocation to pass `--artifact-base <path>` to `pptx_alt_processor.py process <file> ...`. If adding the flag to the single-file process command is awkward (e.g. many callers), use a single well-documented env var `VISUALTEXT_ARTIFACT_BASE_DIR`. If env var: set it only in the environment passed to `subprocess.run(..., env={**os.environ, "VISUALTEXT_ARTIFACT_BASE_DIR": str(artifact_base)})` so it does not leak to the parent; do not mutate `os.environ`. Clear/unset the key for the next iteration if reusing a runner.  
   - Document in code and in a short doc: "When set, per-file artifacts are written under this directory (outputs/<relative_path>/). Set only for the subprocess lifetime."

9. **pptx_alt_processor.py**  
   - In the `process` command path where `RunArtifacts.create_for_run` is called: if `--artifact-base` is set (or `os.environ.get("VISUALTEXT_ARTIFACT_BASE_DIR")` when using env), resolve it to a Path and pass `base_dir=that_path` to `RunArtifacts.create_for_run(input_path, base_dir=...)`. Otherwise keep current behavior (base_dir from pptx parent). Ensure no global state retains artifact base after the process command exits.

### Phase D: Commit / move / version behavior

10. **pptx_alt_processor.py (StagedBatchRunner._commit_file)**  
    - When moving or versioning the staged PPTX, also move/back up the corresponding artifact directory (e.g. `.alt_pipeline_*` in the same parent as the staged PPTX) as a group.  
    - **Step order and rollback:**  
      - **Same-FS:** (1) Rename artifact dir to final/versioned location; (2) if that fails, leave staged outputs intact and raise. (3) Rename staged PPTX to final/versioned location; (4) if that fails, attempt to rename artifact dir back to staged location (rollback); then leave staged outputs intact and raise. Do not delete sources until both PPTX and artifact dir are successfully activated at target.  
      - **Cross-FS:** (1) Copy artifact dir to target; **verify** using the plan’s single rule: target contains at least `scan/visual_index.json` and `resolve/final_alt_map.json`. (2) Copy staged PPTX to target; **verify**: target exists and is a `.pptx` file. (3) If both verifications pass, remove source artifact dir and source staged PPTX (or use atomic replace where possible). If any step fails: do not delete sources; leave staged outputs intact; raise clear error.  
    - Same FS: use atomic rename of directories where supported; on Windows, open-file locking may prevent rename—log at debug.  
    - Log actions at info (e.g. "Moving artifact dir X to Y") and detailed steps at debug.

11. **Path-length and Windows**  
    - Document in code or docs: Windows path length limits (260 for legacy); deep input nesting may hit this when `outputs/<relative_path>/` is long. Prefer keeping run_dir under input_root to avoid very long paths. Add a note in IMPLEMENTATION_PLAN or batch docs about Windows testing/mocking.

### Phase E: Tests

12. **tests/**  
    - Update any existing tests that assume manifest in CWD to use a dedicated temp input dir and assert manifest at `input_dir/staged_runs/<run_id>/manifest.json` (or config staging_root).  
    - Add all tests in Section 3 (Test Names and Assertions), including: test_run_id_collision_escape_hatch_after_ten, test_symlink_resolve_and_validate_containment, and strengthened test_force_skip_staging_no_manifest_written (no staged_runs created, no manifest written, legacy artifacts).

### Phase F: Docs and CLI help

13. **altgen.py**  
    - Ensure `--help` for process includes the new flags with the snippet text in Section 3.

14. **README.md and docs/**  
    - Update any sentence that says "manifest is in CWD" or "batch_*_manifest.json in current directory" to "manifest is under input_root/staged_runs/<run_id>/manifest.json (configurable)." Add short examples: fresh run, resume by run-id, resume by manifest, force reprocess (see Section 3).

### Phase G: Migration helper

15. **Migration helper**  
    - Implement as `altgen.py migrate-manifests` or `tools/migrate_manifests.py` per Section 4. Non-destructive by default; idempotent; optional `--delete-source` only after successful move and verify.

---

## 2. Functions/Classes to Adjust and Responsibilities

| File | Function/Class | Responsibility |
|------|----------------|----------------|
| **config.yaml** | (new key) | Add `staged_batch.staging_root` default `staged_runs`. |
| **shared/batch_manifest.py** | `BatchManifest.save()` | Write to manifest.json.tmp, fsync, os.replace; retry **MANIFEST_REPLACE_RETRIES** with **MANIFEST_RETRY_DELAYS_S**; fallback copy+replace; on EXDEV (same dir) error with guidance; leave .tmp and raise on unrecoverable failure. |
| **shared/batch_queue.py** | `BatchQueue.save()` | Same pattern; use same constants MANIFEST_REPLACE_RETRIES and MANIFEST_RETRY_DELAYS_S so both modules stay in sync. |
| **shared/run_folder.py** (new) | `resolve_run_folder_and_manifest(...)` | Precedence: resume_manifest > run_id > manifest_dir > new run. Auto run_id in UTC; collision suffix -1..-10 with atomic mkdir; escape hatch (e.g. random suffix) after 10. run_dir = manifest_dir when --manifest-dir (rule A). Return run_dir, manifest_path, run_id, used_resume_manifest. |
| **altgen.py** | `create_parser()` | Add args: --run-id, --resume-manifest (existing), --manifest-dir, optionally --staging-root. |
| **altgen.py** | `run_batch()` | Resolve input_root for dir/glob; load staging_root; call resolve_run_folder_and_manifest; create run_dir/inputs, run_dir/outputs; log run_id, run_dir, manifest_path; call process_batch(files, manifest_path, input_root, run_dir). |
| **core/batch_processor.py** | `process_batch(..., input_root=None, run_dir=None)` | Accept optional input_root, run_dir. For each file under input_root, compute artifact_base = run_dir/outputs/<rel>; pass to _process_single (env or CLI). Validate path under input_root; resolve symlinks per security note. |
| **core/batch_processor.py** | `_process_single(file_path, artifact_base=None)` | Invoke subprocess with env VISUALTEXT_ARTIFACT_BASE_DIR=artifact_base (or --artifact-base) only for that call; do not leak env. |
| **pptx_alt_processor.py** | process command | Read --artifact-base or VISUALTEXT_ARTIFACT_BASE_DIR; call RunArtifacts.create_for_run(pptx_path, base_dir=...) when set. |
| **shared/pipeline_artifacts.py** | `RunArtifacts.create_for_run(..., base_dir=None)` | Already supports base_dir; ensure when base_dir is set, run_dir is base_dir / ".alt_pipeline_<session_id>" (or equivalent) so artifacts live under outputs/<rel_path>/. |
| **pptx_alt_processor.py** | `StagedBatchRunner._commit_file` | Move/backup artifact dir with PPTX; defined step order; cross-FS **verify** per plan (artifact dir: scan/visual_index.json + resolve/final_alt_map.json; PPTX: exists and .pptx); rollback on failure; no source delete until both verified and activated. |

---

## 3. Test Names and Assertions (Pseudocode)

- **test_two_runs_create_distinct_run_folders**  
  Two fresh runs (same input dir, no --run-id, no --resume-manifest). Assert: two different run_id values; two directories under input_dir/staged_runs/; two manifest paths; manifests are different files.

- **test_run_id_resumes_existing_run_folder**  
  First run creates run_id R. Second run with `--run-id R`. Assert: same run_dir and manifest_path; manifest loaded; skipped count > 0 for unchanged files (or mock manifest with one COMPLETE item and assert skip).

- **test_resume_manifest_absolute_path**  
  Run with `--resume-manifest /abs/path/to/manifest.json`. Assert: manifest_path is that path; batch loads from it (mock or fixture).

- **test_force_skip_staging_no_manifest_written**  
  Run with `--force` (or `--reprocess`). Assert: manifest_path is None; **staged_runs/ (or staging_root) is NOT created** under input_root; **no manifest file is written** anywhere for that run; process_batch called with manifest_path=None; **artifacts follow legacy behavior** (e.g. per-file artifacts next to each PPTX or under pptx parent, not under any run_dir).

- **test_manifest_atomic_write_and_fallback**  
  Mock or patch os.replace to fail once, then succeed (or simulate cross-FS). Assert: fallback path is used (e.g. copy then replace); if replace always fails, clear error raised and .tmp not deleted.

- **test_concurrent_run_creation_avoids_collision**  
  Simulate or race: two callers try same run_id; one gets run_id, other gets run_id-1 (or -2). Assert: both get distinct run_dir paths; both created via atomic mkdir (exist_ok=False).

- **test_run_id_collision_escape_hatch_after_ten**  
  Simulate 10 existing run_dir candidates (run_id, run_id-1, ... run_id-9). Next call to resolve run folder. Assert: run_dir is created with **run_id plus random suffix** (e.g. run_id-<hex>) or equivalent escape hatch; no "could not create after 10 attempts" without having tried the fallback.

- **test_commit_moves_artifacts_with_pptx_same_fs**  
  StagedBatchRunner._commit_file with staged output and artifact dir on same FS. Assert: after commit, artifact dir exists at final location (or versioned path); original staged artifact dir no longer at source (or backed up as specified).

- **test_commit_moves_artifacts_cross_fs**  
  Mock or use tmpdir on different mount: commit uses copy+verify+replace (or delete source after verify). Assert: **verify** uses the plan’s rule (target artifact dir contains at least `scan/visual_index.json` and `resolve/final_alt_map.json`; target PPTX exists and is .pptx); target has artifact content; no partial state if replace fails; sources not removed if verify fails.

- **test_windows_replace_semantics**  
  On Windows runner (or mock platform to Windows): run atomic manifest write; document or assert behavior (e.g. replace succeeds when file not open, or skip test on non-Windows).

- **test_migration_moves_artifacts_and_manifest**  
  Migration helper: source CWD manifest + one artifact dir. Run migrate with input_root and run_id. Assert: manifest at input_root/staged_runs/run_id/manifest.json; artifact moved under outputs/<rel>/; manifest content updated if paths stored inside; idempotent second run leaves state unchanged.

- **test_env_var_not_leaked_between_runs**  
  Run two subprocess invocations in sequence (same process); first with VISUALTEXT_ARTIFACT_BASE_DIR set in env for subprocess only, second without. Assert: second subprocess does not see VISUALTEXT_ARTIFACT_BASE_DIR (e.g. by checking env in a test script invoked as subprocess).

- **test_precedence_resume_manifest_over_run_id**  
  Call with both --run-id and --resume-manifest. Assert: manifest_path equals --resume-manifest; warning logged that resume_manifest overrides run_id.

- **test_manifest_dir_resolution_relative_to_input_root**  
  Pass relative --manifest-dir. Assert: resolved path is input_root / manifest_dir; manifest_path = that / manifest.json; **run_dir equals that directory** (artifacts colocate under run_dir/outputs/<rel>/).

- **test_symlink_resolve_and_validate_containment**  
  With input_root or file_path involving symlinks: assert that containment is checked using **resolved** paths (resolve then relative_to); path that escapes input_root after resolution is rejected (ValueError or clear error).

---

## 4. CLI --help Text Snippets and README/Doc Lines

**--run-id**  
`Resume or create run folder under input root: input_root/<staging_root>/<id>/; manifest at .../manifest.json. Overridden by --resume-manifest if both given.`

**--resume-manifest**  
`Resume from an existing batch manifest at PATH (absolute). Takes precedence over --run-id and --manifest-dir.`

**--manifest-dir**  
`Directory for manifest file; manifest path is <dir>/manifest.json. If DIR is relative, resolved relative to input root; if absolute, used as-is. Derives run_dir for artifact base when applicable.`

**--staging-root** (optional)  
`Override config staged_batch.staging_root for this run (default: staged_runs).`

**Examples to add (README or docs):**

- Start a fresh run:  
  `python altgen.py process slides_dir`

- Resume by run-id:  
  `python altgen.py process slides_dir --run-id 20260313_153000`

- Resume by manifest:  
  `python altgen.py process slides_dir --resume-manifest /abs/path/to/manifest.json`

- Force reprocess (no manifest):  
  `python altgen.py process slides_dir --force`

**README/doc diff suggestions:**  
- Replace "Manifest is stored in the current working directory (e.g. batch_<timestamp>_<id>_manifest.json)" with "Manifest is stored under the input directory at <staging_root>/<run_id>/manifest.json (default staging_root: staged_runs). Use --run-id to resume or --resume-manifest for an explicit path."  
- Add a "Batch processing and resume" subsection with the four examples above.

---

## 5. Migration Helper Spec

**Command:** `altgen.py migrate-manifests` or `tools/migrate_manifests.py` (invocable as `python tools/migrate_manifests.py`).

**Args:**

- `--input-root` (required): Target input root; manifests will be moved to `input_root/<staging_root>/<run_id>/manifest.json`.
- `--run-id`: Use this run_id for the migrated manifest(s). If omitted, auto-generate one (UTC YYYYMMDD_HHMMSS) or one per manifest with suffix.
- `--staging-root`: Default `staged_runs`; override from config or this flag.
- `--yes`: Non-interactive; perform migration without prompting.
- `--delete-source`: After successful move and verification, remove source manifest (and optionally artifact dirs). Default: false (non-destructive).
- `--move-artifacts`: Also move per-file artifact dirs (e.g. .alt_pipeline_*) from CWD or adjacent to old manifest into `input_root/<staging_root>/<run_id>/outputs/<rel_path>/`. Default: true when migrating manifest (recommended).
- `--dry-run`: Print what would be moved; do not write.

**Behavior:**

- Find old CWD manifests: `batch_*_manifest.json` or `batch_*_*_manifest.json` in current working directory (or configurable source dir).
- For each manifest: validate JSON; compute target path `input_root/<staging_root>/<run_id>/manifest.json`; create run_dir and inputs/outputs if needed; copy manifest to .tmp, fsync, replace to manifest.json; if manifest contains paths to artifact dirs, optionally move those dirs to outputs/<rel_path>/ and update manifest if paths are stored.
- Verify: after move, manifest at target is readable and contains expected keys.
- Idempotent: if target already exists and content matches, skip or no-op (document).
- Safety: no destructive delete unless `--delete-source`; on failure, leave source in place and do not remove .tmp.

**Safety considerations:**  
- Do not overwrite target manifest if it already exists and differs unless user confirms (or --overwrite flag with warning).  
- Resolve paths to avoid symlink traversal; refuse to move if any path escapes input_root.  
- Log every move and verification step.

---

## 6. Acceptance Checklist (Pass/Fail Criteria)

| # | Requirement | Pass criteria |
|---|-------------|---------------|
| 1 | Run folder under input root | For directory input, run_dir is input_root/<staging_root>/<run_id>/ (or manifest_dir when --manifest-dir); contains inputs/ (reserved, empty), outputs/, manifest.json. |
| 2 | Config staging_root | staged_batch.staging_root is read from config; default staged_runs. |
| 3 | --run-id | Using --run-id <id> sets manifest_path = run_dir/manifest.json; resume or create that run folder. |
| 4 | --resume-manifest | Using --resume-manifest <path> uses that absolute path; precedence over --run-id (with warning). |
| 5 | New run auto run_id | New run uses UTC YYYYMMDD_HHMMSS; if run_dir exists, suffix -1..-10 with atomic mkdir; then escape hatch (e.g. random suffix) so unique run_dir is always created. |
| 6 | --manifest-dir | Resolved relative to input_root if relative, else absolute as-is; manifest_path = dir/manifest.json; **run_dir = manifest_dir** (artifacts colocate under run_dir/outputs/<rel>/). |
| 7 | Per-file artifacts | Artifacts under run_dir/outputs/<relative_path>/; batch passes artifact base via CLI or env only for subprocess. |
| 8 | Env not leaked | VISUALTEXT_ARTIFACT_BASE_DIR (if used) set only in subprocess env; not in parent after run. |
| 9 | Commit moves artifacts | _commit_file moves/backs up artifact dir with PPTX; defined step order; cross-FS verify uses single rule (artifact dir: scan/visual_index.json + resolve/final_alt_map.json; PPTX: exists and .pptx); rollback leaves staged intact; no source delete until both verified and activated. |
| 10 | Manifest atomicity | Write to manifest.json.tmp; fsync; os.replace; retry with backoff on failure; then fallback; EXDEV in same dir treated as error with guidance; clear error and no .tmp delete on unrecoverable failure. |
| 11 | Precedence | resume_manifest > run_id > manifest_dir > config staging_root > default staged_runs; conflict warning when applicable. |
| 12 | Timezone | Auto run_id uses UTC. |
| 13 | Path safety | **Resolve-and-validate containment**: paths resolved then checked under input_root; no lexical-only containment; symlink escape rejected. |
| 14 | Windows | Document replace/lock semantics; test or mock Windows where feasible. |
| 15 | Migration helper | Optional command; finds CWD manifests; moves to input_root/staging_root/run_id/; optional artifact move; idempotent; no delete without --delete-source. |
| 16 | Logging | Log run_id, run_dir, manifest_path at start; debug log .tmp write and replace; on resume log skip/process counts. |
| 17 | Tests | All listed tests added/updated (including force/reprocess: no staged_runs, no manifest, legacy artifacts; run_id escape hatch; symlink resolve-and-validate); CI with tmpdir and cleanup. |
| 18 | Docs & help | --help and README/docs updated; examples for fresh run, resume by run-id, resume by manifest, force. |
| 19 | Force/reprocess | With --force/--reprocess: staged_runs/ (staging_root) not created; no manifest written; artifacts follow legacy (next to PPTX or pptx parent). |

---

## 7. Edge Cases and Constraints

- **Atomic rename:** Only guaranteed on same FS. Temp file must be created in the same directory as manifest.json. **Why replace might fail:** Windows file locking (another process holding the file), permissions, or (rare) EXDEV. **Behavior:** Retry os.replace up to **MANIFEST_REPLACE_RETRIES** with **MANIFEST_RETRY_DELAYS_S** (exponential backoff); then fallback copy-to-temp-in-same-dir, fsync, replace once. If still failing: leave .tmp in place and raise clear error (e.g. "Manifest atomic replace failed: ... (close other processes holding the file?)"). **EXDEV:** If temp is in same directory as manifest, EXDEV should not occur; if it does, treat as unexpected and raise with guidance (e.g. ensure temp and manifest are on same volume).
- **Windows:** Replace may fail if file is open. Retry/backoff as above. Path length 260 (legacy)—avoid very deep outputs/<rel_path>/.
- **Deep input nesting:** On Windows, watch path length when outputs/<relative_path>/ is long; document or add a guard (e.g. warn when path exceeds 200 chars).
- **CI tests:** Use tmpdir (e.g. pytest tmp_path); ensure no leftover files; cleanup in teardown.
- **--manifest-dir (rule A):** run_dir always equals manifest_dir when --manifest-dir is used; artifacts always live under run_dir/outputs/<rel>/ whether manifest_dir is inside or outside input_root. No separate "artifact base under input_root" when --manifest-dir is outside input_root.
- **Symlinks:** **Policy: resolve-and-validate containment.** Resolve input_root and file paths (e.g. .resolve()); require resolved file_path to be under resolved input_root (relative_to); if not, reject with clear error. No lexical-only containment.

---

## 8. Suggested Commit Message

```
chore(manifest): move manifests into input-root staged_runs/<run_id>/manifest.json and add --run-id/--resume-manifest flags
```

---

## 9. Summary of Files to Create or Change

**Create:**  
- `shared/run_folder.py` (run folder and manifest path resolution)  
- `docs/IMPLEMENTATION_PLAN_staged_runs.md` (this file)  
- `tools/migrate_manifests.py` or `altgen.py` subcommand migrate-manifests  

**Modify:**  
- `config.yaml`  
- `shared/batch_manifest.py`  
- `shared/batch_queue.py`  
- `altgen.py`  
- `core/batch_processor.py`  
- `pptx_alt_processor.py`  
- `shared/pipeline_artifacts.py` (if any tweak for base_dir under outputs/<rel>)  
- `README.md`  
- `docs/batch_completion_criteria.md`  
- `docs/batch_manifest_skip_explained.md`  
- `docs/batch_resume_smoke_test.md`  
- `tests/` (new and updated tests as listed)

No code is included in this plan; only design, file-level edits, test specs, and CLI/doc text.
