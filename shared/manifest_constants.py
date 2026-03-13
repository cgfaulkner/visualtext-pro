#!/usr/bin/env python3
"""
Shared constants for manifest atomic write (batch_manifest.py and batch_queue.py).
Keep in sync with docs/batch_completion_criteria.md (atomic write).
"""

# Retries for os.replace before fallback
MANIFEST_REPLACE_RETRIES = 3

# Delay in seconds before each retry (exponential backoff)
MANIFEST_RETRY_DELAYS_S = (0.1, 0.2, 0.4)
