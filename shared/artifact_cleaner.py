#!/usr/bin/env python3
"""
Artifact Cleaner Utility
=========================

Provides utilities for cleaning up old pipeline artifacts and monitoring disk usage.

Usage:
    from shared.artifact_cleaner import cleanup_old_artifacts, get_artifact_disk_usage

    # Clean up old artifacts
    stats = cleanup_old_artifacts(Path("."), max_age_days=7)
    print(f"Cleaned {stats['count']} directories, freed {stats['bytes_freed']} bytes")

    # Check disk usage
    usage = get_artifact_disk_usage(Path("."))
    print(f"Total artifacts: {usage['total_bytes']} bytes")
"""

import logging
from pathlib import Path
from typing import Dict, Any, List
from pipeline_artifacts import RunArtifacts

logger = logging.getLogger(__name__)


def cleanup_old_artifacts(base_dir: Path, max_age_days: int = 7, dry_run: bool = False) -> Dict[str, Any]:
    """
    Clean up old .alt_pipeline_* directories.

    Args:
        base_dir: Base directory to search for artifact directories
        max_age_days: Maximum age in days before cleanup (default: 7)
        dry_run: If True, report what would be cleaned without actually cleaning

    Returns:
        Dict with cleanup statistics:
            - count: Number of directories cleaned
            - bytes_freed: Total bytes freed
            - directories: List of cleaned directory info
            - errors: List of error messages
    """
    return RunArtifacts.cleanup_old_artifacts(base_dir, max_age_days, dry_run)


def get_artifact_disk_usage(base_dir: Path) -> Dict[str, Any]:
    """
    Calculate disk usage of pipeline artifacts grouped by age.

    Args:
        base_dir: Base directory to scan for artifact directories

    Returns:
        Dict with usage statistics:
            - total_count: Total number of artifact directories
            - total_bytes: Total size in bytes
            - by_age: Dict with counts/bytes grouped by age category
            - directories: List of directory info with age and size
    """
    import time

    stats = {
        'total_count': 0,
        'total_bytes': 0,
        'by_age': {
            'less_than_1_day': {'count': 0, 'bytes': 0},
            '1_to_7_days': {'count': 0, 'bytes': 0},
            'more_than_7_days': {'count': 0, 'bytes': 0}
        },
        'directories': [],
        'errors': []
    }

    if not base_dir.exists():
        return stats

    now = time.time()
    one_day = 86400
    seven_days = 7 * 86400

    try:
        for path in base_dir.glob(".alt_pipeline_*"):
            if not path.is_dir():
                continue

            try:
                mtime = path.stat().st_mtime
                age_seconds = now - mtime
                age_days = age_seconds / 86400
                size = RunArtifacts._calculate_dir_size(path)

                stats['total_count'] += 1
                stats['total_bytes'] += size

                # Categorize by age
                if age_seconds < one_day:
                    category = 'less_than_1_day'
                elif age_seconds < seven_days:
                    category = '1_to_7_days'
                else:
                    category = 'more_than_7_days'

                stats['by_age'][category]['count'] += 1
                stats['by_age'][category]['bytes'] += size

                stats['directories'].append({
                    'path': str(path),
                    'name': path.name,
                    'age_days': round(age_days, 1),
                    'size_bytes': size,
                    'category': category
                })

            except Exception as e:
                error_msg = f"Error processing {path}: {e}"
                logger.debug(error_msg)
                stats['errors'].append(error_msg)

    except Exception as e:
        error_msg = f"Failed to scan for artifacts: {e}"
        logger.error(error_msg)
        stats['errors'].append(error_msg)

    # Sort directories by age (oldest first)
    stats['directories'].sort(key=lambda x: x['age_days'], reverse=True)

    return stats


def format_bytes(bytes_count: int) -> str:
    """
    Format byte count as human-readable string.

    Args:
        bytes_count: Number of bytes

    Returns:
        Formatted string (e.g., "1.5 GB", "234 MB", "5.2 KB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} PB"


def print_usage_report(base_dir: Path) -> None:
    """
    Print a formatted disk usage report for artifacts.

    Args:
        base_dir: Base directory to scan
    """
    usage = get_artifact_disk_usage(base_dir)

    print("\n=== Pipeline Artifacts Disk Usage ===\n")
    print(f"Total directories: {usage['total_count']}")
    print(f"Total disk usage:  {format_bytes(usage['total_bytes'])}\n")

    print("By Age:")
    for category, data in usage['by_age'].items():
        if data['count'] > 0:
            label = category.replace('_', ' ').title()
            print(f"  {label:20s}: {data['count']:3d} dirs, {format_bytes(data['bytes']):>10s}")

    if usage['directories']:
        print("\nOldest Directories:")
        for dir_info in usage['directories'][:10]:  # Show top 10
            age = f"{dir_info['age_days']:.1f} days"
            size = format_bytes(dir_info['size_bytes'])
            print(f"  {age:12s} {size:>10s}  {dir_info['name']}")

    if usage['errors']:
        print(f"\nWarnings: {len(usage['errors'])} errors encountered")

    print()


def check_artifact_disk_usage(base_dir: Path, warn_threshold_gb: float = 5.0) -> None:
    """
    Check artifact disk usage and warn if exceeding threshold.

    Args:
        base_dir: Base directory to check
        warn_threshold_gb: Threshold in gigabytes to trigger warning
    """
    usage = get_artifact_disk_usage(base_dir)

    total_gb = usage['total_bytes'] / (1024 ** 3)

    if total_gb > warn_threshold_gb:
        logger.warning(
            f"Pipeline artifacts using {format_bytes(usage['total_bytes'])} "
            f"({usage['total_count']} directories) - consider cleanup"
        )
        print(f"\n⚠️  Warning: Artifact disk usage ({format_bytes(usage['total_bytes'])}) "
              f"exceeds {warn_threshold_gb:.1f} GB threshold")
        print(f"   Run cleanup command to free space:")
        print(f"   python altgen.py cleanup --max-age-days 7\n")
    else:
        logger.info(f"Artifact disk usage: {format_bytes(usage['total_bytes'])} "
                   f"({usage['total_count']} directories)")


if __name__ == "__main__":
    # CLI for standalone usage
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Pipeline artifact cleanup utility")
    parser.add_argument("--base-dir", type=Path, default=Path("."),
                       help="Base directory to scan (default: current directory)")
    parser.add_argument("--max-age-days", type=int, default=7,
                       help="Maximum age in days before cleanup (default: 7)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be cleaned without actually cleaning")
    parser.add_argument("--report", action="store_true",
                       help="Show disk usage report")

    args = parser.parse_args()

    if args.report:
        print_usage_report(args.base_dir)
    else:
        print(f"Scanning for artifacts older than {args.max_age_days} days...")
        if args.dry_run:
            print("(DRY RUN - no files will be deleted)\n")

        stats = cleanup_old_artifacts(args.base_dir, args.max_age_days, args.dry_run)

        if stats['count'] > 0:
            action = "Would clean" if args.dry_run else "Cleaned"
            print(f"\n{action} {stats['count']} directories, "
                  f"freed {format_bytes(stats['bytes_freed'])}\n")

            if stats['directories'] and args.dry_run:
                print("Directories to be cleaned:")
                for dir_info in stats['directories']:
                    age = f"{dir_info['age_days']:.1f} days"
                    size = format_bytes(dir_info['size_bytes'])
                    print(f"  {age:12s} {size:>10s}  {Path(dir_info['path']).name}")
        else:
            print("\nNo old artifact directories found.\n")

        if stats['errors']:
            print(f"⚠️  {len(stats['errors'])} errors encountered during cleanup")
            sys.exit(1)
