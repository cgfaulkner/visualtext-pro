# Entry Points and Call Flow for PPTX ALT Text Processing

## Main Entry Point Scripts

### 1. `altgen.py` (Unified CLI Dispatcher)
**Entry Function**: `main()` (line 341)

**CLI Commands**:
- `python altgen.py process <file>` → Processes single file or batch
- `python altgen.py analyze <file>` → Generates review document only
- `python altgen.py inject <file>` → Injects ALT text from manifest
- `python altgen.py batch <target>` → Batch processes files
- `python altgen.py cleanup` → Cleans up old artifacts
- `python altgen.py locks` → Shows/manages file locks

**Call Flow**:
```
main()
  ├─> ProcessorDispatcher(args)
  │     └─> select_processor() → Returns processor script name
  │
  ├─> [if command == 'process']
  │     ├─> [if directory/glob] → run_batch()
  │     │     └─> PPTXBatchProcessor.process_batch()
  │     │           └─> _process_single() → subprocess.run('pptx_alt_processor.py process')
  │     │
  │     └─> [if single file] → dispatcher.dispatch_process()
  │           └─> _run_processor() → subprocess.run(processor_script)
  │
  ├─> [if command == 'analyze']
  │     └─> dispatcher.dispatch_analyze()
  │           └─> _run_processor() → subprocess.run(processor_script)
  │
  └─> [if command == 'batch']
        └─> run_batch()
              └─> PPTXBatchProcessor.process_batch()
```

---

### 2. `pptx_alt_processor.py` (Original Full-Featured Processor)
**Entry Function**: `main()` (line 1146)

**CLI Commands**:
- `python pptx_alt_processor.py process <file>` → Full processing pipeline
- `python pptx_alt_processor.py batch-process <dir>` → Batch processing
- `python pptx_alt_processor.py extract <file>` → Extract images only
- `python pptx_alt_processor.py inject <file>` → Inject from JSON mapping

**Call Flow**:
```
main()
  ├─> PPTXAltProcessor(config_path, verbose, debug, ...)
  │
  └─> [if command == 'process']
        └─> processor.process_single_file(input_pptx, output_path, export_pdf)
              ├─> FileLock.acquire() → Lock file
              ├─> RunArtifacts.create_for_run() → Create artifact directories
              └─> PPTXAccessibilityProcessor.process_pptx()
                    ├─> _extract_images_from_pptx()
                    ├─> FlexibleAltGenerator.generate_alt_text() → LLaVA calls
                    └─> PPTXAltTextInjector.inject_alt_text_from_mapping()
```

**Direct Processing Path** (when called directly, not via altgen.py):
```
pptx_alt_processor.py main()
  → PPTXAltProcessor.process_single_file()
    → core/pptx_processor.py PPTXAccessibilityProcessor.process_pptx()
      → shared/unified_alt_generator.py FlexibleAltGenerator.generate_alt_text()
      → core/pptx_alt_injector.py PPTXAltTextInjector.inject_alt_text_from_mapping()
```

---

### 3. `pptx_clean_processor.py` (Three-Phase Pipeline)
**Entry Function**: `main()` (line 139)

**CLI Commands**:
- `python pptx_clean_processor.py process <file>` → Full three-phase pipeline
- `python pptx_clean_processor.py inject <file>` → Inject from final_alt_map.json
- `python pptx_clean_processor.py review` → Generate review document from artifacts

**Call Flow**:
```
main()
  └─> [if command == 'process']
        └─> cmd_process(args)
              ├─> ConfigManager(args.config)
              ├─> FlexibleAltGenerator(config_manager)
              └─> run_pipeline(input_path, config, alt_generator)
                    ├─> Phase 1: phase1_scan()
                    │     └─> ManifestProcessor.phase1_discover_and_classify()
                    ├─> Phase 1.5: phase1_5_render_thumbnails()
                    │     └─> ManifestProcessor.phase2_render_and_generate_crops()
                    ├─> Phase 1.9: phase1_9_run_selector()
                    │     └─> selector.run_selector()
                    ├─> Phase 2: phase2_generate()
                    │     └─> alt_generator.generate_alt_text()
                    ├─> Phase 3: phase3_resolve()
                    │     └─> Merges current + generated ALT text
                    └─> inject_from_map() → PPTXAltTextInjector.inject_alt_text_from_mapping()
```

---

### 4. `pptx_manifest_processor.py` (Manifest-Driven Workflow)
**Entry Function**: `main()` (line 51)

**CLI Commands**:
- `python pptx_manifest_processor.py process <file>` → Manifest-based processing
- `python pptx_manifest_processor.py inject <file>` → Inject from manifest
- `python pptx_manifest_processor.py review` → Generate review from manifest
- `python pptx_manifest_processor.py validate <manifest>` → Validate manifest schema

**Call Flow**:
```
main()
  └─> [if command == 'process']
        └─> cmd_process(args)
              ├─> ConfigManager(args.config)
              ├─> FlexibleAltGenerator(config_manager)
              └─> ManifestProcessor.process()
                    ├─> phase1_discover_and_classify()
                    ├─> phase2_render_and_generate_crops()
                    ├─> _generate_missing_alt_text()
                    │     └─> alt_generator.generate_alt_text()
                    └─> inject_alt_text() → PPTXAltTextInjector.inject_alt_text_from_mapping()
```

---

## Batch Processing Entry Point

### `core/batch_processor.py`
**Class**: `PPTXBatchProcessor`

**Entry Methods**:
- `discover_files(target)` → Finds PPTX files from folder/glob
- `process_batch(files)` → Processes files sequentially

**Call Flow**:
```
PPTXBatchProcessor.process_batch(files)
  └─> For each file:
        └─> _process_single(file_path)
              └─> subprocess.run(['python', 'pptx_alt_processor.py', 'process', file_path])
                    └─> [Calls pptx_alt_processor.py main() as subprocess]
```

**Called From**:
- `altgen.py` → `run_batch()` function (line 346)
- `altgen.py` → `main()` when command is 'batch' (line 499)

---

## Core Processing Functions

### Single File Processing Chain

**Path 1: Via pptx_alt_processor.py**
```
pptx_alt_processor.py::main()
  → PPTXAltProcessor.process_single_file()
    → core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()
      → _extract_images_from_pptx()
      → FlexibleAltGenerator.generate_alt_text()
      → core/pptx_alt_injector.py::PPTXAltTextInjector.inject_alt_text_from_mapping()
```

**Path 2: Via pptx_clean_processor.py**
```
pptx_clean_processor.py::main()
  → cmd_process()
    → shared/pipeline_phases.py::run_pipeline()
      → phase1_scan() → ManifestProcessor.phase1_discover_and_classify()
      → phase1_5_render_thumbnails() → ManifestProcessor.phase2_render_and_generate_crops()
      → phase1_9_run_selector() → selector.run_selector()
      → phase2_generate() → FlexibleAltGenerator.generate_alt_text()
      → phase3_resolve() → Merges ALT text mappings
      → inject_from_map() → PPTXAltTextInjector.inject_alt_text_from_mapping()
```

**Path 3: Via pptx_manifest_processor.py**
```
pptx_manifest_processor.py::main()
  → cmd_process()
    → shared/manifest_processor.py::ManifestProcessor.process()
      → phase1_discover_and_classify()
      → phase2_render_and_generate_crops()
      → _generate_missing_alt_text() → FlexibleAltGenerator.generate_alt_text()
      → inject_alt_text() → PPTXAltTextInjector.inject_alt_text_from_mapping()
```

---

## Key Processing Components

### ALT Text Generation
**Entry Point**: `shared/unified_alt_generator.py::FlexibleAltGenerator.generate_alt_text()`

**Called From**:
- `core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()`
- `shared/pipeline_phases.py::phase2_generate()`
- `shared/manifest_processor.py::ManifestProcessor._generate_missing_alt_text()`

**Call Flow**:
```
FlexibleAltGenerator.generate_alt_text(image_path, ...)
  └─> LLaVAProvider.generate_alt_text()
      └─> _execute_generation_request()
          └─> requests.post(ollama_endpoint) → LLaVA API call
```

### ALT Text Injection
**Entry Point**: `core/pptx_alt_injector.py::PPTXAltTextInjector.inject_alt_text_from_mapping()`

**Called From**:
- `pptx_clean_processor.py::inject_from_map()`
- `pptx_alt_processor.py::PPTXAltProcessor.process_single_file()`
- `shared/manifest_processor.py::ManifestProcessor.inject_alt_text()`

---

## Summary: Entry Point Hierarchy

```
User Command
    │
    ├─> python altgen.py process <file>
    │       └─> [Dispatcher] → subprocess.run(processor_script)
    │
    ├─> python pptx_alt_processor.py process <file>
    │       └─> PPTXAltProcessor.process_single_file()
    │             └─> PPTXAccessibilityProcessor.process_pptx()
    │
    ├─> python pptx_clean_processor.py process <file>
    │       └─> run_pipeline() → Three-phase pipeline
    │
    └─> python pptx_manifest_processor.py process <file>
            └─> ManifestProcessor.process() → Manifest-based workflow
```

**All paths eventually call**:
- `FlexibleAltGenerator.generate_alt_text()` → LLaVA API
- `PPTXAltTextInjector.inject_alt_text_from_mapping()` → Write to PPTX
