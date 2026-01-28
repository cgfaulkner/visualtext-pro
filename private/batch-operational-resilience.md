# Phase 3C: Batch Operational Resilience

**Status**: Planning Phase  
**Date**: 2026-01-26  
**Scope**: Operational guarantees for batch processing

## Overview

Phase 3C defines the operational guarantees for batch processing, ensuring reliable resume capability, graceful shutdown, and idempotent operations. This phase focuses on **resilience** and **data integrity** without changing selector behavior, adding AI features, or introducing concurrency.

---

## Resume Semantics

### What Constitutes a Completed File?

A file is considered **completed** when:

1. **Status in manifest is `"complete"`**
   - The file's `QueueItem` has `status == QueueStatus.COMPLETE`
   - The `completed_at` timestamp is set
   - The `result` field contains processing metadata (if available)

2. **Output file exists and is valid** (optional verification)
   - If output path is specified, the output file must exist
   - Output file must be readable (not corrupted)
   - Note: This is a **best-effort check** - manifest status is authoritative

3. **No processing errors recorded**
   - `error` field is `None` or absent
   - `skip_reason` field is `None` or absent

**Authoritative Source**: The batch manifest (`batch_{batch_id}_manifest.json`) is the **single source of truth** for completion status. File system checks are secondary validation only.

### What is Skipped on Resume?

On resume, the following items are **automatically skipped**:

1. **Items with status `"complete"`**
   - Files that were successfully processed in a previous run
   - These are skipped without re-processing

2. **Items with status `"skipped"`** (by default)
   - Files that were intentionally skipped (e.g., locked files, invalid paths)
   - These are skipped unless `--force-reprocess` is used

3. **Items with status `"failed"`** (by default)
   - Files that failed processing in a previous run
   - These are skipped unless `--force-reprocess` is used
   - Rationale: Failed files may require manual intervention

**Exception**: Items with status `"processing"` are **reset to `"pending"`** on resume (crash recovery). These will be re-processed.

### What Requires Explicit `--force-reprocess`?

The following require `--force-reprocess` to override skip behavior:

1. **Re-processing completed files**
   - Files with status `"complete"` are skipped unless `--force-reprocess` is specified
   - Use case: Re-run batch after code changes or configuration updates

2. **Re-processing skipped files**
   - Files with status `"skipped"` are skipped unless `--force-reprocess` is specified
   - Use case: Retry files that were skipped due to transient issues (e.g., locks)

3. **Re-processing failed files**
   - Files with status `"failed"` are skipped unless `--force-reprocess` is specified
   - Use case: Retry after fixing underlying issues

**Note**: `--force-reprocess` does **not** clear the manifest history. It only affects the current run's skip logic. Historical status remains in the manifest for audit purposes.

---

## Shutdown Semantics

### What Happens on SIGINT / SIGTERM?

When the batch processor receives SIGINT (Ctrl+C) or SIGTERM:

1. **Signal handler is registered** at batch start
   - Handler sets a `_shutdown_requested` flag (thread-safe)
   - Handler does **not** immediately exit (allows graceful shutdown)

2. **Shutdown detection in processing loop**
   - After each file completes, check `_shutdown_requested` flag
   - If set, initiate graceful shutdown sequence

3. **Graceful shutdown sequence**:
   - Save batch manifest (atomic write)
   - Mark current file status appropriately:
     - If file completed successfully → mark `"complete"`
     - If file failed → mark `"failed"` with error
     - If file was in progress → mark `"processing"` (will be reset on resume)
   - Log shutdown reason and progress summary
   - Exit with non-zero return code (indicates incomplete batch)

### Is the Current File Allowed to Finish?

**Yes, with timeout protection:**

1. **If no file is currently processing**:
   - Shutdown proceeds immediately
   - Manifest is saved and process exits

2. **If a file is currently processing**:
   - Wait for current subprocess to complete, **up to a maximum timeout** (default: 30 seconds)
   - If subprocess completes within timeout:
     - Mark file as `"complete"` or `"failed"` based on result
     - Save manifest and exit
   - If subprocess does not complete within timeout:
     - Send SIGTERM to subprocess (allows cleanup)
     - Wait up to 10 seconds for graceful termination
     - If still running, send SIGKILL (force termination)
     - Mark file as `"processing"` (will be reset to `"pending"` on resume)
     - Save manifest and exit

**Rationale**: Allowing the current file to finish prevents partial writes and file corruption, but timeout prevents indefinite hangs.

### What State Must be Flushed to Disk?

The following state **must** be flushed to disk before shutdown:

1. **Batch manifest** (`batch_{batch_id}_manifest.json`)
   - All queue item statuses (complete, failed, skipped, processing)
   - Batch metadata (start_time, end_time if applicable)
   - Queue statistics
   - **Write method**: Atomic write (write to `.tmp` file, then `replace()`)

2. **Current file's status** (if processing)
   - Status update for the file being processed when shutdown occurred
   - Error message (if file failed)
   - Result metadata (if file completed)

**Not required to flush**:
- Per-file artifact directories (these are managed by the subprocess)
- Log files (handled by logging system buffering)
- Temporary files (cleaned up by subprocess or on next run)

**Flush timing**: Manifest is saved **after each file completes** and **immediately before shutdown**. This ensures minimal data loss.

---

## Idempotency Rules

### What Conditions Allow Early Skip?

A file can be **skipped early** (before processing) if:

1. **Manifest-based skip** (if `--skip-existing` is used):
   - File path exists in manifest with status `"complete"`
   - No `--force-reprocess` flag is set
   - **Authoritative**: Manifest status is checked first

2. **ALT text presence check** (if `--skip-existing-alt` is used):
   - File is scanned for ALT text presence
   - All images have meaningful ALT text (not placeholders like "image.png", "picture", etc.)
   - No `--force-reprocess` flag is set
   - **Note**: This is a **heuristic** - not as reliable as manifest-based skip

3. **File locking skip**:
   - File is locked by another process
   - Lock acquisition times out (configurable, default: 30 seconds)
   - File is marked as `"skipped"` with reason: `"File locked by another process"`

4. **Path validation skip**:
   - File path fails security validation
   - File does not exist or is not readable
   - File is marked as `"skipped"` with reason describing the validation failure

**Early skip does not require subprocess execution** - these checks happen before spawning the processing subprocess.

### What Artifacts are Authoritative?

The following artifacts are **authoritative** for determining file state:

1. **Batch manifest** (`batch_{batch_id}_manifest.json`)
   - **Primary authority** for batch-level state
   - Tracks completion status, errors, skip reasons
   - Used for resume capability
   - Location: `{output_dir}/batch_{batch_id}_manifest.json`

2. **Per-file output file** (if output path is specified)
   - **Secondary authority** for file-level completion
   - Existence indicates file was processed
   - Used for validation, not primary decision-making
   - Location: Specified by user or auto-generated

3. **Per-file artifact directories** (`.alt_pipeline_{session_id}/`)
   - **Not authoritative** for batch state
   - Used for debugging and recovery
   - May be cleaned up after processing
   - Location: `{file.parent}/.alt_pipeline_{session_id}/`

**Decision hierarchy**:
1. Check batch manifest first (if available)
2. If manifest missing or file not in manifest, check output file existence
3. If neither available, file is considered unprocessed

---

## Manifest Guarantees

### What Must Always be Written?

The batch manifest **must always** contain:

1. **Manifest metadata**:
   - `version`: Manifest schema version (currently `"1.0"`)
   - `batch_id`: Unique batch identifier
   - `output_dir`: Output directory path
   - `input_root`: Input root directory (if specified)
   - `start_time`: Batch start timestamp (ISO format)
   - `end_time`: Batch end timestamp (ISO format, `null` if incomplete)
   - `metadata`: Additional metadata dictionary

2. **Queue state**:
   - `queue.items[]`: Array of queue items, each containing:
     - `path`: File path (string)
     - `status`: Status (`"pending"`, `"processing"`, `"complete"`, `"failed"`, `"skipped"`)
     - `added_at`: Timestamp when added to queue
     - `started_at`: Timestamp when processing started (`null` if not started)
     - `completed_at`: Timestamp when processing completed (`null` if not completed)
     - `error`: Error message (`null` if no error)
     - `skip_reason`: Skip reason (`null` if not skipped)
     - `result`: Processing result metadata (`null` if not available)

3. **Write guarantees**:
   - Manifest is written **atomically** (write to `.tmp`, then `replace()`)
   - Manifest is saved **after each file completes** (success or failure)
   - Manifest is saved **before shutdown** (graceful or forced)
   - Manifest is saved **on batch start** (initial state)

### What May be Missing After a Crash?

After a crash, the following may be missing or inconsistent:

1. **Current file's status**:
   - If crash occurs during file processing, the file may be marked as `"processing"` instead of `"complete"` or `"failed"`
   - **Recovery**: On resume, items with status `"processing"` are reset to `"pending"` and re-processed

2. **End timestamp**:
   - `end_time` may be `null` if batch did not complete normally
   - **Recovery**: Resume will continue processing, and `end_time` will be set when batch completes

3. **Partial queue updates**:
   - If crash occurs during manifest write, the manifest may be in an inconsistent state
   - **Recovery**: Atomic writes prevent partial writes (`.tmp` file is not renamed if write fails)
   - If `.tmp` file exists, it indicates a failed write (should be cleaned up or ignored)

4. **Per-file artifacts**:
   - Artifact directories for the file being processed at crash time may be incomplete
   - **Recovery**: Artifacts are recreated on re-processing (idempotent)

5. **Log entries**:
   - Log entries for the current file may be missing if crash occurs during logging
   - **Recovery**: Logs are best-effort; manifest is authoritative for state

**Crash recovery strategy**:
- On resume, load manifest
- Reset all `"processing"` items to `"pending"`
- Continue processing from first `"pending"` item
- This ensures no work is lost, but may re-process the file that was in progress during crash

---

## Non-Goals

Phase 3C explicitly **does not** handle the following:

### Concurrency

- **No parallel processing**: Phase 3C maintains sequential processing (`max_workers=1`)
- **No concurrent batch runs**: Multiple batch processes on the same manifest are not coordinated
- **No distributed processing**: Batch processing is single-machine only
- **Rationale**: Concurrency introduces complexity and requires additional coordination mechanisms (locks, queues, etc.)

### Retries

- **No automatic retries**: Failed files are not automatically retried
- **No exponential backoff**: No retry scheduling or delay mechanisms
- **No retry limits**: Users must manually re-run with `--force-reprocess` to retry failed files
- **Rationale**: Retries require policy decisions (how many retries? what delay? what conditions?) that are out of scope for operational resilience

### AI or Performance Optimizations

- **No AI model changes**: Selector behavior, LLaVA calls, and ALT text generation are unchanged
- **No performance tuning**: No optimizations to processing speed or resource usage
- **No caching improvements**: Existing caching mechanisms are not modified
- **Rationale**: Phase 3C focuses on reliability, not performance or AI capabilities

### Advanced Features

- **No pause/resume**: Cannot pause a batch and resume later (only crash recovery)
- **No progress monitoring API**: No programmatic access to batch progress
- **No webhooks or notifications**: No external system integration
- **No batch scheduling**: No cron-like scheduling or automated batch triggers
- **Rationale**: These features require additional infrastructure and are beyond operational resilience scope

### Data Migration or Schema Changes

- **No manifest schema migrations**: Existing manifests are not upgraded to new schemas
- **No backward compatibility**: Old manifest formats are not supported
- **Rationale**: Phase 3C assumes current manifest schema (`version: "1.0"`)

---

## Implementation Checklist

This checklist can be converted into implementation tickets for Phase 3C.

### Resume Semantics

- [ ] **R-1**: Implement manifest-based completion detection
  - Load manifest on batch start
  - Check `QueueItem.status == "complete"` to determine completed files
  - Skip completed files unless `--force-reprocess` is set

- [ ] **R-2**: Implement skip logic for `"skipped"` and `"failed"` items
  - Skip items with status `"skipped"` by default
  - Skip items with status `"failed"` by default
  - Allow `--force-reprocess` to override skip behavior

- [ ] **R-3**: Implement crash recovery for `"processing"` items
  - On manifest load, reset all `"processing"` items to `"pending"`
  - Log recovery actions for audit purposes

- [ ] **R-4**: Add `--force-reprocess` CLI flag
  - Override skip behavior for completed, skipped, and failed files
  - Document flag usage in help text

### Shutdown Semantics

- [ ] **S-1**: Register signal handlers for SIGINT and SIGTERM
  - Set `_shutdown_requested` flag (thread-safe)
  - Do not immediately exit (allow graceful shutdown)

- [ ] **S-2**: Implement shutdown detection in processing loop
  - Check `_shutdown_requested` flag after each file completes
  - Initiate graceful shutdown sequence if flag is set

- [ ] **S-3**: Implement current file completion with timeout
  - Wait for current subprocess to complete (max 30 seconds)
  - Send SIGTERM if timeout exceeded, then SIGKILL if still running
  - Mark file status appropriately before exit

- [ ] **S-4**: Implement manifest flush on shutdown
  - Save manifest atomically before exit
  - Ensure current file status is recorded
  - Log shutdown reason and progress summary

- [ ] **S-5**: Exit with appropriate return code
  - Return non-zero code on shutdown (indicates incomplete batch)
  - Return zero code on normal completion

### Idempotency Rules

- [ ] **I-1**: Implement manifest-based early skip
  - Check manifest for `"complete"` status before processing
  - Skip if found and `--skip-existing` is set (and no `--force-reprocess`)

- [ ] **I-2**: Implement ALT text presence check (optional)
  - Add `--skip-existing-alt` flag
  - Pre-scan files for meaningful ALT text
  - Skip if all images have ALT text (heuristic)

- [ ] **I-3**: Implement file locking skip
  - Check file lock before processing
  - Skip with reason if lock acquisition times out
  - Mark as `"skipped"` in manifest

- [ ] **I-4**: Implement path validation skip
  - Validate file path before processing
  - Skip with reason if validation fails
  - Mark as `"skipped"` in manifest

### Manifest Guarantees

- [ ] **M-1**: Ensure manifest contains required fields
  - Verify all metadata fields are present
  - Verify queue items have all required fields
  - Add validation on manifest load

- [ ] **M-2**: Implement atomic manifest writes
  - Write to `.tmp` file first
  - Use `replace()` to atomically update manifest
  - Handle write failures gracefully

- [ ] **M-3**: Implement manifest save after each file
  - Save manifest after file completes (success or failure)
  - Save manifest after file is skipped
  - Ensure save happens before processing next file

- [ ] **M-4**: Implement manifest save on batch start
  - Save initial manifest state when batch starts
  - Include all files in queue with `"pending"` status

- [ ] **M-5**: Implement crash recovery for incomplete writes
  - Detect and clean up `.tmp` files on startup
  - Ignore incomplete manifest writes (use previous version)
  - Log recovery actions

### Integration

- [ ] **INT-1**: Integrate `BatchManifest` into `core/batch_processor.py`
  - Replace in-memory results dict with `BatchManifest` system
  - Use `BatchQueue` for queue management
  - Remove duplicate state tracking

- [ ] **INT-2**: Add CLI flags to `altgen.py batch` command
  - `--resume`: Resume from most recent manifest
  - `--batch-id ID`: Resume from specific batch ID
  - `--skip-existing`: Skip files already in manifest as complete
  - `--force-reprocess`: Override skip behavior

- [ ] **INT-3**: Update error handling to use manifest
  - Mark files as `"failed"` in manifest on error
  - Store error messages in `QueueItem.error` field
  - Ensure manifest is saved even on errors

- [ ] **INT-4**: Update progress reporting to use manifest
  - Load statistics from `BatchQueue.get_stats()`
  - Display resume status if resuming
  - Show skipped/failed counts from manifest

### Testing

- [ ] **T-1**: Test resume from completed batch
  - Process batch, verify manifest created
  - Re-run with `--resume`, verify completed files skipped

- [ ] **T-2**: Test resume from interrupted batch
  - Start batch, interrupt with Ctrl+C
  - Verify manifest saved with current state
  - Re-run with `--resume`, verify processing continues

- [ ] **T-3**: Test graceful shutdown
  - Start batch, send SIGTERM
  - Verify current file allowed to finish (or timeout)
  - Verify manifest saved before exit

- [ ] **T-4**: Test crash recovery
  - Simulate crash (kill process)
  - Verify `"processing"` items reset to `"pending"` on resume
  - Verify no data loss

- [ ] **T-5**: Test idempotency
  - Process batch twice with `--skip-existing`
  - Verify second run skips all files
  - Verify `--force-reprocess` overrides skip

- [ ] **T-6**: Test manifest atomicity
  - Simulate write failure during manifest save
  - Verify `.tmp` file handling
  - Verify manifest consistency

### Documentation

- [ ] **D-1**: Update `README.md` with resume instructions
  - Document `--resume` and `--batch-id` flags
  - Document `--skip-existing` and `--force-reprocess` flags
  - Add examples of resume usage

- [ ] **D-2**: Update `docs/batch-processing-remediation-plan.md`
  - Mark Phase 3C items as complete after implementation
  - Update status and verification results

- [ ] **D-3**: Add inline code documentation
  - Document signal handler behavior
  - Document manifest write guarantees
  - Document idempotency rules in code

---

## References

- **Batch Processing Audit**: `docs/batch-processing-audit.md`
- **Batch Processing Remediation Plan**: `docs/batch-processing-remediation-plan.md`
- **Batch Processing Implementation**: `.claude_docs/batch_processing_implementation.md`
- **Batch Queue Implementation**: `shared/batch_queue.py`
- **Batch Manifest Implementation**: `shared/batch_manifest.py`
- **Batch Processor**: `core/batch_processor.py`

---

**End of Document**
