#!/usr/bin/env python3
"""
altgen - CLI dispatcher for alt text generation and processing
Unified CLI that dispatches to existing proven processors
"""

import argparse
import sys
import os
import subprocess
from typing import List, Optional


MODES = ["presentation", "scientific", "context", "auto"]
POLICIES = ["preserve", "overwrite_all", "smart"]

# Processor selection mappings
PROCESSOR_MAP = {
    "manifest": "pptx_manifest_processor.py",
    "clean": "pptx_clean_processor.py",
    "original": "pptx_alt_processor.py"
}


class ProcessorDispatcher:
    """Dispatches commands to appropriate existing processors"""

    def __init__(self, args):
        self.args = args
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.warnings_shown = set()  # Track shown warnings

    def _show_warning_once(self, message: str):
        """Show warning only once per session"""
        if message not in self.warnings_shown:
            print(f"Warning: {message}")
            self.warnings_shown.add(message)

    def setup_logging(self):
        """Setup JSONL logging if requested (altgen.py handles this)"""
        if hasattr(self.args, 'log_jsonl') and self.args.log_jsonl:
            # Create the directory and file
            log_dir = os.path.dirname(self.args.log_jsonl)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)

            # Create empty file with header
            with open(self.args.log_jsonl, 'w') as f:
                import json
                from datetime import datetime
                header = {
                    "timestamp": datetime.now().isoformat(),
                    "dispatcher": "altgen.py",
                    "command": getattr(self.args, 'command', 'unknown'),
                    "note": "Log file created by altgen dispatcher"
                }
                f.write(json.dumps(header) + '\n')

            print(f"Logging to: {os.path.abspath(self.args.log_jsonl)}")

    def select_processor(self) -> str:
        """Select which processor to use based on flags and command"""
        # Check for manifest mode flags
        if getattr(self.args, 'use_manifest', False) or getattr(self.args, 'resume', False):
            return PROCESSOR_MAP["manifest"]

        # Check for clean pipeline mode
        if getattr(self.args, 'clean_pipeline', False):
            return PROCESSOR_MAP["clean"]

        # Default to original processor
        return PROCESSOR_MAP["original"]

    def dispatch_analyze(self, file_path: str) -> int:
        """Dispatch analyze command to appropriate processor"""
        # Pass path directly to processor - it will validate
        processor = self.select_processor()

        if processor == PROCESSOR_MAP["clean"]:
            # Use clean processor's review-doc-only mode for analysis
            cmd = ["python", processor, "process", file_path, "--review-doc-only"]
        elif processor == PROCESSOR_MAP["manifest"]:
            # Use manifest processor's review-only mode for analysis
            cmd = ["python", processor, "process", file_path, "--review-only"]
        else:
            # For original processor, use extract command for analysis
            cmd = ["python", processor, "extract", file_path]

        return self._run_processor(cmd)

    def dispatch_process(self, file_path: str) -> int:
        """Dispatch process command to appropriate processor"""
        # Pass path directly to processor - it will validate
        processor = self.select_processor()

        # Build command: python processor.py [global-flags] process file.pptx [subcommand-flags]
        cmd = ["python", processor]

        # Add global flags BEFORE subcommand (original processor expects this)
        if hasattr(self.args, 'alt_policy'):
            if self.args.alt_policy == "preserve":
                cmd.extend(["--mode", "preserve"])
            elif self.args.alt_policy == "overwrite_all":
                cmd.extend(["--mode", "replace"])
            else:  # smart policy defaults to preserve
                cmd.extend(["--mode", "preserve"])

        # Handle --mode scientific mapping (placeholder for future implementation)
        if hasattr(self.args, 'mode') and self.args.mode == 'scientific':
            # Scientific mode could enable detailed processing options
            # For now, just use preserve mode - extend as processors support it
            pass

        # Add subcommand and file
        cmd.extend(["process", file_path])

        # Add subcommand-specific flags AFTER the file
        if self.args.dry_run:
            if processor == PROCESSOR_MAP["manifest"]:
                cmd.append("--review-only")
            elif processor == PROCESSOR_MAP["clean"]:
                cmd.append("--review-doc-only")
            else:
                cmd.append("--dry-run")

        # Add artifact management flag if specified
        if hasattr(self.args, 'no_artifacts') and self.args.no_artifacts:
            cmd.append("--no-artifacts")

        return self._run_processor(cmd)

    def dispatch_inject(self, file_path: str) -> int:
        """Dispatch inject command to appropriate processor"""
        # Pass path directly to processor - it will validate
        processor = self.select_processor()

        if processor == PROCESSOR_MAP["manifest"]:
            cmd = ["python", processor, "inject", file_path]
        elif processor == PROCESSOR_MAP["clean"]:
            cmd = ["python", processor, "inject", file_path]
        else:
            # Original processor uses inject command
            cmd = ["python", processor, "inject", file_path]

        return self._run_processor(cmd)

    def dispatch_review(self, manifest_path: str, output_path: str) -> int:
        """Dispatch review command to manifest processor"""
        # Pass paths directly to processor - it will validate
        cmd = ["python", PROCESSOR_MAP["manifest"], "review",
               "--manifest", manifest_path, "--out", output_path]
        return self._run_processor(cmd)

    def dispatch_audit(self, file_path: str) -> int:
        """Dispatch audit command to manifest processor"""
        # Pass path directly to processor - it will validate
        # Manifest processor validate expects a manifest file, not the PPTX
        # For now, redirect to process with review-only to generate validation data
        cmd = ["python", PROCESSOR_MAP["manifest"], "process", file_path, "--review-only"]
        return self._run_processor(cmd)

    def _run_processor(self, cmd: List[str]) -> int:
        """Run processor command (flags should already be added by dispatch methods)"""

        # Add remaining common global flags before the subcommand
        if len(cmd) >= 3:  # ["python", "processor.py", ...]
            # Find the subcommand position
            subcommand_idx = -1
            known_subcommands = ["process", "extract", "inject", "review", "validate", "analyze"]
            for i, part in enumerate(cmd[2:], 2):  # Start from index 2
                if part in known_subcommands:
                    subcommand_idx = i
                    break

            if subcommand_idx > 2:  # Found subcommand, insert global flags before it
                before_subcommand = cmd[:subcommand_idx]
                after_subcommand = cmd[subcommand_idx:]

                # Add remaining global flags
                if hasattr(self.args, 'config') and self.args.config != 'config.yaml':
                    before_subcommand.extend(["--config", self.args.config])
                if hasattr(self.args, 'verbose') and self.args.verbose:
                    before_subcommand.append("--verbose")

                final_cmd = before_subcommand + after_subcommand
            else:
                # No subcommand found or at wrong position, add flags at end
                final_cmd = cmd[:]
                if hasattr(self.args, 'config') and self.args.config != 'config.yaml':
                    final_cmd.extend(["--config", self.args.config])
                if hasattr(self.args, 'verbose') and self.args.verbose:
                    final_cmd.append("--verbose")
        else:
            final_cmd = cmd

        # Handle unsupported flags with warnings (only once)
        if hasattr(self.args, 'log_jsonl') and self.args.log_jsonl:
            self._show_warning_once("--log-jsonl not supported by underlying processors")

        if hasattr(self.args, 'profile') and self.args.profile:
            self._show_warning_once("--profile not supported by underlying processors")

        # Execute command
        original_cwd = os.getcwd()
        try:
            os.chdir(self.base_path)
            print(f"Dispatching to: {' '.join(final_cmd)}")
            result = subprocess.run(final_cmd, cwd=self.base_path)
            return result.returncode
        finally:
            os.chdir(original_cwd)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='altgen',
        description='Unified CLI dispatcher for alt text generation and processing'
    )

    # Global flags
    parser.add_argument('--config', metavar='PATH', default='config.yaml',
                       help='Path to config.yaml file (default: config.yaml)')
    parser.add_argument('--mode', choices=MODES, default='auto',
                       help='Processing mode')
    parser.add_argument('--alt-policy', choices=POLICIES, default='smart',
                       help='Alt text policy')
    parser.add_argument('--min-confidence', type=float, metavar='FLOAT',
                       help='Minimum confidence threshold (0.0-1.0)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Dry run mode (no changes)')
    parser.add_argument('--log-jsonl', metavar='PATH',
                       help='Path to JSONL log file')
    parser.add_argument('--profile', metavar='NAME',
                       help='Load preset from config.yaml')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output')

    # Processor selection flags
    parser.add_argument('--use-manifest', action='store_true',
                       help='Use manifest-based processor')
    parser.add_argument('--clean-pipeline', action='store_true',
                       help='Use clean 3-phase pipeline processor')
    parser.add_argument('--resume', action='store_true',
                       help='Resume from existing manifest')

    # Legacy compatibility flags (for backward compatibility)
    parser.add_argument('--include-hidden', action='store_true',
                       help='Include hidden slides in processing (passed to processor)')
    parser.add_argument('--use-stub', action='store_true',
                       help='Use stub data (legacy compatibility - ignored)')

    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # analyze
    analyze_parser = subparsers.add_parser('analyze', help='Analyze files for alt text opportunities')
    analyze_parser.add_argument('path', help='File or folder to analyze')

    # process
    process_parser = subparsers.add_parser('process', help='Process files and make alt text decisions')
    process_parser.add_argument('path', help='File or folder to process')
    process_parser.add_argument('--no-artifacts', action='store_true',
                               help='Disable artifact directory creation (no intermediate files saved)')

    # inject
    inject_parser = subparsers.add_parser('inject', help='Inject alt text into files')
    inject_parser.add_argument('path', help='File or folder to inject')

    # review
    review_parser = subparsers.add_parser('review', help='Review JSONL manifest and create summary')
    review_parser.add_argument('--manifest', required=True, help='Path to JSONL manifest')
    review_parser.add_argument('--out', required=True, help='Output path for review')

    # audit
    audit_parser = subparsers.add_parser('audit', help='Audit files for compliance')
    audit_parser.add_argument('path', help='File or folder to audit')

    # cleanup
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up old artifact directories')
    cleanup_parser.add_argument('--max-age-days', type=int, default=7,
                               help='Maximum age in days before cleanup (default: 7)')
    cleanup_parser.add_argument('--dry-run', action='store_true',
                               help='Show what would be cleaned without actually cleaning')
    cleanup_parser.add_argument('--report', action='store_true',
                               help='Show disk usage report')
    cleanup_parser.add_argument('--base-dir', default='.',
                               help='Base directory to scan (default: current directory)')

    # batch
    batch_parser = subparsers.add_parser(
        'batch',
        help='Batch process multiple presentations',
        description='Process PPTX files sequentially from a folder or glob pattern.'
    )
    batch_parser.add_argument(
        'target',
        help='Folder path or glob pattern identifying PPTX files'
    )

    # locks
    locks_parser = subparsers.add_parser('locks', help='Show file lock status')
    locks_parser.add_argument('--directory', default='.',
                             help='Directory to check for locks (default: current directory)')
    locks_parser.add_argument('--clean-stale', action='store_true',
                             help='Remove stale lock files')
    locks_parser.add_argument('--max-age-hours', type=int, default=1,
                             help='Age threshold for stale locks in hours (default: 1)')

    return parser


def main():
    try:
        parser = create_parser()
        args = parser.parse_args()

        if not args.command:
            parser.print_help()
            return 1

        # Validate file/directory exists
        if args.command in ['process', 'analyze', 'inject', 'audit']:
            if not os.path.exists(args.path):
                print(f"Error: File or directory not found: {args.path}")
                return 1

            if args.command in ['process', 'analyze', 'inject'] and os.path.isfile(args.path):
                if not args.path.lower().endswith(('.pptx', '.ppt')):
                    print(f"Error: File must be a PowerPoint presentation (.pptx or .ppt): {args.path}")
                    return 1

        # Create dispatcher and handle logging setup
        dispatcher = ProcessorDispatcher(args)

        # Setup JSONL logging once if requested
        if hasattr(args, 'log_jsonl') and args.log_jsonl:
            dispatcher.setup_logging()

        if args.command == 'analyze':
            return dispatcher.dispatch_analyze(args.path)

        elif args.command == 'process':
            return dispatcher.dispatch_process(args.path)

        elif args.command == 'inject':
            return dispatcher.dispatch_inject(args.path)

        elif args.command == 'review':
            return dispatcher.dispatch_review(args.manifest, args.out)

        elif args.command == 'audit':
            return dispatcher.dispatch_audit(args.path)

        elif args.command == 'cleanup':
            # Import cleanup utilities
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'shared'))
            from artifact_cleaner import cleanup_old_artifacts, print_usage_report, format_bytes
            from pathlib import Path

            base_dir = Path(args.base_dir).resolve()

            if args.report:
                print_usage_report(base_dir)
                return 0

            print(f"Scanning for artifacts older than {args.max_age_days} days in {base_dir}...")
            if args.dry_run:
                print("(DRY RUN - no files will be deleted)\n")

            stats = cleanup_old_artifacts(base_dir, args.max_age_days, args.dry_run)

            if stats['count'] > 0:
                action = "Would clean" if args.dry_run else "Cleaned"
                print(f"\n{action} {stats['count']} directories, freed {format_bytes(stats['bytes_freed'])}\n")

                if stats['directories'] and args.dry_run:
                    print("Directories to be cleaned:")
                    for dir_info in stats['directories'][:20]:  # Show top 20
                        age = f"{dir_info['age_days']:.1f} days"
                        size = format_bytes(dir_info['size_bytes'])
                        print(f"  {age:12s} {size:>10s}  {Path(dir_info['path']).name}")
            else:
                print("\nNo old artifact directories found.\n")

            if stats['errors']:
                print(f"⚠️  {len(stats['errors'])} errors encountered during cleanup")
                return 1

            return 0

        elif args.command == 'batch':
            # Import batch processor
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'core'))
            from batch_processor import PPTXBatchProcessor
            from shared.path_validator import SecurityError

            processor = PPTXBatchProcessor(config_path=args.config)

            try:
                files = processor.discover_files(args.target)
            except (SecurityError, FileNotFoundError, ValueError) as exc:
                print(f"Error: {exc}")
                return 1

            if not files:
                print("No PPTX files found.")
                return 0

            if args.dry_run:
                print(f"Discovered {len(files)} PPTX file(s). Dry run only.")
                return 0

            result = processor.process_batch(files)

            print("\nBatch complete")
            print(f"Total: {result['total']}")
            print(f"Succeeded: {result['succeeded']}")
            print(f"Failed: {result['failed']}")

            if result['errors']:
                print("\nErrors:")
                for error in result['errors']:
                    print(f"  {error['file']}: {error['error']}")

            return 0 if result['failed'] == 0 else 1

        elif args.command == 'locks':
            # Import lock utilities
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'shared'))
            from lock_monitor import print_lock_status
            from artifact_cleaner import cleanup_stale_locks
            from pathlib import Path

            directory = Path(args.directory).resolve()

            if args.clean_stale:
                print(f"Cleaning stale locks (older than {args.max_age_hours} hours) in {directory}...\n")
                stats = cleanup_stale_locks(directory, args.max_age_hours)

                if stats['count'] > 0:
                    print(f"✅ Removed {stats['count']} stale lock(s)\n")
                    if stats['stale_locks']:
                        print("Removed locks:")
                        for lock_info in stats['stale_locks']:
                            print(f"  {Path(lock_info['file']).name} (age: {lock_info['age_hours']}h, PID: {lock_info['pid']})")
                else:
                    print("No stale locks found.\n")

                if stats['errors']:
                    print(f"\n⚠️  {len(stats['errors'])} errors encountered")
                    return 1

                return 0
            else:
                # Show lock status
                print_lock_status(directory)
                return 0

        else:
            print(f"Error: Unknown command '{args.command}'")
            return 1

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
