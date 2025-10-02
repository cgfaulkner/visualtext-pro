# RunArtifacts Integration Verification

## Summary

Successfully integrated the RunArtifacts system from Session 2 into pptx_alt_processor.py. The processor now creates `.alt_pipeline_*` directories during processing and automatically cleans them up based on configuration.

## Changes Made

### 1. pptx_alt_processor.py

#### Import Addition
```python
from shared.pipeline_artifacts import RunArtifacts
```

#### Constructor Update
Added `use_artifacts` parameter (default: `True`):
```python
def __init__(self, ..., use_artifacts: bool = True):
    ...
    self.use_artifacts = use_artifacts
    self._current_artifacts = None
```

#### process_single_file() Integration
Wrapped processing logic with RunArtifacts context manager:

```python
# Determine if we should use artifacts
artifact_config = self.config_manager.config.get('artifact_management', {})
cleanup_on_exit = artifact_config.get('auto_cleanup', True)
should_use_artifacts = self.use_artifacts

# Wrap processing with RunArtifacts if enabled
if should_use_artifacts:
    artifacts = RunArtifacts.create_for_run(input_path, cleanup_on_exit=cleanup_on_exit)
    artifacts.__enter__()
    self._current_artifacts = artifacts
else:
    artifacts = None
    self._current_artifacts = None

try:
    # ... existing processing logic ...
finally:
    # Mark success and cleanup artifacts if enabled
    if artifacts is not None:
        if result_obj.success:
            artifacts.mark_success()
        artifacts.__exit__(None, None, None)
        self._current_artifacts = None
```

#### CLI Flag Addition
```python
parser.add_argument('--no-artifacts', action='store_true',
                   help='Disable artifact directory creation')

processor = PPTXAltProcessor(
    ...
    use_artifacts=not args.no_artifacts
)
```

### 2. altgen.py

#### Process Parser Update
```python
process_parser.add_argument('--no-artifacts', action='store_true',
                           help='Disable artifact directory creation')
```

#### Dispatcher Update
```python
# Add artifact management flag if specified
if hasattr(self.args, 'no_artifacts') and self.args.no_artifacts:
    cmd.append("--no-artifacts")
```

### 3. Configuration

config.yaml already has the required `artifact_management` section from Session 2:
```yaml
artifact_management:
  auto_cleanup: true              # Automatically cleanup artifacts after processing
  keep_finals: true               # Keep final_alt_map.json and visual_index.json
  max_age_days: 7                 # Maximum age before auto-cleanup (days)
  cleanup_on_success: true        # Cleanup temporary artifacts on successful processing
  cleanup_on_failure: false       # Keep artifacts on failure for debugging
  warn_threshold_gb: 5.0          # Warn if total artifact disk usage exceeds this (GB)
```

## Usage Examples

### Default Behavior (Artifacts Enabled)
```bash
# Creates .alt_pipeline_<timestamp>_<uuid> directory
# Automatically cleans up after processing (based on config)
python altgen.py process presentation.pptx
```

### Disable Artifacts
```bash
# No artifact directory created
python altgen.py process presentation.pptx --no-artifacts
```

### Direct Processor Usage
```bash
# With artifacts (default)
python3 pptx_alt_processor.py process presentation.pptx

# Without artifacts
python3 pptx_alt_processor.py process presentation.pptx --no-artifacts
```

## Artifact Lifecycle

1. **Creation**: When processing starts, `RunArtifacts.create_for_run()` creates:
   - Directory: `.alt_pipeline_<timestamp>_<uuid>/`
   - Subdirectories: `scans/`, `generated/`, `resolved/`, `finals/`

2. **During Processing**:
   - `self._current_artifacts` is available for saving intermediate files
   - Future enhancement: processors can save visual index, alt mappings, etc.

3. **On Success**:
   - `artifacts.mark_success()` is called
   - If `cleanup_on_success: true`, temporary files are removed
   - If `keep_finals: true`, `finals/` directory is preserved

4. **On Failure**:
   - If `cleanup_on_failure: false`, artifacts are kept for debugging
   - Otherwise, cleanup occurs

5. **Cleanup**:
   - Automatic via `__exit__()` context manager
   - Manual via `python altgen.py cleanup --max-age-days 7`

## Benefits

✅ **Automatic Cleanup**: No manual cleanup needed - artifacts are cleaned up based on config
✅ **Debug Support**: Failed runs preserve artifacts for troubleshooting
✅ **Backward Compatible**: `--no-artifacts` flag maintains old behavior
✅ **Configurable**: All behavior controlled via `config.yaml`
✅ **Integration Ready**: `self._current_artifacts` available for future enhancements

## Future Enhancements

The integration is designed to support saving intermediate files:

```python
# Future: Save visual index to artifacts
if hasattr(self, '_current_artifacts') and self._current_artifacts:
    visual_index_path = self._current_artifacts.scans_dir / "visual_index.json"
    visual_index_path.write_text(json.dumps(visual_index, indent=2))
```

Potential artifacts to save:
- Visual index (scanned shapes/images)
- Generated ALT text mappings
- Resolved ALT text (after conflict resolution)
- Coverage reports
- Debug logs
- Timing statistics

## Testing

### Manual Verification

1. **Test Artifact Creation**:
```bash
# Before processing
ls -la | grep .alt_pipeline_

# Process file
python3 pptx_alt_processor.py process tests/manual_injection_test.pptx

# Check if artifacts were created and cleaned up
ls -la | grep .alt_pipeline_
```

2. **Test --no-artifacts Flag**:
```bash
# Should NOT create artifacts
python3 pptx_alt_processor.py process tests/manual_injection_test.pptx --no-artifacts
ls -la | grep .alt_pipeline_  # Should find nothing new
```

3. **Test via altgen.py**:
```bash
# Should pass flag through to processor
python3 altgen.py process tests/manual_injection_test.pptx --no-artifacts
ls -la | grep .alt_pipeline_  # Should find nothing new
```

### Expected Behavior

**With Artifacts Enabled** (default):
- Creates `.alt_pipeline_*` directory during processing
- Automatically removes directory after processing completes
- Preserves `finals/` if `keep_finals: true` and processing succeeded

**With `--no-artifacts`**:
- No `.alt_pipeline_*` directory created
- Processing works exactly as before
- Backward compatible behavior

## Troubleshooting

### Artifacts Not Cleaned Up
Check `config.yaml`:
```yaml
artifact_management:
  auto_cleanup: true  # Must be true for automatic cleanup
```

### Want to Keep All Artifacts
Disable cleanup temporarily:
```yaml
artifact_management:
  auto_cleanup: false  # Disables automatic cleanup
```

Or keep on failure:
```yaml
artifact_management:
  cleanup_on_failure: false  # Keep artifacts when processing fails
```

### Manually Clean Old Artifacts
```bash
python altgen.py cleanup --max-age-days 7 --report
```

## Integration Status

✅ RunArtifacts imported into pptx_alt_processor.py
✅ use_artifacts parameter added to __init__()
✅ process_single_file() wrapped with artifact context manager
✅ --no-artifacts CLI flag added
✅ altgen.py dispatcher updated to pass flag
✅ config.yaml artifact_management section verified
✅ Automatic cleanup on success/failure based on config
✅ mark_success() called when processing succeeds
✅ Context manager ensures cleanup even on exceptions

## Related Documentation

- Artifact Management: `.claude_docs/artifact_cleanup_implementation.md`
- File Locking: `.claude_docs/file_locking_implementation.md`
- Path Validation: `.claude_docs/path_validation_implementation.md`
