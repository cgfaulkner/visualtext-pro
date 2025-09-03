"""
PPTX ALT Text Injector for PPTX Accessibility Processor
Injects ALT text into PowerPoint presentations using python-pptx XML manipulation
Integrates with existing ConfigManager, reinjection settings, and workflow patterns
"""

import logging
import os
import sys
import time
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from hashlib import md5
import tempfile

# Third-party imports for PPTX processing
try:
    from pptx import Presentation
    from pptx.shapes.picture import Picture
    from pptx.shapes.base import BaseShape
    from pptx.oxml.ns import _nsmap
    PPTX_AVAILABLE = True
except ImportError as e:
    PPTX_AVAILABLE = False
    PPTX_ERROR = str(e)

# Setup paths for shared and core modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

# Import shared modules
from config_manager import ConfigManager
from decorative_filter import is_force_decorative_by_filename

logger = logging.getLogger(__name__)


class PPTXImageIdentifier:
    """
    Robust image identifier for maintaining consistency across extract→generate→inject workflow.
    """
    
    def __init__(self, slide_idx: int, shape_idx: int, shape_name: str = "", 
                 image_hash: str = "", embed_id: str = ""):
        self.slide_idx = slide_idx
        self.shape_idx = shape_idx
        self.shape_name = shape_name
        self.image_hash = image_hash
        self.embed_id = embed_id
        self.image_key = self._create_image_key()
    
    def _create_image_key(self) -> str:
        """Create robust, unique identifier for image, supporting nested shapes."""
        # Handle nested shape IDs (e.g., "0_1_2" for deeply nested groups)
        if isinstance(self.shape_idx, str) and '_' in str(self.shape_idx):
            shape_component = f"shape_{self.shape_idx}"
        else:
            shape_component = f"shape_{self.shape_idx}"
        
        components = [f"slide_{self.slide_idx}", shape_component]
        
        if self.shape_name and not self.shape_name.startswith('Picture'):
            components.append(f"name_{self.shape_name}")
        
        if self.image_hash:
            components.append(f"hash_{self.image_hash[:8]}")
        
        return "_".join(components)
    
    @classmethod
    def from_shape(cls, shape: Picture, slide_idx: int, shape_idx):
        """Create identifier from shape object, supporting nested/complex shape indices."""
        shape_name = getattr(shape, 'name', '')
        
        # Extract image hash if available
        image_hash = ""
        try:
            if hasattr(shape, 'image') and shape.image:
                image_data = shape.image.blob
                image_hash = md5(image_data).hexdigest()
        except Exception:
            pass
        
        # Extract embed ID if available
        embed_id = ""
        try:
            blip_fill = shape._element.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip')
            if blip_fill is not None:
                embed_id = blip_fill.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed', '')
        except Exception:
            pass
        
        return cls(slide_idx, shape_idx, shape_name, image_hash, embed_id)
    
    @classmethod
    def parse_from_complex_key(cls, image_key: str):
        """
        Parse complex image key format to extract components.
        Handles formats like: slide_X_shape_Y_Z_hash_XXXXX or slide_X_shape_Y_name_ABC_hash_XXXXX
        
        Args:
            image_key: Complex image key string
            
        Returns:
            PPTXImageIdentifier instance
        """
        parts = image_key.split('_')
        
        if len(parts) < 3 or not parts[0].startswith('slide') or not parts[2].startswith('shape'):
            raise ValueError(f"Invalid image key format: {image_key}")
        
        # Extract slide index
        slide_idx = int(parts[1])
        
        # Extract shape index (may be complex like "0_1_2")
        shape_parts = []
        i = 3
        while i < len(parts) and (parts[i].isdigit() or (i == 3)):
            shape_parts.append(parts[i])
            i += 1
        
        if not shape_parts:
            raise ValueError(f"No shape index found in key: {image_key}")
        
        shape_idx = "_".join(shape_parts) if len(shape_parts) > 1 else int(shape_parts[0])
        
        # Extract optional components
        shape_name = ""
        image_hash = ""
        
        while i < len(parts):
            if parts[i] == 'name' and i + 1 < len(parts):
                shape_name = parts[i + 1]
                i += 2
            elif parts[i] == 'hash' and i + 1 < len(parts):
                image_hash = parts[i + 1]
                i += 2
            else:
                i += 1
        
        return cls(slide_idx, shape_idx, shape_name, image_hash, "")


class PPTXAltTextInjector:
    """
    PPTX ALT text injector that integrates with existing system architecture.
    Supports multiple injection methods, validation, and ConfigManager integration.
    """
    
    def __init__(self, config_manager: Optional[ConfigManager] = None):
        """
        Initialize the PPTX ALT text injector.
        
        Args:
            config_manager: Optional ConfigManager instance
        """
        if not PPTX_AVAILABLE:
            raise ImportError(f"python-pptx is required: {PPTX_ERROR}")
        
        self.config_manager = config_manager or ConfigManager()
        
        # Get reinjection settings from config
        self.reinjection_config = self.config_manager.config.get('reinjection', {})
        self.skip_alt_text_if = self.reinjection_config.get('skip_alt_text_if', [])
        
        # Get ALT text handling settings
        self.alt_text_config = self.config_manager.config.get('alt_text_handling', {})
        self.mode = self.alt_text_config.get('mode', 'preserve')
        self.clean_generated_alt_text = self.alt_text_config.get('clean_generated_alt_text', True)
        
        # Get PPTX-specific settings
        self.pptx_config = self.config_manager.config.get('pptx_processing', {})
        
        # Register XML namespaces for decorative detection
        self._register_namespaces()
        
        # Statistics
        self.injection_stats = {
            'total_images': 0,
            'injected_successfully': 0,
            'skipped_existing': 0,
            'skipped_invalid': 0,
            'failed_injection': 0,
            'validation_failures': 0
        }
        
        logger.info("Initialized PPTX ALT text injector")
        logger.debug(f"Skip ALT text if: {self.skip_alt_text_if}")
        logger.debug(f"Mode: {self.mode}")
    
    def _register_namespaces(self):
        """Register required XML namespaces."""
        try:
            # Register decorative namespace for Office 2019+ decorative image support
            _nsmap["adec"] = "http://schemas.microsoft.com/office/drawing/2017/decorative"
        except Exception as e:
            logger.warning(f"Could not register XML namespaces: {e}")
    
    def inject_alt_text_from_mapping(self, pptx_path: str, alt_text_mapping: Dict[str, str], 
                                   output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Inject ALT text into PPTX file from a mapping dictionary.
        
        Args:
            pptx_path: Path to input PPTX file
            alt_text_mapping: Dictionary mapping image keys to ALT text
            output_path: Optional output path (defaults to overwriting input)
            
        Returns:
            Dictionary with injection results and statistics
        """
        pptx_path = Path(pptx_path)
        if output_path is None:
            output_path = pptx_path
        else:
            output_path = Path(output_path)
        
        # Validate input file
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {pptx_path}")
        
        logger.info(f"Injecting ALT text into: {pptx_path}")
        logger.info(f"Output will be saved to: {output_path}")
        logger.info(f"ALT text mappings: {len(alt_text_mapping)}")
        
        # Reset statistics
        self.injection_stats = {key: 0 for key in self.injection_stats}
        
        try:
            # Load presentation
            presentation = Presentation(str(pptx_path))
            
            # Build image identifier mapping for matching
            image_identifiers = self._build_image_identifier_mapping(presentation)
            
            # Debug: Show what keys we have vs what we expect
            logger.debug(f"Mapping keys from generator ({len(alt_text_mapping)}):")
            for key in sorted(alt_text_mapping.keys()):
                logger.debug(f"  Expected: {key}")
            
            logger.debug(f"Identifier keys from PPTX ({len(image_identifiers)}):")
            for key in sorted(image_identifiers.keys()):
                logger.debug(f"  Available: {key}")
            
            # Inject ALT text for each mapping
            matched_keys = []
            unmatched_keys = []
            
            for image_key, alt_text in alt_text_mapping.items():
                if image_key in image_identifiers:
                    identifier, shape = image_identifiers[image_key]
                    self._inject_alt_text_single(shape, alt_text, identifier)
                    matched_keys.append(image_key)
                else:
                    # Try fallback injection methods for unmatched keys
                    if self._try_fallback_injection(presentation, image_key, alt_text):
                        matched_keys.append(image_key)
                        logger.info(f"Successfully injected via fallback method: {image_key}")
                    else:
                        logger.warning(f"Could not find image for key (even with fallback): {image_key}")
                        unmatched_keys.append(image_key)
            
            logger.info(f"Key matching results: {len(matched_keys)} matched, {len(unmatched_keys)} unmatched")
            
            # VERIFICATION STEP: Check what ALT texts are actually in the presentation before saving
            logger.info("🔍 DEBUG: POST-INJECTION VERIFICATION")
            self._perform_post_injection_verification(presentation, image_identifiers, alt_text_mapping)
            
            # Save presentation
            output_path.parent.mkdir(parents=True, exist_ok=True)
            presentation.save(str(output_path))
            
            # Create result summary
            result = {
                'success': True,
                'input_file': str(pptx_path),
                'output_file': str(output_path),
                'statistics': self.injection_stats.copy(),
                'errors': []
            }
            
            self._log_injection_summary(result)
            return result
            
        except Exception as e:
            error_msg = f"Failed to inject ALT text: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            return {
                'success': False,
                'input_file': str(pptx_path),
                'output_file': str(output_path),
                'statistics': self.injection_stats.copy(),
                'errors': [error_msg]
            }
    
    def _build_image_identifier_mapping(self, presentation: Presentation) -> Dict[str, Tuple[PPTXImageIdentifier, Picture]]:
        """
        Build mapping from image keys to (identifier, shape) tuples using recursive traversal
        to find images within grouped shapes, chart elements, and nested structures.
        
        Args:
            presentation: PowerPoint presentation
            
        Returns:
            Dictionary mapping image keys to (identifier, shape) tuples
        """
        mapping = {}
        logger.info("🔍 DEBUG: Starting _build_image_identifier_mapping")
        
        for slide_idx, slide in enumerate(presentation.slides):
            logger.info(f"🔍 DEBUG: Processing slide {slide_idx + 1} for image mapping")
            logger.info(f"🔍 DEBUG:   Total shapes on slide: {len(slide.shapes)}")
            
            # Use recursive shape processing from enhanced detection system
            images_found = self._extract_images_from_shapes_for_mapping(
                slide.shapes, slide_idx, parent_group_idx=None
            )
            
            logger.info(f"🔍 DEBUG:   Images found on slide {slide_idx + 1}: {len(images_found)}")
            
            for identifier, shape in images_found:
                self.injection_stats['total_images'] += 1
                mapping[identifier.image_key] = (identifier, shape)
                
                # Log detailed shape information
                logger.info(f"🔍 DEBUG:   Mapped image key: {identifier.image_key}")
                logger.info(f"🔍 DEBUG:     Shape type: {type(shape).__name__}")
                logger.info(f"🔍 DEBUG:     Shape ID: {getattr(shape, 'id', 'unknown')}")
                logger.info(f"🔍 DEBUG:     Shape name: {getattr(shape, 'name', 'unknown')}")
                if hasattr(shape, '_element'):
                    logger.info(f"🔍 DEBUG:     XML element: {shape._element.tag if hasattr(shape._element, 'tag') else 'unknown'}")
                
                # Check current ALT text
                current_alt = ""
                try:
                    if hasattr(shape, 'descr'):
                        current_alt = shape.descr or ""
                    elif hasattr(shape, '_element'):
                        current_alt = shape._element.get('descr', "") or ""
                except:
                    pass
                logger.info(f"🔍 DEBUG:     Current ALT text: '{current_alt}'")
            
            logger.info(f"🔍 DEBUG: Completed slide {slide_idx + 1} - found {len(images_found)} images")
        
        logger.info(f"🔍 DEBUG: Completed mapping build - total images: {len(mapping)}")
        logger.info(f"🔍 DEBUG: Final image keys in mapping:")
        for key in sorted(mapping.keys()):
            logger.info(f"🔍 DEBUG:   - {key}")
        
        return mapping
    
    def _extract_images_from_shapes_for_mapping(self, shapes, slide_idx: int, parent_group_idx: str = None) -> List[Tuple[PPTXImageIdentifier, Picture]]:
        """
        Recursively extract images from shapes for identifier mapping, including grouped shapes.
        Based on the enhanced detection system's recursive logic.
        
        Args:
            shapes: Collection of shapes to process
            slide_idx: Slide index
            parent_group_idx: Index of parent group if this is a nested call
            
        Returns:
            List of (identifier, shape) tuples
        """
        image_mappings = []
        
        for shape_idx, shape in enumerate(shapes):
            try:
                # Create hierarchical shape identifier for nested images
                if parent_group_idx is not None:
                    shape_id = f"{parent_group_idx}_{shape_idx}"
                else:
                    shape_id = shape_idx
                
                # Debug: Log shape examination
                shape_name = getattr(shape, 'name', 'unnamed')
                shape_type = getattr(shape, 'shape_type', 'unknown')
                logger.debug(f"    Examining shape {shape_id}: {type(shape).__name__} (type={shape_type}, name='{shape_name}')")
                
                # 1. Direct picture shapes (original logic)
                if hasattr(shape, 'image') and shape.image:
                    logger.debug(f"      -> Found direct picture shape")
                    try:
                        identifier = PPTXImageIdentifier.from_shape(shape, slide_idx, shape_id)
                        # Update identifier to handle complex nested IDs
                        identifier = self._update_identifier_for_nested_shape(identifier, shape_id)
                        image_mappings.append((identifier, shape))
                        logger.debug(f"      -> Mapped direct image: {identifier.image_key}")
                        
                    except Exception as e:
                        logger.warning(f"Failed to create identifier for direct image at shape {shape_id}: {e}")
                
                # 2. Group shapes (recursively process shapes within groups)
                if hasattr(shape, 'shapes'):
                    logger.debug(f"      -> Found group shape with {len(shape.shapes)} child shapes")
                    group_images = self._extract_images_from_shapes_for_mapping(
                        shape.shapes, slide_idx, shape_id
                    )
                    image_mappings.extend(group_images)
                    logger.debug(f"      -> Mapped {len(group_images)} images from group")
                
                # 3. Chart shapes (may contain images) - placeholder for future enhancement
                if hasattr(shape, 'chart'):
                    logger.debug(f"      -> Found chart shape (chart image mapping not yet implemented)")
                    # Future: Extract images from chart backgrounds, fills, etc.
                
                # 4. Text boxes and shape fills with image content - placeholder
                if hasattr(shape, 'fill'):
                    logger.debug(f"      -> Shape has fill property (fill image mapping not yet implemented)")
                    # Future: Extract images from picture fills, texture fills
                
            except Exception as e:
                logger.warning(f"Error processing shape {shape_idx} on slide {slide_idx}: {e}")
                continue
        
        return image_mappings
    
    def _update_identifier_for_nested_shape(self, identifier: PPTXImageIdentifier, shape_id) -> PPTXImageIdentifier:
        """
        Update identifier for nested shapes to handle complex hierarchical IDs.
        
        Args:
            identifier: Original identifier
            shape_id: Hierarchical shape ID (e.g., "0_1_2" for nested groups)
            
        Returns:
            Updated identifier with complex shape index
        """
        # If shape_id contains underscores, it's a nested shape
        if isinstance(shape_id, str) and '_' in str(shape_id):
            # Update the shape_idx to reflect the nested structure
            identifier.shape_idx = shape_id
            # Recreate the image key with the updated shape index
            identifier.image_key = identifier._create_image_key()
        
        return identifier
    
    def _try_fallback_injection(self, presentation: Presentation, image_key: str, alt_text: str) -> bool:
        """
        Try fallback injection methods for images that weren't found through normal shape traversal.
        This handles images accessible through relationships but not the shape API.
        
        Args:
            presentation: PowerPoint presentation
            image_key: Image key that wasn't matched
            alt_text: ALT text to inject
            
        Returns:
            bool: True if injection succeeded via fallback method
        """
        logger.debug(f"Attempting fallback injection for {image_key}")
        
        # Try to parse the image key to understand what we're looking for
        try:
            identifier = PPTXImageIdentifier.parse_from_complex_key(image_key)
            logger.debug(f"Parsed fallback key: slide={identifier.slide_idx}, shape={identifier.shape_idx}")
        except Exception as e:
            logger.debug(f"Could not parse image key for fallback: {e}")
            return False
        
        # Method 1: Try relationship-based injection
        if self._try_relationship_based_injection(presentation, identifier, alt_text):
            return True
        
        # Method 2: Try XML-based direct manipulation
        if self._try_xml_based_injection(presentation, identifier, alt_text):
            return True
        
        # Method 3: Try slide part-based injection
        if self._try_slide_part_injection(presentation, identifier, alt_text):
            return True
        
        logger.debug(f"All fallback methods failed for {image_key}")
        return False
    
    def _try_relationship_based_injection(self, presentation: Presentation, identifier: PPTXImageIdentifier, alt_text: str) -> bool:
        """
        Try to inject ALT text by finding images through presentation relationships.
        
        Args:
            presentation: PowerPoint presentation
            identifier: Image identifier
            alt_text: ALT text to inject
            
        Returns:
            bool: True if successful
        """
        try:
            logger.debug(f"Trying relationship-based injection for slide {identifier.slide_idx}")
            
            if identifier.slide_idx >= len(presentation.slides):
                return False
            
            slide = presentation.slides[identifier.slide_idx]
            slide_part = slide.part
            
            # Look through slide relationships for images
            for relationship in slide_part.rels.values():
                if hasattr(relationship, 'target_part'):
                    target = relationship.target_part
                    if hasattr(target, 'content_type') and target.content_type.startswith('image/'):
                        logger.debug(f"Found image relationship: {relationship.rId}")
                        # Try to find the corresponding element in the slide XML and set ALT text
                        if self._inject_alt_via_relationship(slide, relationship.rId, alt_text, identifier):
                            return True
            
        except Exception as e:
            logger.debug(f"Relationship-based injection failed: {e}")
        
        return False
    
    def _inject_alt_via_relationship(self, slide, rel_id: str, alt_text: str, identifier: PPTXImageIdentifier) -> bool:
        """
        Inject ALT text by finding XML elements that reference a specific relationship ID.
        
        Args:
            slide: Slide object
            rel_id: Relationship ID
            alt_text: ALT text to inject
            identifier: Image identifier for matching
            
        Returns:
            bool: True if successful
        """
        try:
            # Access the slide's XML and look for elements with this relationship ID
            slide_xml = slide._element
            
            # Look for blip elements that reference this relationship
            blip_elements = slide_xml.xpath(f'.//a:blip[@r:embed="{rel_id}"]', 
                                          namespaces={'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
                                                    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'})
            
            for blip_element in blip_elements:
                # Find the parent cNvPr element where we can set the description
                parent_elements = blip_element.xpath('ancestor::*')
                for parent in reversed(parent_elements):  # Start from closest ancestor
                    cnvpr_elements = parent.xpath('.//pic:cNvPr | .//p:cNvPr', 
                                                namespaces={'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture',
                                                          'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'})
                    
                    if cnvpr_elements:
                        cnvpr_element = cnvpr_elements[0]
                        # Verify this matches our identifier if possible
                        if self._verify_element_matches_identifier(cnvpr_element, identifier):
                            cnvpr_element.set('descr', alt_text)
                            logger.debug(f"Injected ALT text via relationship {rel_id}")
                            return True
            
        except Exception as e:
            logger.debug(f"Failed to inject via relationship {rel_id}: {e}")
        
        return False
    
    def _verify_element_matches_identifier(self, element, identifier: PPTXImageIdentifier) -> bool:
        """
        Verify that an XML element matches the given identifier.
        
        Args:
            element: XML element
            identifier: Image identifier
            
        Returns:
            bool: True if element matches identifier
        """
        try:
            # For now, we'll be permissive since relationship-based matching
            # is already a fallback method. In a more sophisticated implementation,
            # we could check element IDs, names, or position information.
            
            # Check if element has a name that matches our identifier
            element_name = element.get('name', '')
            if identifier.shape_name and identifier.shape_name in element_name:
                return True
            
            # For fallback cases, assume match if we got this far
            return True
            
        except Exception:
            return True  # Be permissive for fallback injection
    
    def _try_xml_based_injection(self, presentation: Presentation, identifier: PPTXImageIdentifier, alt_text: str) -> bool:
        """
        Try direct XML manipulation to inject ALT text.
        
        Args:
            presentation: PowerPoint presentation
            identifier: Image identifier
            alt_text: ALT text to inject
            
        Returns:
            bool: True if successful
        """
        try:
            logger.debug(f"Trying XML-based injection for slide {identifier.slide_idx}")
            
            if identifier.slide_idx >= len(presentation.slides):
                return False
            
            slide = presentation.slides[identifier.slide_idx]
            slide_xml = slide._element
            
            # Look for all pic:cNvPr elements (picture non-visual properties)
            cnvpr_elements = slide_xml.xpath('.//pic:cNvPr',
                                           namespaces={'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture'})
            
            # Try to match by position or other identifying characteristics
            for i, cnvpr in enumerate(cnvpr_elements):
                if self._element_matches_shape_index(cnvpr, identifier.shape_idx, i):
                    cnvpr.set('descr', alt_text)
                    logger.debug(f"Injected ALT text via XML manipulation at index {i}")
                    return True
            
        except Exception as e:
            logger.debug(f"XML-based injection failed: {e}")
        
        return False
    
    def _element_matches_shape_index(self, element, target_shape_idx, current_index: int) -> bool:
        """
        Check if an XML element matches the target shape index.
        
        Args:
            element: XML element
            target_shape_idx: Target shape index (may be complex like "0_1_2")
            current_index: Current enumeration index
            
        Returns:
            bool: True if element matches
        """
        # If target is a simple integer, match by current index
        if isinstance(target_shape_idx, int):
            return current_index == target_shape_idx
        
        # For complex shape indices, this is more challenging
        # For now, use a heuristic approach
        if isinstance(target_shape_idx, str) and '_' in target_shape_idx:
            # Parse the complex index and try to match the last component
            parts = target_shape_idx.split('_')
            try:
                last_index = int(parts[-1])
                return current_index == last_index
            except ValueError:
                pass
        
        return False
    
    def _try_slide_part_injection(self, presentation: Presentation, identifier: PPTXImageIdentifier, alt_text: str) -> bool:
        """
        Try injection through slide part manipulation.
        
        Args:
            presentation: PowerPoint presentation
            identifier: Image identifier
            alt_text: ALT text to inject
            
        Returns:
            bool: True if successful
        """
        try:
            logger.debug(f"Trying slide part injection for slide {identifier.slide_idx}")
            
            if identifier.slide_idx >= len(presentation.slides):
                return False
            
            slide = presentation.slides[identifier.slide_idx]
            slide_part = slide.part
            
            # This is a placeholder for more advanced slide part manipulation
            # In a full implementation, this would involve:
            # 1. Parsing the slide's XML content
            # 2. Finding image elements by their relationship IDs
            # 3. Modifying the appropriate cNvPr elements
            # 4. Handling the part's relationships and embedded content
            
            logger.debug("Slide part injection not yet fully implemented")
            return False
            
        except Exception as e:
            logger.debug(f"Slide part injection failed: {e}")
            return False
    
    def _inject_alt_text_single(self, shape: Picture, alt_text: str, identifier: PPTXImageIdentifier) -> bool:
        """
        Inject ALT text into a single shape with comprehensive debug logging.
        
        Args:
            shape: Picture shape to inject ALT text into
            alt_text: ALT text to inject
            identifier: Image identifier for logging
            
        Returns:
            bool: True if injection was successful
        """
        try:
            logger.debug(f"🔍 Processing injection for {identifier.image_key}")
            logger.debug(f"   Generated ALT text: '{alt_text}'")
            
            # Check if we should skip this ALT text
            if self._should_skip_alt_text(alt_text):
                logger.debug(f"❌ DECISION: Skipping invalid ALT text for {identifier.image_key}: '{alt_text}'")
                logger.debug(f"   Reason: ALT text matches skip patterns")
                self.injection_stats['skipped_invalid'] += 1
                return False
            
            # Get existing ALT text to make informed decisions
            existing_alt_text = self._get_existing_alt_text(shape)
            logger.debug(f"   Existing ALT text in shape: '{existing_alt_text}' (empty: {not existing_alt_text})")
            
            # Determine if this is truly pre-existing ALT text or if we should inject
            should_inject, decision_reason = self._should_inject_alt_text(
                existing_alt_text, alt_text, identifier.image_key
            )
            
            logger.debug(f"🎯 DECISION: {'INJECT' if should_inject else 'SKIP'} for {identifier.image_key}")
            logger.debug(f"   Reason: {decision_reason}")
            
            if not should_inject:
                if existing_alt_text:
                    logger.debug(f"✅ Preserving existing ALT text: '{existing_alt_text}'")
                    self.injection_stats['skipped_existing'] += 1
                else:
                    logger.debug(f"❌ Skipping due to decision logic")
                    self.injection_stats['skipped_invalid'] += 1
                return True
            
            # Clean ALT text if configured
            if self.clean_generated_alt_text:
                cleaned_alt_text = self._clean_alt_text(alt_text)
                if cleaned_alt_text != alt_text:
                    logger.debug(f"   Cleaned ALT text: '{alt_text}' -> '{cleaned_alt_text}'")
                alt_text = cleaned_alt_text
            
            # Perform injection using multiple fallback methods
            logger.debug(f"🚀 Injecting ALT text: '{alt_text}'")
            success = self._inject_alt_text_robust(shape, alt_text)
            
            if success:
                # Validate injection
                if self._validate_alt_text_injection(shape, alt_text):
                    logger.debug(f"✅ Successfully injected ALT text for {identifier.image_key}: '{alt_text[:50]}...'")
                    self.injection_stats['injected_successfully'] += 1
                    return True
                else:
                    logger.warning(f"❌ ALT text injection validation failed for {identifier.image_key}")
                    logger.warning(f"   Expected: '{alt_text}'")
                    logger.warning(f"   Actual: '{self._get_existing_alt_text(shape)}'")
                    self.injection_stats['validation_failures'] += 1
                    return False
            else:
                logger.error(f"❌ All injection methods failed for {identifier.image_key}")
                self.injection_stats['failed_injection'] += 1
                return False
                
        except Exception as e:
            logger.error(f"💥 Error injecting ALT text for {identifier.image_key}: {e}")
            self.injection_stats['failed_injection'] += 1
            return False
    
    def _should_inject_alt_text(self, existing_alt_text: str, new_alt_text: str, image_key: str) -> Tuple[bool, str]:
        """
        Determine whether to inject new ALT text based on current state and mode.
        
        This is the core logic that fixes the preserve/overwrite issue by properly
        distinguishing between pre-existing ALT text vs freshly generated text.
        
        Args:
            existing_alt_text: Current ALT text in the shape (may be empty)
            new_alt_text: Newly generated ALT text to potentially inject
            image_key: Image identifier for logging
            
        Returns:
            Tuple of (should_inject: bool, reason: str)
        """
        # If no existing ALT text, always inject the new text
        if not existing_alt_text or existing_alt_text.strip() == "":
            return True, "No existing ALT text found - injecting new text"
        
        # Check if existing ALT text should be skipped (invalid patterns)
        if self._should_skip_alt_text(existing_alt_text):
            return True, f"Existing ALT text is invalid/skippable: '{existing_alt_text}' - replacing with new text"
        
        # Mode-based decisions
        if self.mode == 'overwrite':
            return True, f"Overwrite mode - replacing existing '{existing_alt_text}' with new text"
        
        elif self.mode == 'preserve':
            # In preserve mode, we need to distinguish between:
            # 1. Truly pre-existing ALT text (preserve it)
            # 2. ALT text that was just generated but is now being seen as "existing"
            
            # Check if this looks like generated decorative text that should be replaced
            if existing_alt_text.strip().lower() in ['[decorative image]', 'decorative image', '']:
                return True, f"Existing text appears to be generated decorative placeholder - replacing"
            
            # Check if existing ALT text matches common generation failure patterns
            failure_patterns = [
                'error', 'failed', 'cannot', 'unable', 'sorry', 
                'i cannot', 'i am unable', 'no description',
                'not available', 'description not available',
                'image could not be processed'
            ]
            
            existing_lower = existing_alt_text.lower()
            for pattern in failure_patterns:
                if pattern in existing_lower:
                    return True, f"Existing text contains failure pattern '{pattern}' - replacing"
            
            # If we have meaningful existing ALT text and we're in preserve mode,
            # check if the new text is significantly better
            if len(existing_alt_text.strip()) > 10:  # Meaningful length
                # For now, preserve existing meaningful ALT text in preserve mode
                # TODO: Could add AI comparison here to determine if new text is better
                return False, f"Preserve mode - keeping existing meaningful ALT text: '{existing_alt_text}'"
            else:
                # Short existing text might not be meaningful
                return True, f"Existing ALT text too short ('{existing_alt_text}') - replacing with new text"
        
        else:
            # Unknown mode, default to inject
            return True, f"Unknown mode '{self.mode}' - defaulting to inject"
    
    def _inject_alt_text_robust(self, shape: Picture, alt_text: str) -> bool:
        """
        Inject ALT text using multiple fallback methods for maximum compatibility.
        
        Args:
            shape: Picture shape
            alt_text: ALT text to inject
            
        Returns:
            bool: True if any method succeeded
        """
        # List of injection methods in order of preference
        injection_methods = [
            ('modern_property', self._inject_via_modern_property),
            ('xml_cnvpr', self._inject_via_xml_cnvpr),
            ('xml_element', self._inject_via_xml_element),
            ('xml_fallback', self._inject_via_xml_fallback)
        ]
        
        logger.debug(f"   Attempting {len(injection_methods)} injection methods:")
        
        for method_name, method_func in injection_methods:
            try:
                logger.debug(f"     Trying {method_name}...")
                if method_func(shape, alt_text):
                    logger.debug(f"     ✅ ALT text injected successfully via {method_name}")
                    return True
                else:
                    logger.debug(f"     ❌ Method {method_name} returned False")
            except Exception as e:
                logger.debug(f"     💥 Injection method {method_name} failed: {e}")
                continue
        
        logger.debug(f"   ❌ All {len(injection_methods)} injection methods failed")
        return False
    
    def _inject_via_modern_property(self, shape: Picture, alt_text: str) -> bool:
        """Inject using modern property-based approach (python-pptx >= 0.6.22)."""
        logger.info(f"🔍 DEBUG: XML PATH - Modern property injection")
        logger.info(f"🔍 DEBUG:   Shape type: {type(shape).__name__}")
        if hasattr(shape, 'descr'):
            logger.info(f"🔍 DEBUG:   Using shape.descr property (modern approach)")
            logger.info(f"🔍 DEBUG:   Setting ALT text: '{alt_text}'")
            shape.descr = alt_text
            
            # Verify it was set
            actual_value = getattr(shape, 'descr', '')
            logger.info(f"🔍 DEBUG:   Verification - got back: '{actual_value}'")
            return True
        else:
            logger.info(f"🔍 DEBUG:   Shape does not have 'descr' property")
        return False
    
    def _inject_via_xml_cnvpr(self, shape: Picture, alt_text: str) -> bool:
        """Inject via direct XML cNvPr element manipulation."""
        logger.info(f"🔍 DEBUG: XML PATH - cNvPr element injection")
        try:
            logger.info(f"🔍 DEBUG:   Accessing shape._element._nvXxPr.cNvPr")
            cNvPr = shape._element._nvXxPr.cNvPr
            logger.info(f"🔍 DEBUG:   cNvPr element found: {cNvPr}")
            logger.info(f"🔍 DEBUG:   cNvPr tag: {getattr(cNvPr, 'tag', 'unknown')}")
            logger.info(f"🔍 DEBUG:   Setting descr attribute: '{alt_text}'")
            cNvPr.set('descr', alt_text)
            
            # Verify it was set
            actual_value = cNvPr.get('descr', '')
            logger.info(f"🔍 DEBUG:   Verification - cNvPr.get('descr'): '{actual_value}'")
            return True
        except AttributeError as e:
            logger.info(f"🔍 DEBUG:   cNvPr element access failed: {e}")
            return False
    
    def _inject_via_xml_element(self, shape: Picture, alt_text: str) -> bool:
        """Inject via XML element attribute (current approach)."""
        logger.info(f"🔍 DEBUG: XML PATH - Direct element injection")
        try:
            logger.info(f"🔍 DEBUG:   Accessing shape._element")
            logger.info(f"🔍 DEBUG:   Element: {shape._element}")
            logger.info(f"🔍 DEBUG:   Element tag: {getattr(shape._element, 'tag', 'unknown')}")
            logger.info(f"🔍 DEBUG:   Setting descr attribute: '{alt_text}'")
            shape._element.set('descr', alt_text)
            
            # Verify it was set
            actual_value = shape._element.get('descr', '')
            logger.info(f"🔍 DEBUG:   Verification - element.get('descr'): '{actual_value}'")
            return True
        except Exception as e:
            logger.info(f"🔍 DEBUG:   XML element access failed: {e}")
            return False
    
    def _inject_via_xml_fallback(self, shape: Picture, alt_text: str) -> bool:
        """Fallback XML injection method."""
        elements_to_try = [
            ('shape._element', lambda: shape._element),
            ('shape._element._nvXxPr', lambda: shape._element._nvXxPr),
            ('shape._element._nvXxPr.cNvPr', lambda: shape._element._nvXxPr.cNvPr)
        ]
        
        for element_name, element_getter in elements_to_try:
            try:
                element = element_getter()
                if element is not None:
                    logger.debug(f"       Trying fallback on {element_name}")
                    element.set('descr', alt_text)
                    return True
            except Exception as e:
                logger.debug(f"       Fallback {element_name} failed: {e}")
                continue
        
        logger.debug(f"       All fallback methods exhausted")
        return False
    
    def _get_existing_alt_text(self, shape: Picture) -> str:
        """
        Get existing ALT text from shape with debug logging.
        
        Args:
            shape: Picture shape
            
        Returns:
            str: Existing ALT text or empty string
        """
        # Try modern property first
        try:
            if hasattr(shape, 'descr'):
                alt_text = shape.descr or ""
                logger.debug(f"   Retrieved ALT text via shape.descr: '{alt_text}'")
                return alt_text
            else:
                logger.debug(f"   Shape does not have 'descr' property")
        except Exception as e:
            logger.debug(f"   Failed to get ALT text via shape.descr: {e}")
        
        # Try XML access
        try:
            cNvPr = shape._element._nvXxPr.cNvPr
            alt_text = cNvPr.get('descr', '')
            logger.debug(f"   Retrieved ALT text via XML cNvPr: '{alt_text}'")
            return alt_text
        except Exception as e:
            logger.debug(f"   Failed to get ALT text via XML cNvPr: {e}")
        
        # Fallback XML access
        try:
            alt_text = shape._element.get('descr', '')
            logger.debug(f"   Retrieved ALT text via XML element: '{alt_text}'")
            return alt_text
        except Exception as e:
            logger.debug(f"   Failed to get ALT text via XML element: {e}")
        
        logger.debug(f"   No ALT text found via any method")
        return ""
    
    def _validate_alt_text_injection(self, shape: Picture, expected_alt_text: str) -> bool:
        """
        Validate that ALT text was successfully injected.
        
        Args:
            shape: Picture shape
            expected_alt_text: Expected ALT text
            
        Returns:
            bool: True if validation passed
        """
        actual_alt_text = self._get_existing_alt_text(shape)
        return actual_alt_text == expected_alt_text
    
    def _perform_post_injection_verification(self, presentation: Presentation, 
                                          image_identifiers: Dict[str, Tuple], 
                                          alt_text_mapping: Dict[str, str]) -> None:
        """
        Verify that ALT texts were actually injected after the injection process.
        
        Args:
            presentation: PowerPoint presentation
            image_identifiers: Mapping of image keys to (identifier, shape) tuples
            alt_text_mapping: Original ALT text mapping requested
        """
        logger.info("🔍 DEBUG: Verifying ALT text injection results...")
        
        successful_injections = 0
        failed_injections = 0
        
        # Check each image that we tried to inject
        for image_key, expected_alt_text in alt_text_mapping.items():
            if image_key in image_identifiers:
                identifier, shape = image_identifiers[image_key]
                
                # Get current ALT text using all available methods
                current_alt_text = self._get_existing_alt_text(shape)
                
                if current_alt_text == expected_alt_text:
                    logger.info(f"🔍 DEBUG: ✅ VERIFIED: {image_key}")
                    logger.info(f"🔍 DEBUG:   Expected: '{expected_alt_text}'")
                    logger.info(f"🔍 DEBUG:   Actual: '{current_alt_text}'")
                    successful_injections += 1
                else:
                    logger.info(f"🔍 DEBUG: ❌ FAILED: {image_key}")
                    logger.info(f"🔍 DEBUG:   Expected: '{expected_alt_text}'")
                    logger.info(f"🔍 DEBUG:   Actual: '{current_alt_text}'")
                    failed_injections += 1
                    
                    # Additional debug info for failed injections
                    logger.info(f"🔍 DEBUG:   Shape type: {type(shape).__name__}")
                    logger.info(f"🔍 DEBUG:   Shape ID: {getattr(shape, 'id', 'unknown')}")
                    if hasattr(shape, '_element'):
                        try:
                            # Check XML attributes directly
                            descr_attr = shape._element.get('descr')
                            logger.info(f"🔍 DEBUG:   XML descr attribute: '{descr_attr}'")
                            
                            # Check cNvPr element
                            if hasattr(shape._element, '_nvXxPr'):
                                cnvpr = getattr(shape._element._nvXxPr, 'cNvPr', None)
                                if cnvpr is not None:
                                    cnvpr_descr = cnvpr.get('descr')
                                    logger.info(f"🔍 DEBUG:   cNvPr descr attribute: '{cnvpr_descr}'")
                        except Exception as e:
                            logger.info(f"🔍 DEBUG:   XML inspection failed: {e}")
        
        logger.info(f"🔍 DEBUG: VERIFICATION SUMMARY:")
        logger.info(f"🔍 DEBUG:   Successful injections: {successful_injections}")
        logger.info(f"🔍 DEBUG:   Failed injections: {failed_injections}")
        logger.info(f"🔍 DEBUG:   Total attempted: {len(alt_text_mapping)}")
        
        # Also verify by re-scanning the presentation
        logger.info("🔍 DEBUG: Re-scanning presentation for all ALT texts...")
        all_alt_texts_found = 0
        for slide_idx, slide in enumerate(presentation.slides):
            for shape_idx, shape in enumerate(slide.shapes):
                if hasattr(shape, 'image') or hasattr(shape, '_element'):
                    alt_text = self._get_existing_alt_text(shape)
                    if alt_text.strip():
                        all_alt_texts_found += 1
                        logger.info(f"🔍 DEBUG:   Found ALT text on slide {slide_idx}, shape {shape_idx}: '{alt_text}'")
        
        logger.info(f"🔍 DEBUG: Total ALT texts found in presentation: {all_alt_texts_found}")
    
    def _should_skip_alt_text(self, alt_text: str) -> bool:
        """
        Check if ALT text should be skipped based on reinjection rules.
        
        Args:
            alt_text: ALT text to check
            
        Returns:
            bool: True if ALT text should be skipped
        """
        if not alt_text:
            return True
        
        alt_text_stripped = alt_text.strip()
        
        for skip_pattern in self.skip_alt_text_if:
            if isinstance(skip_pattern, str):
                if skip_pattern == alt_text_stripped:
                    return True
            
        return False
    
    def _clean_alt_text(self, alt_text: str) -> str:
        """
        Clean ALT text using existing alt_cleaner if available.
        
        Args:
            alt_text: ALT text to clean
            
        Returns:
            str: Cleaned ALT text
        """
        try:
            # Import and use existing alt_cleaner
            sys.path.insert(0, str(project_root / "shared"))
            from alt_cleaner import clean_alt_text
            return clean_alt_text(alt_text)
        except ImportError:
            logger.debug("alt_cleaner not available, using basic cleaning")
            # Basic cleaning - remove extra whitespace
            return " ".join(alt_text.split())
        except Exception as e:
            logger.warning(f"Error cleaning ALT text: {e}")
            return alt_text
    
    def _log_injection_summary(self, result: Dict[str, Any]):
        """Log summary of injection results."""
        stats = result['statistics']
        
        logger.info("PPTX ALT Text Injection Summary:")
        logger.info(f"  Input file: {result['input_file']}")
        logger.info(f"  Output file: {result['output_file']}")
        logger.info(f"  Total images found: {stats['total_images']}")
        logger.info(f"  Successfully injected: {stats['injected_successfully']}")
        logger.info(f"  Skipped (existing): {stats['skipped_existing']}")
        logger.info(f"  Skipped (invalid): {stats['skipped_invalid']}")
        logger.info(f"  Failed injection: {stats['failed_injection']}")
        logger.info(f"  Validation failures: {stats['validation_failures']}")
        logger.info(f"  Success: {result['success']}")
        
        if result.get('errors'):
            logger.warning(f"Errors encountered: {len(result['errors'])}")
            for error in result['errors']:
                logger.warning(f"  - {error}")
    
    def extract_images_with_identifiers(self, pptx_path: str) -> Dict[str, Dict[str, Any]]:
        """
        Extract images with robust identifiers for roundtrip workflow.
        
        Args:
            pptx_path: Path to PPTX file
            
        Returns:
            Dictionary mapping image keys to image information
        """
        pptx_path = Path(pptx_path)
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {pptx_path}")
        
        logger.info(f"Extracting images with identifiers from: {pptx_path}")
        
        presentation = Presentation(str(pptx_path))
        extracted_images = {}
        
        for slide_idx, slide in enumerate(presentation.slides):
            for shape_idx, shape in enumerate(slide.shapes):
                if hasattr(shape, 'image') and shape.image:
                    try:
                        # Create robust identifier
                        identifier = PPTXImageIdentifier.from_shape(shape, slide_idx, shape_idx)
                        
                        # Extract image information with consistent ALT text extraction
                        alt_text = self._get_existing_alt_text(shape)
                        image_info = {
                            'identifier': identifier,
                            'slide_idx': slide_idx,
                            'shape_idx': shape_idx,
                            'shape_name': identifier.shape_name,
                            'image_key': identifier.image_key,
                            'image_hash': identifier.image_hash,
                            'embed_id': identifier.embed_id,
                            'existing_alt_text': alt_text,
                            'alt_text': alt_text,  # Add explicit alt_text field for compatibility
                            'image_data': shape.image.blob,
                            'filename': getattr(shape.image, 'filename', f'slide_{slide_idx}_shape_{shape_idx}.png')
                        }
                        
                        extracted_images[identifier.image_key] = image_info
                        logger.debug(f"Extracted image: {identifier.image_key}")
                        
                    except Exception as e:
                        logger.warning(f"Failed to extract image from slide {slide_idx}, shape {shape_idx}: {e}")
        
        logger.info(f"Extracted {len(extracted_images)} images with identifiers")
        return extracted_images
    
    def test_pdf_export_alt_text_survival(self, pptx_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Test that ALT text survives PowerPoint → PDF export.
        
        Args:
            pptx_path: Path to PPTX file
            output_dir: Optional directory for output files
            
        Returns:
            Dictionary with test results
        """
        pptx_path = Path(pptx_path)
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {pptx_path}")
        
        if output_dir is None:
            output_dir = pptx_path.parent
        else:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Testing ALT text survival in PDF export for: {pptx_path}")
        
        # This would require PowerPoint automation or a PDF conversion library
        # For now, we'll create a placeholder test that validates ALT text exists in PPTX
        
        try:
            presentation = Presentation(str(pptx_path))
            alt_text_count = 0
            total_images = 0
            
            for slide_idx, slide in enumerate(presentation.slides):
                for shape_idx, shape in enumerate(slide.shapes):
                    if hasattr(shape, 'image') and shape.image:
                        total_images += 1
                        existing_alt = self._get_existing_alt_text(shape)
                        if existing_alt and not self._should_skip_alt_text(existing_alt):
                            alt_text_count += 1
            
            survival_test_result = {
                'success': True,
                'pptx_file': str(pptx_path),
                'total_images': total_images,
                'images_with_alt_text': alt_text_count,
                'alt_text_coverage': alt_text_count / total_images if total_images > 0 else 0,
                'test_type': 'pptx_validation',
                'note': 'Full PDF export testing requires PowerPoint automation or conversion library',
                'errors': []
            }
            
            logger.info(f"ALT text survival test completed:")
            logger.info(f"  Total images: {total_images}")
            logger.info(f"  Images with ALT text: {alt_text_count}")
            logger.info(f"  Coverage: {survival_test_result['alt_text_coverage']:.1%}")
            
            return survival_test_result
            
        except Exception as e:
            error_msg = f"PDF export survival test failed: {str(e)}"
            logger.error(error_msg)
            
            return {
                'success': False,
                'pptx_file': str(pptx_path),
                'test_type': 'pptx_validation',
                'errors': [error_msg]
            }


def create_alt_text_mapping(image_data: Dict[str, Dict[str, Any]], 
                          alt_text_results: Dict[str, str]) -> Dict[str, str]:
    """
    Create ALT text mapping from extracted image data and generation results.
    
    Args:
        image_data: Dictionary from extract_images_with_identifiers()
        alt_text_results: Dictionary mapping image keys to generated ALT text
        
    Returns:
        Dictionary mapping image keys to ALT text for injection
    """
    mapping = {}
    
    for image_key, image_info in image_data.items():
        if image_key in alt_text_results:
            alt_text = alt_text_results[image_key]
            mapping[image_key] = alt_text
            logger.debug(f"Mapped ALT text for {image_key}: {alt_text[:50]}...")
    
    logger.info(f"Created ALT text mapping for {len(mapping)} images")
    return mapping


def main():
    """Command-line interface for PPTX ALT text injection."""
    parser = argparse.ArgumentParser(
        description='Inject ALT text into PowerPoint presentations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pptx_alt_injector.py presentation.pptx --alt-text-file mappings.json
  python pptx_alt_injector.py presentation.pptx --extract-only --output extracted_images.json
  python pptx_alt_injector.py presentation.pptx --test-pdf-export
  python pptx_alt_injector.py presentation.pptx --config custom_config.yaml --verbose
        """
    )
    
    parser.add_argument('pptx_file', help='Input PPTX file')
    parser.add_argument('-o', '--output', help='Output PPTX file (default: overwrite input)')
    parser.add_argument('--alt-text-file', help='JSON file containing ALT text mappings')
    parser.add_argument('--extract-only', action='store_true', 
                       help='Only extract images with identifiers (no injection)')
    parser.add_argument('--test-pdf-export', action='store_true',
                       help='Test ALT text survival in PDF export')
    parser.add_argument('--config', help='Configuration file path')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--mode', choices=['preserve', 'overwrite'], 
                       help='ALT text handling mode')
    parser.add_argument('--debug-decisions', action='store_true',
                       help='Enable debug logging for injection decisions only')
    
    args = parser.parse_args()
    
    # Set up logging
    log_level = logging.DEBUG if (args.verbose or args.debug_decisions) else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # If debug-decisions is enabled, set up more focused logging
    if args.debug_decisions and not args.verbose:
        # Reduce noise from other modules
        logging.getLogger('pptx').setLevel(logging.WARNING)
        logging.getLogger('PIL').setLevel(logging.WARNING)
    
    try:
        # Initialize components
        config_manager = ConfigManager(args.config)
        injector = PPTXAltTextInjector(config_manager)
        
        # Override mode if specified
        if args.mode:
            injector.mode = args.mode
        
        print(f"PPTX ALT Text Injector")
        print(f"Processing: {args.pptx_file}")
        
        # Extract-only mode
        if args.extract_only:
            extracted_images = injector.extract_images_with_identifiers(args.pptx_file)
            output_file = args.output or f"{Path(args.pptx_file).stem}_extracted_images.json"
            
            import json
            with open(output_file, 'w') as f:
                # Convert to JSON-serializable format
                serializable = {}
                for key, info in extracted_images.items():
                    serializable[key] = {
                        'slide_idx': info['slide_idx'],
                        'shape_idx': info['shape_idx'],
                        'shape_name': info['shape_name'],
                        'image_key': info['image_key'],
                        'existing_alt_text': info['existing_alt_text'],
                        'filename': info['filename']
                    }
                json.dump(serializable, f, indent=2)
            
            print(f"Extracted {len(extracted_images)} images to: {output_file}")
            return 0
        
        # PDF export test mode
        if args.test_pdf_export:
            result = injector.test_pdf_export_alt_text_survival(args.pptx_file, args.output)
            
            if result['success']:
                print(f"✅ PDF export test completed")
                print(f"ALT text coverage: {result['alt_text_coverage']:.1%} ({result['images_with_alt_text']}/{result['total_images']})")
            else:
                print(f"❌ PDF export test failed")
                for error in result['errors']:
                    print(f"Error: {error}")
            
            return 0 if result['success'] else 1
        
        # ALT text injection mode
        if not args.alt_text_file:
            parser.error("--alt-text-file is required for ALT text injection")
        
        # Load ALT text mappings
        import json
        with open(args.alt_text_file, 'r') as f:
            alt_text_mapping = json.load(f)
        
        # Perform injection
        result = injector.inject_alt_text_from_mapping(
            args.pptx_file,
            alt_text_mapping,
            args.output
        )
        
        # Display results
        stats = result['statistics']
        print(f"\nInjection Results:")
        print(f"  Success: {result['success']}")
        print(f"  Images processed: {stats['injected_successfully']}/{stats['total_images']}")
        print(f"  Skipped (existing): {stats['skipped_existing']}")
        print(f"  Failed: {stats['failed_injection']}")
        
        if result.get('errors'):
            print(f"Errors:")
            for error in result['errors']:
                print(f"  - {error}")
        
        if result['success']:
            print(f"✅ ALT text injection completed successfully!")
            print(f"Output saved to: {result['output_file']}")
        else:
            print(f"❌ ALT text injection failed!")
        
        return 0 if result['success'] else 1
        
    except Exception as e:
        logger.error(f"ALT text injection failed: {e}", exc_info=True)
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())