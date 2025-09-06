"""
PDF Context Extractor for PDF ALT Text Generator
Extracts images and context from PDF documents using PyMuPDF
"""

import logging
import fitz  # PyMuPDF
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


def extract_pdf_context(pdf_path: str) -> Dict[str, Any]:
    """
    Extract images and context from PDF.
    
    Args:
        pdf_path: Path to the PDF file to process
        
    Returns:
        Dictionary containing:
        {
            'document_info': {...},
            'images': [
                {
                    'page_number': int,
                    'image_index': int, 
                    'bbox': (x, y, width, height),
                    'image_data': bytes,
                    'surrounding_text': str,
                    'page_text': str
                }
            ]
        }
    """
    pdf_path = Path(pdf_path)
    
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    result = {
        'document_info': {},
        'images': []
    }
    
    try:
        # Open PDF document
        doc = fitz.open(str(pdf_path))
        
        # Check if document is encrypted
        if doc.needs_pass:
            doc.close()
            raise ValueError(f"PDF is encrypted and requires a password: {pdf_path}")
        
        # Extract document metadata
        result['document_info'] = _extract_document_info(doc)
        logger.info(f"Opened PDF with {doc.page_count} pages: {pdf_path.name}")
        
        # Process each page
        for page_num in range(doc.page_count):
            page = doc[page_num]
            
            # Extract all text from page
            page_text = page.get_text()
            
            # Get all images on this page
            image_list = page.get_images(full=True)
            
            for img_index, img in enumerate(image_list):
                try:
                    # Extract image data and properties
                    image_info = _extract_image_info(doc, page, img, img_index, page_num + 1, page_text)
                    if image_info:
                        result['images'].append(image_info)
                        
                except Exception as e:
                    logger.warning(f"Failed to extract image {img_index} from page {page_num + 1}: {e}")
                    continue
        
        doc.close()
        logger.info(f"Extracted {len(result['images'])} images from {pdf_path.name}")
        
    except fitz.FileDataError as e:
        raise ValueError(f"Corrupted or invalid PDF file: {pdf_path} - {e}")
    except Exception as e:
        logger.error(f"Error processing PDF {pdf_path}: {e}")
        raise
    
    return result


def _extract_document_info(doc: fitz.Document) -> Dict[str, Any]:
    """Extract document metadata and properties."""
    metadata = doc.metadata
    
    return {
        'title': metadata.get('title', ''),
        'subject': metadata.get('subject', ''),
        'author': metadata.get('author', ''),
        'creator': metadata.get('creator', ''),
        'producer': metadata.get('producer', ''),
        'creation_date': metadata.get('creationDate', ''),
        'modification_date': metadata.get('modDate', ''),
        'page_count': doc.page_count,
        'is_pdf': True,
        'encrypted': doc.needs_pass
    }


def _extract_image_info(doc: fitz.Document, page: fitz.Page, img_tuple: tuple, 
                       img_index: int, page_number: int, page_text: str) -> Optional[Dict[str, Any]]:
    """
    Extract detailed information about a single image.
    
    Args:
        doc: PyMuPDF document object
        page: PyMuPDF page object
        img_tuple: Image tuple from page.get_images()
        img_index: Index of image on page
        page_number: 1-based page number
        page_text: Full text content of the page
        
    Returns:
        Dictionary with image information or None if extraction fails
    """
    try:
        # Get image reference
        xref = img_tuple[0]  # Image xref number
        
        # Get image data
        image_data = doc.extract_image(xref)
        img_bytes = image_data["image"]
        
        # Get image rectangles on the page
        image_rects = page.get_image_rects(img_tuple)
        
        # Use the first rectangle if multiple exist
        if image_rects:
            rect = image_rects[0]
            bbox = (rect.x0, rect.y0, rect.width, rect.height)
        else:
            # Fallback: use a default bbox if we can't find the image location
            bbox = (0, 0, 0, 0)
            logger.warning(f"Could not determine bbox for image {img_index} on page {page_number}")
        
        # Extract surrounding text context
        surrounding_text = _extract_surrounding_text(page, rect if image_rects else None, page_text)
        
        return {
            'page_number': page_number,
            'image_index': img_index,
            'bbox': bbox,
            'image_data': img_bytes,
            'surrounding_text': surrounding_text,
            'page_text': page_text,
            'image_format': image_data.get("ext", "unknown"),
            'image_width': image_data.get("width", 0),
            'image_height': image_data.get("height", 0),
            'colorspace': image_data.get("colorspace", 0)
        }
        
    except Exception as e:
        logger.error(f"Failed to extract image {img_index} from page {page_number}: {e}")
        return None


def _extract_surrounding_text(page: fitz.Page, image_rect: Optional[fitz.Rect], 
                             page_text: str) -> str:
    """
    Extract text surrounding an image for context.
    
    Args:
        page: PyMuPDF page object
        image_rect: Rectangle of the image on the page
        page_text: Full text content of the page
        
    Returns:
        Surrounding text context
    """
    if not image_rect:
        # If we don't have image position, return first 500 chars of page text
        return page_text[:500].strip() if page_text else ""
    
    try:
        # Get text blocks from the page
        blocks = page.get_text("dict")["blocks"]
        
        surrounding_text_parts = []
        
        # Look for text blocks near the image
        for block in blocks:
            if "lines" in block:  # Text block
                block_rect = fitz.Rect(block["bbox"])
                
                # Check if text block is near the image (within reasonable distance)
                distance = _calculate_rect_distance(image_rect, block_rect)
                
                if distance < 100:  # Within 100 points of the image
                    block_text = ""
                    for line in block["lines"]:
                        for span in line["spans"]:
                            block_text += span["text"]
                        block_text += " "
                    
                    if block_text.strip():
                        surrounding_text_parts.append(block_text.strip())
        
        # Join surrounding text parts
        surrounding_text = " ".join(surrounding_text_parts[:3])  # Limit to 3 nearest blocks
        
        # If no surrounding text found, return beginning of page text
        if not surrounding_text.strip():
            surrounding_text = page_text[:500].strip()
        
        return surrounding_text
        
    except Exception as e:
        logger.warning(f"Error extracting surrounding text: {e}")
        return page_text[:500].strip() if page_text else ""


def _calculate_rect_distance(rect1: fitz.Rect, rect2: fitz.Rect) -> float:
    """Calculate the minimum distance between two rectangles."""
    # Get the centers of the rectangles
    center1 = ((rect1.x0 + rect1.x1) / 2, (rect1.y0 + rect1.y1) / 2)
    center2 = ((rect2.x0 + rect2.x1) / 2, (rect2.y0 + rect2.y1) / 2)
    
    # Calculate Euclidean distance between centers
    dx = center1[0] - center2[0]
    dy = center1[1] - center2[1]
    return (dx * dx + dy * dy) ** 0.5


def main():
    """Test the PDF context extraction with a sample file."""
    import sys
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) != 2:
        print("Usage: python pdf_context_extractor.py <pdf_file>")
        print("\nThis will extract and display information about images found in the PDF.")
        return
    
    pdf_path = sys.argv[1]
    
    try:
        print(f"PDF Context Extractor Test")
        print("=" * 50)
        print(f"Processing: {pdf_path}")
        print()
        
        # Extract context
        result = extract_pdf_context(pdf_path)
        
        # Display results
        doc_info = result['document_info']
        print("Document Information:")
        print(f"  Title: {doc_info.get('title', 'N/A')}")
        print(f"  Author: {doc_info.get('author', 'N/A')}")
        print(f"  Pages: {doc_info.get('page_count', 'N/A')}")
        print(f"  Creator: {doc_info.get('creator', 'N/A')}")
        print()
        
        images = result['images']
        print(f"Found {len(images)} images:")
        print()
        
        for i, img in enumerate(images, 1):
            print(f"Image {i}:")
            print(f"  Page: {img['page_number']}")
            print(f"  Position: {img['bbox']}")
            print(f"  Format: {img.get('image_format', 'unknown')}")
            print(f"  Size: {img.get('image_width', 0)}x{img.get('image_height', 0)}")
            print(f"  Data size: {len(img['image_data'])} bytes")
            
            # Show surrounding text preview
            surrounding = img['surrounding_text']
            if surrounding:
                preview = surrounding[:100] + "..." if len(surrounding) > 100 else surrounding
                print(f"  Context: {preview}")
            else:
                print(f"  Context: No surrounding text found")
            print()
        
        print("Extraction completed successfully!")
        
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())