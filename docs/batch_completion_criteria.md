# Batch Completion Criteria

**criteria_version:** 1.0

This document defines what marks a file as DONE vs NOT DONE in batch processing, and the metadata required for stable checkpoint/resume. Implementations must follow these rules so that restarting a batch skips only files that are DONE and unchanged.

**Manifest file location:** The checkpoint manifest is stored by default in the current working directory as `batch_manifest.json` (i.e. `Path.cwd() / "batch_manifest.json"`). The batch runner creates this file on first run when processing with resume support. Only the manifest object writes the checkpoint; the queue does not persist directly.

---

## 1. Canonical statuses

The only statuses used in the batch manifest are (enum-style names; stored as lowercase in JSON):

| Status        | Meaning |
| ------------- | ------- |
| PENDING       | Not yet processed; will be processed or retried. |
| PROCESSING    | Currently being processed; on load, reset to PENDING (crash recovery). |
| COMPLETE      | Processor exited 0; no further processing needed. |
| FAILED        | Processor exited non-zero or exception; terminal. Retry of FAILED is not part of resume. |
| SKIPPED       | Not processed (e.g. policy, duplicate). Not used for lock. |
| DEGRADED      | Run completed with placeholders only (provider offline path). Every file processed in that run gets DEGRADED. |
| TIMED_OUT     | Subprocess did not finish within timeout. Retry on resume. |
| LOCKED        | Lock detected via a **reliable lock check** before running the processor; processing not attempted. Retry on resume. |

**Lock classification (deterministic):**

- Use **LOCKED** only when a reliable lock check (e.g. presence of `.lock` file or lock API) detects a lock **before** invoking the processor.
- If the subprocess exits non-zero and stderr suggests "File locked" but we did **not** perform a reliable pre-check, classify as **FAILED** and record the message.

No lowercase status names and no "succeeded" terminology anywhere.

---

## 2. DONE vs retryable

**DONE** = no further processing needed on restart. The runner will not re-run this file when resuming.

- **DONE set:** COMPLETE, DEGRADED, FAILED, SKIPPED.
- **Retryable (NOT DONE):** TIMED_OUT, LOCKED, PENDING, PROCESSING (PROCESSING is reset to PENDING on load).

---

## 3. File fingerprint on resume

**Rule:** On resume, if `file_fingerprint` differs from the stored value for an item: **do not skip; set status to PENDING and log "input changed".**

The file is then treated as retryable and processed again.

---

## 4. Provider offline abort (exit 2)

**Rule:** If provider preflight aborts (exit 2): **must not create or modify the manifest.**

No file records are written. On a later run, preflight runs again; if still offline and abort, exit 2 again without touching any manifest.

---

## 5. Metadata required for stable restart

**Per-file (in queue item / result):**

- `input_path` (path)
- `output_path` (default: same as input for in-place)
- `file_fingerprint` (required; e.g. mtime+size or content hash)
- `status` (one of the canonical statuses above)
- `exit_code` (when subprocess used: 0, 1, 2)
- `error_summary` (short string for FAILED / TIMED_OUT / LOCKED)
- `provider_offline` (bool)
- `placeholders_applied` (bool or count when applicable)
- `started_at`, `completed_at` (timestamps)

**Batch-level:**

- `batch_id`, `criteria_version` (e.g. "1.0"), `config_path`, `timeout_seconds`, discover target, `start_time`, `end_time`.

---

## 6. Mapping table (canonical)

| Observed run outcome | Batch status | DONE? | Retry on resume? |
| -------------------- | ------------ | ----- | ----------------- |
| Subprocess exit 0 | COMPLETE | Yes | No |
| Subprocess exit non-zero | FAILED | Yes | No |
| Subprocess TimeoutExpired | TIMED_OUT | No | Yes |
| Exception in batch runner | FAILED | Yes | No |
| Provider offline + placeholder path, any file processed | DEGRADED | Yes | No |
| Provider offline + placeholder path, file failure | FAILED | Yes | No |
| File skipped (policy / duplicate) | SKIPPED | Yes | No |
| Use LOCKED only when lock detected via reliable lock check before run; otherwise FAILED (record message). | LOCKED if pre-check; FAILED if not | No / Yes | Yes / No |
| Item was PROCESSING when batch stopped | Reset to PENDING on load | No | Yes |
| Output file created but incomplete (processor exited 0) | COMPLETE (exit 0 ⇒ COMPLETE; no integrity validation in scope) | Yes | No |

---

## 7. Future work

- Output integrity: exit 0 ⇒ COMPLETE is definitive; no output integrity validation in scope. A future change could add checks and demote to FAILED when output is invalid.
