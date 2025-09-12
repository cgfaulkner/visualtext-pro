# approval/__init__.py
"""
Approval workflow module for PPTX ALT text processing.

This module provides functionality to generate Word review documents
for manual approval of generated ALT text suggestions.
"""

from .approval_pipeline import ApprovalOptions, make_review_doc
from .docx_alt_review import generate_alt_review_doc
from .llava_adapter import LegacyLLaVAAdapter

__all__ = ['ApprovalOptions', 'make_review_doc', 'generate_alt_review_doc', 'LegacyLLaVAAdapter']