# Batch Processing Remediation Plan

**Plan Date**: 2026-01-26  
**Based On**: `docs/batch-processing-audit.md`  
**Status**: Planning Phase (No Implementation)

## Overview

This plan addresses 12 open items identified in the batch processing audit. Items are prioritized by risk reduction and grouped into logical implementation phases.

---

## Phase 1: Critical Data Loss Prevention (Priority: CRITICAL)

### Item 5.1: Implement Resume Capability

**Goal**: Enable batch processing to resume from interruption without losing progress.

**Non-goals**:
- Parallel processing (keep sequential for Phase 2B.1)
- Real-time progress monitoring dashboard
- Multi-machine batch coordination

**Proposed Approach**:
1. Integrate existing `BatchManifest` system (`shared/batch_manifest.py`, `shared/batch_queue.py`) into `core/batch_processor.py`
2. Modify `process_batch()` to:
   - Create or load manifest at start
   - Track each file in manifest queue
   - Save manifest after each file completion/failure
   - Skip "complete" items on resume
3. Add CLI flags to `altgen.py`:
   - `--resume` - Resume from most recent manifest
   - `--batch-id ID` - Resume from specific batch ID
   - `--output-dir DIR` - Specify output directory for manifest (default: input directory or `./batch_output`)
4. Manifest location: `{output_dir}/batch_{batch_id}_manifest.json`

**Acceptance Criteria**:
1. Start batch with 20 files, process 10, Ctrl+C
2. Rerun with `--resume --batch-id <id>`
3. Files 1-10 skipped (status "complete"), files 11-20 processed
4. Manifest file exists and is updated after each file
5. Items stuck in "processing" reset to "pending" on resume (crash recovery)

**Effort Estimate**: Large (L) - 3-5 days
- Integration work: 2 days
- Testing and edge cases: 1-2 days
- Documentation: 0.5 day

**Dependencies/Risks**:
- Dependencies: None (manifest system already exists)
- Risks: 
  - Manifest file corruption (mitigate with atomic writes - already implemented)
  - Concurrent batch runs on same manifest (mitigate with file locking)
  - Manifest cleanup (add retention policy - config exists)

**Specific Focus Areas**:
- Manifest creation in `PPTXBatchProcessor.__init__()` or `process_batch()`
- Queue integration in processing loop
- Resume detection and manifest loading
- Atomic manifest saves after each file
- Error handling for manifest I/O failures

---

### Item 5.5: Add Graceful Shutdown

**Goal**: Handle SIGINT/SIGTERM gracefully by saving progress and cleaning up resources.

**Non-goals**:
- Pause/resume functionality (separate feature)
- Background processing mode
- Multi-process signal coordination

**Proposed Approach**:
1. Add signal handlers in `core/batch_processor.py`:
   - Register handlers for SIGINT (Ctrl+C) and SIGTERM
   - Set flag `_shutdown_requested` when signal received
   - In processing loop, check flag after each file
2. Graceful shutdown sequence:
   - Save manifest (if using manifest system)
   - Wait for current subprocess to finish or timeout (max 30s)
   - Log shutdown reason and progress
   - Exit with non-zero code
3. If subprocess is running:
   - Send SIGTERM to subprocess (allow cleanup)
   - Wait up to 10 seconds
   - If still running, send SIGKILL
   - Log subprocess termination

**Acceptance Criteria**:
1. Start batch, process 5 files, Ctrl+C
2. Verify manifest saved with files 1-5 marked "complete"
3. Verify current subprocess allowed to finish or terminated cleanly
4. Verify no stale lock files remain
5. Verify batch can be resumed from saved manifest
6. Verify shutdown message logged with progress summary

**Effort Estimate**: Medium (M) - 1-2 days
- Signal handler implementation: 0.5 day
- Subprocess termination logic: 0.5 day
- Testing: 0.5 day
- Edge case handling: 0.5 day

**Dependencies/Risks**:
- Dependencies: Item 5.1 (resume capability) - graceful shutdown needs manifest to save progress
- Risks:
  - Subprocess may not respond to SIGTERM (mitigate with timeout + SIGKILL)
  - Signal handler re-entrancy (mitigate with flag-based approach)
  - Windows signal handling differences (test on Windows if needed)

**Specific Focus Areas**:
- Signal handler registration in `process_batch()`
- Flag-based shutdown detection (avoid re-entrancy)
- Subprocess termination with timeout
- Manifest save on shutdown (if manifest system integrated)
- Cleanup of locks and artifacts (coordinate with subprocess)

---

## Phase 2: Operational Efficiency (Priority: HIGH)

### Item 5.3: Add Idempotency Checking

**Goal**: Skip files that are already processed or have comprehensive ALT text.

**Non-goals**:
- Deep content analysis (keep simple checks)
- Automatic ALT text quality assessment
- Cross-batch deduplication

**Proposed Approach**:
1. Add `--skip-existing` flag to `altgen.py batch` command
2. Implementation options:
   - **Option A (Manifest-based)**: Check manifest for files marked "complete", skip if found
   - **Option B (ALT text scan)**: Pre-scan each file for ALT text presence, skip if all images have meaningful ALT text
   - **Option C (Hybrid)**: Check manifest first, if no manifest, scan ALT text
3. Recommend Option A (manifest-based) for consistency with resume system
4. Add `--force` flag to override skip behavior

**Acceptance Criteria**:
1. Process batch with 10 files, all succeed
2. Rerun same batch with `--skip-existing`
3. All 10 files skipped (no processing)
4. Rerun with `--force`, all files processed again
5. Process batch with mix of processed/unprocessed files
6. Verify only unprocessed files are processed

**Effort Estimate**: Medium (M) - 1-2 days
- Manifest integration: 0.5 day (if Option A)
- ALT text scanning: 1 day (if Option B)
- Testing: 0.5 day

**Dependencies/Risks**:
- Dependencies: Item 5.1 (resume capability) - if using manifest-based approach
- Risks:
  - ALT text scanning adds overhead (mitigate by making it optional/async)
  - False positives (skip files that need processing) - mitigate with conservative heuristics
  - File modification time changes (manifest tracks by path, not mtime)

**Specific Focus Areas**:
- Skip logic in `process_batch()` loop
- Manifest checking for "complete" status
- ALT text scanning implementation (if Option B)
- Flag handling in CLI
- Performance impact of pre-scanning

---

### Item 5.9: Add Error Threshold Stop

**Goal**: Abort batch early if failure rate exceeds threshold.

**Non-goals**:
- Per-file retry logic (separate feature)
- Dynamic threshold adjustment
- Failure pattern analysis

**Proposed Approach**:
1. Use existing config: `batch_processing.stop_on_error_threshold: 0.5` (50%)
2. After each file (or every N files for performance), calculate failure rate
3. If `failed / total > threshold`, abort batch with error message
4. Add `--stop-on-error-threshold FLOAT` flag to override config (0 = disabled)
5. Save manifest before aborting (if manifest system integrated)

**Acceptance Criteria**:
1. Process batch with threshold 0.5, first 6 files fail
2. Verify batch aborts after file 6 (failure rate = 100% > 50%)
3. Verify manifest saved with files 1-6 marked "failed"
4. Verify error message indicates threshold exceeded
5. Test with threshold 0.0 (disabled), verify processes all files
6. Test with threshold 1.0 (never abort), verify processes all files

**Effort Estimate**: Small (S) - 0.5-1 day
- Threshold checking logic: 0.25 day
- Flag handling: 0.25 day
- Testing: 0.25 day

**Dependencies/Risks**:
- Dependencies: Item 5.1 (resume capability) - for manifest save on abort
- Risks:
  - False positives (abort on temporary failures) - mitigate by making threshold configurable
  - Performance impact of frequent checks - mitigate by checking every N files (configurable)

**Specific Focus Areas**:
- Failure rate calculation in processing loop
- Threshold check after each file (or configurable interval)
- Abort logic with manifest save
- CLI flag for threshold override
- Error message clarity

---

## Phase 3: Code Quality and Observability (Priority: MEDIUM)

### Item 1.3: Add Batch Logging Boundaries

**Goal**: Add clear batch start/end markers and batch ID to logs.

**Non-goals**:
- Structured logging format (JSON) - keep text format
- Log aggregation system integration
- Real-time log streaming

**Proposed Approach**:
1. Generate batch ID at start: `batch_{timestamp}_{short_uuid}`
2. Add batch start marker: `logger.info("=== BATCH START: {batch_id} ===")`
3. Add batch end marker: `logger.info("=== BATCH END: {batch_id} ===")`
4. Include batch ID in all batch-related log messages
5. Add summary logging: total files, succeeded, failed, duration

**Acceptance Criteria**:
1. Run batch, check log file
2. Verify batch start marker with batch ID
3. Verify batch end marker with batch ID
4. Verify all batch-related messages include batch ID
5. Verify summary logged at end
6. Verify batch ID matches manifest batch ID (if manifest integrated)

**Effort Estimate**: Small (S) - 0.5 day
- Batch ID generation: 0.1 day
- Logging markers: 0.2 day
- Testing: 0.2 day

**Dependencies/Risks**:
- Dependencies: None
- Risks: None (low-risk change)

**Specific Focus Areas**:
- Batch ID generation in `process_batch()`
- Logger usage (replace `print()` calls)
- Log message formatting
- Summary logging

---

### Item 2.1: Standardize Logging Mechanisms

**Goal**: Replace `print()` calls with logger calls for consistent logging.

**Non-goals**:
- Remove all `print()` calls (keep user-facing progress if needed)
- Change log format
- Add log rotation (already handled by logging config)

**Proposed Approach**:
1. Replace `print()` in `core/batch_processor.py:95` with `logger.info()`
2. Replace `print()` in `altgen.py:372-380` with `logger.info()` for summary
3. Keep `print()` for user-facing progress if `--verbose` flag (optional)
4. Ensure logger is configured (use root logger or configure in batch processor)

**Acceptance Criteria**:
1. Run batch, verify progress messages in log file (not just stdout)
2. Verify summary in log file
3. Verify no mixed print/logger usage in batch code
4. Verify log level filtering works (INFO vs DEBUG)

**Effort Estimate**: Small (S) - 0.5 day
- Replace print calls: 0.2 day
- Logger configuration: 0.2 day
- Testing: 0.1 day

**Dependencies/Risks**:
- Dependencies: Item 1.3 (batch logging boundaries) - can be done together
- Risks: None (low-risk change)

**Specific Focus Areas**:
- Print to logger conversion
- Logger configuration in batch processor
- User-facing vs log file output (consider --verbose flag)

---

### Item 5.2: Limit Memory Accumulation

**Goal**: Write errors to disk instead of accumulating in memory.

**Non-goals**:
- Error aggregation system
- Error reporting dashboard
- Error retry logic

**Proposed Approach**:
1. Option A: Use manifest system (errors persisted in manifest)
2. Option B: Write errors to log file, keep minimal error list in memory
3. Recommend Option A (if manifest integrated) or Option B (simpler)
4. Keep error summary in memory (counts only), write details to disk

**Acceptance Criteria**:
1. Process batch with 100 files, 50 failures
2. Verify memory usage doesn't grow linearly with failures
3. Verify error details accessible (in manifest or log file)
4. Verify error summary still accurate (counts)
5. Verify errors can be retrieved after batch completion

**Effort Estimate**: Small (S) - 0.5-1 day
- Manifest integration: 0.5 day (if Option A)
- Log file writing: 0.5 day (if Option B)
- Testing: 0.25 day

**Dependencies/Risks**:
- Dependencies: Item 5.1 (resume capability) - if using manifest approach
- Risks: None (low-risk change)

**Specific Focus Areas**:
- Error storage strategy (manifest vs log file)
- Memory usage optimization
- Error retrieval after batch completion

---

## Phase 4: Polish and Edge Cases (Priority: LOW)

### Item 2.3: Fix Artifact Session ID Collision Risk

**Goal**: Prevent artifact directory collision for files with same stem processed in same second.

**Non-goals**:
- Global artifact directory coordination
- Artifact deduplication
- Cross-batch artifact sharing

**Proposed Approach**:
1. Add microsecond precision to session ID: `f"{pptx_path.stem}_{int(time.time() * 1000000)}"`
2. Or add random suffix: `f"{pptx_path.stem}_{int(time.time())}_{random.randint(1000, 9999)}"`
3. Recommend microsecond precision (simpler, deterministic)

**Acceptance Criteria**:
1. Process two files with same stem in rapid succession (<1s apart)
2. Verify no collision (different artifact directories)
3. Verify artifact directories are unique
4. Verify cleanup works correctly

**Effort Estimate**: Small (S) - 0.25 day
- Session ID modification: 0.1 day
- Testing: 0.15 day

**Dependencies/Risks**:
- Dependencies: None
- Risks: None (low-risk change)

**Specific Focus Areas**:
- Session ID generation in `shared/pipeline_artifacts.py:150`
- Collision probability analysis
- Testing with rapid file processing

---

### Item 2.4: Enhance Summary Statistics

**Goal**: Add per-file timing and richer error context to summary.

**Non-goals**:
- Performance profiling system
- Detailed timing breakdown per phase
- Statistical analysis

**Proposed Approach**:
1. Add timing per file: start time, end time, duration
2. Store in results dict or manifest
3. Include in summary output: per-file timing, total duration, average time per file
4. Add error context: timestamp, return code, file index

**Acceptance Criteria**:
1. Run batch, check summary
2. Verify per-file timing included
3. Verify total duration and average time calculated
4. Verify error context includes timestamp, return code, index
5. Verify timing accuracy

**Effort Estimate**: Small (S) - 0.5 day
- Timing tracking: 0.25 day
- Summary formatting: 0.25 day

**Dependencies/Risks**:
- Dependencies: None
- Risks: None (low-risk change)

**Specific Focus Areas**:
- Timing capture in processing loop
- Summary formatting
- Error context enhancement

---

### Item 3.1: Enhance Progress Reporting

**Goal**: Add elapsed time, ETA, and success rate to progress messages.

**Non-goals**:
- Real-time progress bar
- Progress persistence
- Multi-file progress tracking

**Proposed Approach**:
1. Track start time at batch start
2. Calculate elapsed time, rate (files/sec), ETA after each file
3. Include in progress message: `Processing 10/100: file.pptx (elapsed: 120s, ETA: 1080s, success: 9, failed: 1)`
4. Update every file (or configurable interval)

**Acceptance Criteria**:
1. Run batch, observe progress messages
2. Verify elapsed time displayed
3. Verify ETA calculated and displayed
4. Verify success/failure counts displayed
5. Verify ETA accuracy improves as batch progresses

**Effort Estimate**: Small (S) - 0.5 day
- Timing calculations: 0.25 day
- Progress message formatting: 0.25 day

**Dependencies/Risks**:
- Dependencies: None
- Risks: None (low-risk change)

**Specific Focus Areas**:
- Timing calculations
- ETA estimation algorithm
- Progress message formatting

---

### Item 3.2: Enhance Error Message Formatting

**Goal**: Include timestamp, return code, and full context in error dict.

**Non-goals**:
- Error classification system
- Error pattern detection
- Automatic error recovery

**Proposed Approach**:
1. Add fields to error dict: `timestamp`, `index`, `return_code`, `stdout`, `stderr`
2. Include in `results["errors"]` list
3. Format in summary output with full context

**Acceptance Criteria**:
1. Process batch with failures
2. Check error list in results
3. Verify timestamp, index, return code included
4. Verify stdout/stderr included (if available)
5. Verify summary output shows full context

**Effort Estimate**: Small (S) - 0.25 day
- Error dict enhancement: 0.15 day
- Summary formatting: 0.1 day

**Dependencies/Risks**:
- Dependencies: None
- Risks: None (low-risk change)

**Specific Focus Areas**:
- Error dict structure
- Context capture
- Summary formatting

---

### Item 3.3: Configure Logger

**Goal**: Explicitly configure logger for batch processing.

**Non-goals**:
- Custom log format
- Log rotation changes
- Multi-handler setup

**Proposed Approach**:
1. Configure logger in `PPTXBatchProcessor.__init__()` or `process_batch()`
2. Set level from config: `batch_processing.log_level` (default: INFO)
3. Use existing formatter or document inheritance from root logger
4. Document logger configuration

**Acceptance Criteria**:
1. Run batch, check logger configuration
2. Verify logger level matches config
3. Verify log messages appear correctly
4. Verify documentation explains logger setup

**Effort Estimate**: Small (S) - 0.25 day
- Logger configuration: 0.15 day
- Documentation: 0.1 day

**Dependencies/Risks**:
- Dependencies: None
- Risks: None (low-risk change)

**Specific Focus Areas**:
- Logger configuration in batch processor
- Config integration
- Documentation

---

### Item 5.7: Add Already-Processed Detection

**Goal**: Skip files that already have comprehensive ALT text.

**Non-goals**:
- ALT text quality assessment
- Partial ALT text detection
- Cross-file deduplication

**Proposed Approach**:
1. Pre-scan each file for ALT text presence
2. Skip if all images have meaningful ALT text (not placeholders)
3. Use `shared/alt_text_reader.py` or similar for scanning
4. Add `--skip-existing-alt` flag (separate from `--skip-existing` which uses manifest)

**Acceptance Criteria**:
1. Process batch with mix of files (some with ALT text, some without)
2. Run with `--skip-existing-alt`
3. Verify files with comprehensive ALT text skipped
4. Verify files without ALT text processed
5. Verify performance impact acceptable (pre-scan overhead)

**Effort Estimate**: Medium (M) - 1-2 days
- ALT text scanning: 1 day
- Skip logic: 0.5 day
- Testing: 0.5 day

**Dependencies/Risks**:
- Dependencies: None (can use existing ALT text reading utilities)
- Risks:
  - Pre-scan overhead (mitigate by making it optional/async)
  - False positives (skip files that need processing) - use conservative heuristics

**Specific Focus Areas**:
- ALT text scanning implementation
- Meaningful ALT text detection (vs placeholders)
- Performance optimization
- Flag handling

---

### Item 5.8: Add Batch-Level Artifact Cleanup

**Goal**: Coordinate artifact cleanup at batch level, monitor disk usage.

**Non-goals**:
- Automatic artifact deduplication
- Artifact compression
- Artifact archival system

**Proposed Approach**:
1. Track artifact directories created during batch
2. After batch completion, verify cleanup (if enabled)
3. Warn if total artifact disk usage exceeds threshold (`config.yaml:222` - `warn_threshold_gb: 5.0`)
4. Add batch-level cleanup command or flag

**Acceptance Criteria**:
1. Process batch with cleanup enabled
2. Verify artifacts cleaned up after batch
3. Process batch with cleanup disabled
4. Verify warning if disk usage exceeds threshold
5. Verify batch-level cleanup works

**Effort Estimate**: Small (S) - 0.5-1 day
- Artifact tracking: 0.25 day
- Cleanup coordination: 0.25 day
- Disk usage monitoring: 0.25 day

**Dependencies/Risks**:
- Dependencies: None
- Risks: None (low-risk change)

**Specific Focus Areas**:
- Artifact directory tracking
- Cleanup coordination
- Disk usage calculation
- Warning threshold

---

## Implementation Order Recommendation

### Sprint 1 (Critical - Week 1)
1. Item 5.1: Resume Capability (L) - 3-5 days
2. Item 5.5: Graceful Shutdown (M) - 1-2 days (depends on 5.1)

### Sprint 2 (High Priority - Week 2)
3. Item 5.3: Idempotency Checking (M) - 1-2 days (depends on 5.1)
4. Item 5.9: Error Threshold Stop (S) - 0.5-1 day (depends on 5.1)

### Sprint 3 (Medium Priority - Week 3)
5. Item 1.3: Batch Logging Boundaries (S) - 0.5 day
6. Item 2.1: Standardize Logging (S) - 0.5 day (can combine with 1.3)
7. Item 5.2: Limit Memory Accumulation (S) - 0.5-1 day (depends on 5.1)

### Sprint 4 (Low Priority - Week 4)
8. Item 2.3: Fix Session ID Collision (S) - 0.25 day
9. Item 2.4: Enhance Summary Statistics (S) - 0.5 day
10. Item 3.1: Enhance Progress Reporting (S) - 0.5 day
11. Item 3.2: Enhance Error Formatting (S) - 0.25 day
12. Item 3.3: Configure Logger (S) - 0.25 day
13. Item 5.7: Already-Processed Detection (M) - 1-2 days
14. Item 5.8: Batch-Level Artifact Cleanup (S) - 0.5-1 day

**Total Estimated Effort**: 12-20 days (2.5-4 weeks)

---

## Testing Strategy

### Unit Tests
- Manifest creation and loading
- Queue operations (add, mark complete, mark failed)
- Resume logic (skip completed, reset processing)
- Signal handler behavior
- Idempotency checks

### Integration Tests
- End-to-end batch processing with resume
- Graceful shutdown scenarios
- Error threshold abort
- Mixed processed/unprocessed files
- Artifact cleanup coordination

### Manual Tests
- 100+ file batch with interruption/resume
- Corrupted file handling (timeout)
- Mixed quality files (valid/corrupted/already-processed)
- Memory usage monitoring
- Disk usage monitoring

---

## Success Metrics

- **Resume Capability**: 100% of interrupted batches can resume without data loss
- **Graceful Shutdown**: 100% of Ctrl+C interrupts save progress and clean up
- **Idempotency**: 0% unnecessary reprocessing of completed files
- **Error Capture**: 100% of subprocess errors captured (stdout + stderr)
- **Logging Quality**: 100% of batch operations logged with batch ID and boundaries

---

**Plan Complete** - Ready for implementation after approval.
