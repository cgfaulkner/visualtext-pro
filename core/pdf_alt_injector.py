"""
PDF ALT Text Injector for PDF ALT Text Generator
Injects ALT text into PDF documents using PyMuPDF structure tags
"""

import logging
import sys
import fitz  # PyMuPDF
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Setup paths for direct execution
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

logger = logging.getLogger(__name__)


def inject_alt_text(pdf_path: str, context_data: Dict[str, Any], 
                   alt_text_mapping: Dict[str, str], output_path: str) -> bool:
    """
    Inject ALT text into a PDF document.
    
    Args:
        pdf_path: Path to the original PDF file
        context_data: Output from extract_pdf_context()
        alt_text_mapping: Map of image identifiers to ALT text
                         Format: {"page_X_image_Y": "alt text", ...}
        output_path: Path where the modified PDF should be saved
        
    Returns:
        bool: True if injection was successful, False otherwise
    """
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    if not context_data.get('images'):
        logger.warning(f"No images found in context data for {pdf_path}")
        return False
    
    try:
        # Open the original PDF
        doc = fitz.open(str(pdf_path))
        
        if doc.needs_pass:
            doc.close()
            raise ValueError(f"PDF is encrypted and requires a password: {pdf_path}")
        
        logger.info(f"Processing PDF with {doc.page_count} pages: {pdf_path.name}")
        
        # Track injection statistics
        injected_count = 0
        skipped_count = 0
        
        # Process each image from the context data
        for image_info in context_data['images']:
            image_key = f"page_{image_info['page_number']}_image_{image_info['image_index']}"
            alt_text = alt_text_mapping.get(image_key)
            
            logger.info(f"Processing image: {image_key}")
            logger.debug(f"Image info: bbox={image_info.get('bbox')}, page={image_info['page_number']}")
            
            if not alt_text:
                logger.warning(f"No ALT text provided for {image_key}, skipping")
                skipped_count += 1
                continue
            
            logger.info(f"Found ALT text for {image_key}: {alt_text[:50]}...")
            
            # Inject ALT text for this image
            success = _inject_image_alt_text(doc, image_info, alt_text)
            if success:
                injected_count += 1
                logger.info(f"✅ Successfully injected ALT text for {image_key}")
            else:
                logger.error(f"❌ Failed to inject ALT text for {image_key}")
                skipped_count += 1
        
        # Save the modified PDF
        doc.save(str(output_path))
        doc.close()
        
        logger.info(f"ALT text injection completed: {injected_count} injected, {skipped_count} skipped")
        logger.info(f"Modified PDF saved to: {output_path}")
        
        return injected_count > 0
        
    except Exception as e:
        logger.error(f"Error injecting ALT text into {pdf_path}: {e}")
        raise


def _inject_image_alt_text(doc: fitz.Document, image_info: Dict[str, Any], alt_text: str) -> bool:
    """
    Inject ALT text for a specific image using multiple fallback methods.
    
    Args:
        doc: PyMuPDF document object
        image_info: Image information from context extractor
        alt_text: ALT text to inject
        
    Returns:
        bool: True if injection was successful
    """
    try:
        page_num = image_info['page_number'] - 1  # Convert to 0-based index
        page = doc[page_num]
        
        # Get image position
        bbox = image_info['bbox']
        image_rect = fitz.Rect(bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3])
        
        logger.debug(f"Attempting ALT text injection for image at {image_rect}")
        
        # Method 1: Try structure tree approach
        if _ensure_structure_tree(doc):
            logger.debug("Structure tree available, trying structure element method")
            if _add_image_structure_element(doc, page, image_rect, alt_text):
                logger.debug("Structure element method succeeded")
                return True
            logger.debug("Structure element method failed, trying fallbacks")
        else:
            logger.debug("Structure tree not available, skipping to fallback methods")
        
        # Method 2: Try annotation method
        logger.debug("Trying annotation method")
        if _add_alt_text_annotation(page, image_rect, alt_text):
            logger.debug("Annotation method succeeded")
            return True
        
        # Method 3: Try direct image metadata modification
        logger.debug("Trying direct image metadata method")
        if _add_alt_text_to_image_object(doc, page, image_info, alt_text):
            logger.debug("Direct image metadata method succeeded")
            return True
        
        # Method 4: Add as page-level text annotation (most basic fallback)
        logger.debug("Trying page-level text annotation method")
        if _add_page_level_alt_text(page, image_rect, alt_text):
            logger.debug("Page-level annotation method succeeded")
            return True
        
        logger.error(f"All ALT text injection methods failed for image on page {page_num + 1}")
        return False
        
    except Exception as e:
        logger.error(f"Failed to inject ALT text for image on page {image_info['page_number']}: {e}")
        return False


def _ensure_structure_tree(doc: fitz.Document) -> bool:
    """
    Ensure the PDF has a structure tree for accessibility.
    
    Args:
        doc: PyMuPDF document object
        
    Returns:
        bool: True if structure tree exists or was created
    """
    try:
        # Check if document already has a structure tree
        catalog = doc.pdf_catalog()
        logger.debug(f"PDF catalog type: {type(catalog)}")
        
        # Handle case where catalog might be an object reference instead of dict
        if catalog is not None:
            # Convert to dict if it's an object reference
            if hasattr(catalog, 'resolve'):
                catalog_dict = catalog.resolve()
            elif isinstance(catalog, dict):
                catalog_dict = catalog
            else:
                logger.debug(f"Catalog is type {type(catalog)}, treating as dict-like")
                catalog_dict = catalog
            
            # Check if structure tree already exists
            if catalog_dict and "StructTreeRoot" in catalog_dict:
                logger.debug("Structure tree already exists")
                return True
        
        # Create a basic structure tree
        logger.debug("Creating new structure tree")
        struct_tree_root = doc.new_object({
            "Type": "/StructTreeRoot",
            "ParentTree": doc.new_object({
                "Nums": []
            })
        })
        
        # Add structure tree root to catalog
        catalog_obj = doc.pdf_catalog()
        if catalog_obj:
            catalog_obj["StructTreeRoot"] = struct_tree_root
            logger.debug("Added StructTreeRoot to catalog")
            
        logger.info("Created basic structure tree successfully")
        return True
        
    except Exception as e:
        logger.warning(f"Could not create structure tree: {e}")
        logger.debug(f"Structure tree error details: {type(e).__name__}: {e}")
        return False


def _add_image_structure_element(doc: fitz.Document, page: fitz.Page, 
                                image_rect: fitz.Rect, alt_text: str) -> bool:
    """
    Add a structure element for an image with ALT text.
    
    Args:
        doc: PyMuPDF document object
        page: PyMuPDF page object
        image_rect: Rectangle defining image position
        alt_text: ALT text for the image
        
    Returns:
        bool: True if structure element was added successfully
    """
    try:
        # Create a Figure structure element
        figure_element = doc.new_object({
            "Type": "/StructElem",
            "S": "/Figure",
            "Alt": alt_text,  # This is the key field for ALT text
            "P": None,  # Parent (to be set)
            "Pg": page.obj,  # Page reference
            "BBox": [image_rect.x0, image_rect.y0, image_rect.x1, image_rect.y1]
        })
        
        # Try to add to existing structure tree
        catalog = doc.pdf_catalog()
        if catalog and "StructTreeRoot" in catalog:
            struct_root = catalog["StructTreeRoot"]
            
            # Create or get the document structure element
            if "/K" not in struct_root:
                # Create a Document structure element as root
                document_element = doc.new_object({
                    "Type": "/StructElem",
                    "S": "/Document",
                    "P": struct_root,
                    "K": [figure_element]
                })
                struct_root["K"] = document_element
                figure_element["P"] = document_element
            else:
                # Add to existing structure
                # This is simplified - in practice, you'd need to navigate the structure tree
                existing_kids = struct_root.get("/K", [])
                if not isinstance(existing_kids, list):
                    existing_kids = [existing_kids]
                existing_kids.append(figure_element)
                struct_root["K"] = existing_kids
                figure_element["P"] = struct_root
        
        logger.debug(f"Added structure element with ALT text: {alt_text[:30]}...")
        return True
        
    except Exception as e:
        logger.warning(f"Could not add structure element for image: {e}")
        # Fallback: try to add as annotation (less standard but sometimes works)
        return _add_alt_text_annotation(page, image_rect, alt_text)


def _add_alt_text_annotation(page: fitz.Page, image_rect: fitz.Rect, alt_text: str) -> bool:
    """
    Fallback method: Add ALT text as a hidden annotation.
    
    Args:
        page: PyMuPDF page object
        image_rect: Rectangle defining image position
        alt_text: ALT text for the image
        
    Returns:
        bool: True if annotation was added successfully
    """
    try:
        # Add a text annotation with the ALT text
        annotation = page.add_text_annot(
            image_rect.tl,  # Top-left point of image
            alt_text,
            icon="Note"
        )
        
        # Make annotation hidden but accessible to screen readers
        annotation.set_flags(annotation.flags | fitz.PDF_ANNOT_HIDDEN)
        annotation.update()
        
        logger.debug(f"Added text annotation with ALT text: {alt_text[:30]}...")
        return True
        
    except Exception as e:
        logger.debug(f"Could not add text annotation: {e}")
        return False


def _add_alt_text_to_image_object(doc: fitz.Document, page: fitz.Page, image_info: Dict[str, Any], alt_text: str) -> bool:
    """
    Try to add ALT text directly to the image object in the PDF.
    
    Args:
        doc: PyMuPDF document object
        page: PyMuPDF page object
        image_info: Image information from context extractor
        alt_text: ALT text for the image
        
    Returns:
        bool: True if ALT text was added to image object
    """
    try:
        # Get all images on the page
        image_list = page.get_images(full=True)
        
        if image_info['image_index'] < len(image_list):
            img_tuple = image_list[image_info['image_index']]
            xref = img_tuple[0]  # Image xref number
            
            # Try to get the image object and add ALT text metadata
            img_obj = doc.xref_object(xref)
            if img_obj:
                # Add ALT text as metadata (this approach varies by PDF structure)
                try:
                    doc.xref_set_key(xref, "Alt", f"({alt_text})")
                    logger.debug(f"Added ALT text to image object {xref}")
                    return True
                except Exception as e:
                    logger.debug(f"Could not set Alt key on image object: {e}")
                    
                # Alternative: try adding as custom metadata
                try:
                    doc.xref_set_key(xref, "AltText", f"({alt_text})")
                    logger.debug(f"Added AltText metadata to image object {xref}")
                    return True
                except Exception as e:
                    logger.debug(f"Could not set AltText key on image object: {e}")
        
        return False
        
    except Exception as e:
        logger.debug(f"Could not modify image object: {e}")
        return False


def _add_page_level_alt_text(page: fitz.Page, image_rect: fitz.Rect, alt_text: str) -> bool:
    """
    Most basic fallback: Add ALT text as a visible annotation near the image.
    
    Args:
        page: PyMuPDF page object
        image_rect: Rectangle defining image position
        alt_text: ALT text for the image
        
    Returns:
        bool: True if annotation was added successfully
    """
    try:
        # Add a small text annotation next to the image
        # Position it just outside the image boundary
        annot_point = fitz.Point(image_rect.x1 + 2, image_rect.y0)
        
        # Create a free text annotation
        annotation = page.add_freetext_annot(
            fitz.Rect(annot_point.x, annot_point.y, annot_point.x + 100, annot_point.y + 20),
            f"[ALT: {alt_text}]",
            fontsize=8,
            text_color=(0.5, 0.5, 0.5),  # Gray text
            fill_color=(1, 1, 1, 0.8)    # Semi-transparent white background
        )
        
        # Make it small and unobtrusive
        annotation.set_flags(annotation.flags | fitz.PDF_ANNOT_PRINT)
        annotation.update()
        
        logger.debug(f"Added page-level annotation with ALT text: {alt_text[:30]}...")
        return True
        
    except Exception as e:
        logger.debug(f"Could not add page-level annotation: {e}")
        return False


def batch_inject_alt_text(pdf_files: List[str], alt_text_mappings: Dict[str, Dict[str, str]], 
                         output_dir: str) -> Dict[str, bool]:
    """
    Inject ALT text into multiple PDF files.
    
    Args:
        pdf_files: List of PDF file paths to process
        alt_text_mappings: Map of PDF filename to ALT text mappings
                          Format: {"file.pdf": {"page_X_image_Y": "alt text", ...}, ...}
        output_dir: Directory to save modified PDFs
        
    Returns:
        Dict mapping PDF filenames to success status
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results = {}
    
    for pdf_path in pdf_files:
        pdf_name = Path(pdf_path).name
        
        try:
            # Skip if no ALT text mapping provided
            if pdf_name not in alt_text_mappings:
                logger.warning(f"No ALT text mapping provided for {pdf_name}, skipping")
                results[pdf_name] = False
                continue
            
            # Import context extractor to get image data
            from pdf_context_extractor import extract_pdf_context
            
            # Extract context
            context_data = extract_pdf_context(pdf_path)
            
            # Determine output path
            output_path = output_dir / f"alt_{pdf_name}"
            
            # Inject ALT text
            success = inject_alt_text(pdf_path, context_data, alt_text_mappings[pdf_name], str(output_path))
            results[pdf_name] = success
            
        except Exception as e:
            logger.error(f"Error processing {pdf_name}: {e}")
            results[pdf_name] = False
    
    return results


def create_alt_text_mapping(context_data: Dict[str, Any], alt_texts: List[str]) -> Dict[str, str]:
    """
    Helper function to create ALT text mapping from context data and ALT text list.
    
    Args:
        context_data: Output from extract_pdf_context()
        alt_texts: List of ALT texts corresponding to images in order
        
    Returns:
        Dict mapping image keys to ALT texts
    """
    mapping = {}
    
    for i, image_info in enumerate(context_data.get('images', [])):
        if i < len(alt_texts) and alt_texts[i]:
            image_key = f"page_{image_info['page_number']}_image_{image_info['image_index']}"
            mapping[image_key] = alt_texts[i]
    
    return mapping


def main():
    """Test the PDF ALT text injection with sample data."""
    import sys
    import json
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) not in [3, 4]:
        print("Usage: python pdf_alt_injector.py <pdf_file> <alt_mapping_json> [output_file]")
        print("\nalt_mapping_json format:")
        print('{"page_1_image_0": "Description of first image", "page_2_image_0": "Description of second image"}')
        print("\nIf output_file is not specified, will use 'alt_<original_filename>'")
        return
    
    pdf_path = sys.argv[1]
    mapping_file = sys.argv[2]
    output_path = sys.argv[3] if len(sys.argv) == 4 else f"alt_{Path(pdf_path).name}"
    
    try:
        print(f"PDF ALT Text Injector Test")
        print("=" * 50)
        print(f"Input PDF: {pdf_path}")
        print(f"ALT mapping: {mapping_file}")
        print(f"Output PDF: {output_path}")
        print()
        
        # Load ALT text mapping
        with open(mapping_file, 'r', encoding='utf-8') as f:
            alt_text_mapping = json.load(f)
        
        print(f"Loaded {len(alt_text_mapping)} ALT text mappings:")
        for key, alt_text in alt_text_mapping.items():
            preview = alt_text[:50] + "..." if len(alt_text) > 50 else alt_text
            print(f"  {key}: {preview}")
        print()
        
        # Extract context from PDF
        from pdf_context_extractor import extract_pdf_context
        context_data = extract_pdf_context(pdf_path)
        
        print(f"Found {len(context_data['images'])} images in PDF")
        
        # Inject ALT text
        success = inject_alt_text(pdf_path, context_data, alt_text_mapping, output_path)
        
        if success:
            print("\n✅ ALT text injection completed successfully!")
            print(f"Modified PDF saved to: {output_path}")
        else:
            print("\n❌ ALT text injection failed or no images were processed")
        
    except FileNotFoundError as e:
        print(f"Error: File not found - {e}")
        return 1
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in mapping file - {e}")
        return 1
    except Exception as e:
        logger.error(f"Injection failed: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())