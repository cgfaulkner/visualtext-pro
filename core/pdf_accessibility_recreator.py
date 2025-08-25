"""
PDF Accessibility Recreator for PDF ALT Text Generator
Recreates PDFs with proper accessibility structure using ReportLab
"""

import logging
import sys
import tempfile
import io
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Setup paths for direct execution
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

import fitz  # PyMuPDF for extraction
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image as RLImage,
)
from reportlab.platypus.flowables import Flowable
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch, cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import black, white
from reportlab.pdfbase import pdfdoc
import PIL.Image
import types

logger = logging.getLogger(__name__)


class AccessibleImage(Flowable):
    """Custom flowable for images with ALT text accessibility support."""
    
    def __init__(self, image_path: str, width: float, height: float, alt_text: str):
        """
        Initialize accessible image flowable.
        
        Args:
            image_path: Path to image file
            width: Image width in points
            height: Image height in points
            alt_text: ALT text for accessibility
        """
        Flowable.__init__(self)
        self.image_path = image_path
        self.width = width
        self.height = height
        self.alt_text = alt_text
        
    def draw(self):
        """Draw the image with accessibility metadata."""
        extra: Dict[str, Any] = {"imgObj": None}
        self.canv.drawImage(
            self.image_path,
            0,
            0,
            width=self.width,
            height=self.height,
            preserveAspectRatio=True,
            extraReturn=extra,
        )

        img_obj = extra.get("imgObj")
        if img_obj:
            self._add_accessibility_structure(img_obj)

    def _add_accessibility_structure(self, img_obj: pdfdoc.PDFImageXObject) -> None:
        """Create `/Figure` structure element and set ALT text."""
        try:
            img_obj.Alt = self.alt_text

            orig_format = pdfdoc.PDFImageXObject.format

            def format_with_alt(obj: pdfdoc.PDFImageXObject, document, _orig=orig_format):
                stream = pdfdoc.PDFStream(content=obj.streamContent)
                d = stream.dictionary
                d["Type"] = pdfdoc.PDFName("XObject")
                d["Subtype"] = pdfdoc.PDFName("Image")
                d["Width"] = obj.width
                d["Height"] = obj.height
                d["BitsPerComponent"] = obj.bitsPerComponent
                d["ColorSpace"] = pdfdoc.PDFName(obj.colorSpace)
                if obj.colorSpace == "DeviceCMYK" and getattr(obj, "_dotrans", 0):
                    d["Decode"] = pdfdoc.PDFArray([1, 0, 1, 0, 1, 0, 1, 0])
                elif getattr(obj, "_decode", None):
                    d["Decode"] = pdfdoc.PDFArray(obj._decode)
                d["Filter"] = pdfdoc.PDFArray(map(pdfdoc.PDFName, obj._filters))
                d["Length"] = len(obj.streamContent)
                if obj.mask:
                    d["Mask"] = pdfdoc.PDFArray(obj.mask)
                if getattr(obj, "smask", None):
                    d["SMask"] = obj.smask
                if getattr(obj, "Alt", None):
                    d["Alt"] = pdfdoc.PDFString(obj.Alt)
                return stream.format(document)

            img_obj.format = types.MethodType(format_with_alt, img_obj)

            catalog = self.canv._doc.Catalog
            if not hasattr(catalog, "StructTreeRoot"):
                struct_root = pdfdoc.PDFDictionary()
                struct_root["Type"] = pdfdoc.PDFName("StructTreeRoot")
                struct_root["K"] = pdfdoc.PDFArray([])
                catalog.StructTreeRoot = struct_root
            else:
                struct_root = catalog.StructTreeRoot

            figure = pdfdoc.PDFDictionary()
            figure["Type"] = pdfdoc.PDFName("StructElem")
            figure["S"] = pdfdoc.PDFName("Figure")
            figure["Alt"] = pdfdoc.PDFString(self.alt_text)
            struct_root["K"].sequence.append(figure)

            logger.debug(
                f"Added accessibility structure for image: {self.alt_text[:30]}..."
            )
        except Exception as exc:
            logger.debug(f"Could not add accessibility structure: {exc}")


class PDFAccessibilityRecreator:
    """
    Recreates PDFs with proper accessibility structure using ReportLab.
    """
    
    def __init__(self):
        """Initialize the PDF accessibility recreator."""
        self.temp_files = []  # Track temporary files for cleanup
        
    def recreate_accessible_pdf(self, original_pdf_path: str, alt_text_mapping: Dict[str, str], 
                               output_path: str) -> Dict[str, Any]:
        """
        Recreate a PDF with proper accessibility structure.
        
        Args:
            original_pdf_path: Path to the original PDF file
            alt_text_mapping: Map of image identifiers to ALT text
            output_path: Path for the recreated accessible PDF
            
        Returns:
            Dictionary with recreation statistics and results
        """
        result = {
            'success': False,
            'input_file': original_pdf_path,
            'output_file': output_path,
            'pages_processed': 0,
            'images_processed': 0,
            'errors': []
        }
        
        try:
            logger.info(f"Starting PDF recreation for accessibility: {original_pdf_path}")
            
            # Step 1: Extract content from original PDF
            extracted_content = self._extract_pdf_content(original_pdf_path)
            if not extracted_content:
                result['errors'].append("Failed to extract content from original PDF")
                return result
            
            # Step 2: Create accessible PDF with ReportLab
            success = self._create_accessible_pdf(extracted_content, alt_text_mapping, output_path)
            
            if success:
                result['success'] = True
                result['pages_processed'] = len(extracted_content['pages'])
                result['images_processed'] = sum(len(page['images']) for page in extracted_content['pages'])
                logger.info(f"✅ Successfully recreated accessible PDF: {output_path}")
            else:
                result['errors'].append("Failed to create accessible PDF with ReportLab")
                
        except Exception as e:
            error_msg = f"Error during PDF recreation: {str(e)}"
            logger.error(error_msg)
            result['errors'].append(error_msg)
        
        finally:
            self._cleanup_temp_files()
            
        return result
    
    def _extract_pdf_content(self, pdf_path: str) -> Optional[Dict[str, Any]]:
        """
        Extract all content from the original PDF for recreation.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Dictionary containing extracted content structure
        """
        try:
            doc = fitz.open(pdf_path)
            
            if doc.needs_pass:
                logger.error(f"PDF is encrypted: {pdf_path}")
                return None
            
            content = {
                'metadata': self._extract_metadata(doc),
                'pages': []
            }
            
            # Extract content from each page
            for page_num in range(doc.page_count):
                page = doc[page_num]
                page_content = self._extract_page_content(doc, page, page_num)
                content['pages'].append(page_content)
            
            doc.close()
            logger.info(f"Extracted content from {len(content['pages'])} pages")
            return content
            
        except Exception as e:
            logger.error(f"Failed to extract PDF content: {e}")
            return None
    
    def _extract_metadata(self, doc: fitz.Document) -> Dict[str, Any]:
        """Extract document metadata."""
        metadata = doc.metadata
        return {
            'title': metadata.get('title', ''),
            'author': metadata.get('author', ''),
            'subject': metadata.get('subject', ''),
            'creator': metadata.get('creator', 'PDF ALT Text Generator'),
            'producer': metadata.get('producer', 'PDF ALT Text Generator with ReportLab'),
            'page_count': doc.page_count
        }
    
    def _extract_page_content(self, doc: fitz.Document, page: fitz.Page, page_num: int) -> Dict[str, Any]:
        """
        Extract content from a single page.
        
        Args:
            doc: PyMuPDF document
            page: PyMuPDF page
            page_num: Page number (0-based)
            
        Returns:
            Dictionary with page content
        """
        page_content = {
            'page_number': page_num + 1,
            'page_size': (page.rect.width, page.rect.height),
            'text_blocks': [],
            'images': []
        }
        
        # Extract text blocks with positioning
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if "lines" in block:  # Text block
                text_content = ""
                bbox = block["bbox"]
                font_info = []
                
                for line in block["lines"]:
                    for span in line["spans"]:
                        text_content += span["text"]
                        font_info.append({
                            'font': span.get("font", "Unknown"),
                            'size': span.get("size", 12),
                            'flags': span.get("flags", 0)
                        })
                    text_content += "\n"
                
                if text_content.strip():
                    page_content['text_blocks'].append({
                        'text': text_content.strip(),
                        'bbox': bbox,
                        'fonts': font_info
                    })
        
        # Extract images with positioning
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            try:
                image_info = self._extract_image_data(doc, page, img, img_index, page_num + 1)
                if image_info:
                    page_content['images'].append(image_info)
            except Exception as e:
                logger.warning(f"Failed to extract image {img_index} from page {page_num + 1}: {e}")
        
        return page_content
    
    def _extract_image_data(self, doc: fitz.Document, page: fitz.Page, img_tuple: tuple, 
                           img_index: int, page_number: int) -> Optional[Dict[str, Any]]:
        """Extract image data and save to temporary file."""
        try:
            xref = img_tuple[0]
            image_data = doc.extract_image(xref)
            img_bytes = image_data["image"]
            
            # Save image to temporary file
            temp_file = tempfile.NamedTemporaryFile(
                suffix=f'.{image_data.get("ext", "png")}', 
                delete=False
            )
            temp_file.write(img_bytes)
            temp_file.close()
            self.temp_files.append(temp_file.name)
            
            # Get image rectangles on the page
            image_rects = page.get_image_rects(img_tuple)
            if image_rects:
                rect = image_rects[0]
                bbox = (rect.x0, rect.y0, rect.width, rect.height)
            else:
                bbox = (0, 0, image_data.get("width", 100), image_data.get("height", 100))
            
            return {
                'image_index': img_index,
                'temp_path': temp_file.name,
                'bbox': bbox,
                'format': image_data.get("ext", "png"),
                'width': image_data.get("width", 0),
                'height': image_data.get("height", 0),
                'key': f"page_{page_number}_image_{img_index}"
            }
            
        except Exception as e:
            logger.error(f"Failed to extract image data: {e}")
            return None
    
    def _create_accessible_pdf(self, content: Dict[str, Any], alt_text_mapping: Dict[str, str], 
                              output_path: str) -> bool:
        """
        Create accessible PDF using ReportLab with extracted content.
        
        Args:
            content: Extracted content from original PDF
            alt_text_mapping: ALT text mapping for images
            output_path: Output file path
            
        Returns:
            True if PDF was created successfully
        """
        try:
            # Create PDF with ReportLab
            doc = SimpleDocTemplate(
                output_path,
                pagesize=letter,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=72,
                title=content['metadata'].get('title', 'Accessible PDF'),
                author=content['metadata'].get('author', ''),
                subject=content['metadata'].get('subject', ''),
                creator='PDF ALT Text Generator',
                producer='PDF ALT Text Generator with ReportLab'
            )
            
            # Build the document content
            story = []
            styles = getSampleStyleSheet()
            
            # Process each page
            for page_content in content['pages']:
                logger.info(f"Processing page {page_content['page_number']}")
                
                # Add page break for pages after the first
                if page_content['page_number'] > 1:
                    story.append(Spacer(1, inch))  # Page break equivalent
                
                # Add text blocks
                for text_block in page_content['text_blocks']:
                    para = Paragraph(text_block['text'], styles['Normal'])
                    story.append(para)
                    story.append(Spacer(1, 6))  # Small space between blocks
                
                # Add images with ALT text
                for image_info in page_content['images']:
                    image_key = image_info['key']
                    alt_text = alt_text_mapping.get(image_key, f"Image on page {page_content['page_number']}")
                    
                    # Create accessible image
                    try:
                        # Scale image to fit page
                        img_width = min(image_info['width'], 400)  # Max width
                        img_height = image_info['height'] * (img_width / image_info['width'])
                        
                        accessible_img = AccessibleImage(
                            image_info['temp_path'],
                            img_width,
                            img_height,
                            alt_text
                        )
                        
                        story.append(accessible_img)
                        story.append(Spacer(1, 12))  # Space after image
                        
                        logger.debug(f"Added accessible image: {alt_text[:30]}...")
                        
                    except Exception as e:
                        logger.warning(f"Could not add image {image_key}: {e}")
            
            # Build the PDF
            doc.build(story)
            logger.info(f"Created accessible PDF with {len(content['pages'])} pages")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create accessible PDF: {e}")
            return False
    
    def _cleanup_temp_files(self):
        """Clean up temporary image files."""
        for temp_file in self.temp_files:
            try:
                Path(temp_file).unlink(missing_ok=True)
            except Exception:
                pass  # Ignore cleanup errors
        self.temp_files.clear()


def main():
    """Test the PDF accessibility recreator."""
    import sys
    import json
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) not in [3, 4]:
        print("Usage: python pdf_accessibility_recreator.py <pdf_file> <alt_mapping_json> [output_file]")
        print("\nalt_mapping_json format:")
        print('{"page_1_image_0": "Description of first image", "page_2_image_0": "Description of second image"}')
        print("\nThis will recreate the PDF with proper accessibility structure.")
        return
    
    pdf_path = sys.argv[1]
    mapping_file = sys.argv[2]
    output_path = sys.argv[3] if len(sys.argv) == 4 else f"accessible_{Path(pdf_path).name}"
    
    try:
        print("PDF Accessibility Recreator Test")
        print("=" * 50)
        print(f"Input PDF: {pdf_path}")
        print(f"ALT mapping: {mapping_file}")
        print(f"Output PDF: {output_path}")
        print()
        
        # Load ALT text mapping
        with open(mapping_file, 'r', encoding='utf-8') as f:
            alt_text_mapping = json.load(f)
        
        print(f"Loaded {len(alt_text_mapping)} ALT text mappings")
        
        # Recreate PDF with accessibility
        recreator = PDFAccessibilityRecreator()
        result = recreator.recreate_accessible_pdf(pdf_path, alt_text_mapping, output_path)
        
        # Display results
        print("Recreation Results:")
        print(f"  Success: {result['success']}")
        print(f"  Pages processed: {result['pages_processed']}")
        print(f"  Images processed: {result['images_processed']}")
        
        if result['errors']:
            print(f"  Errors: {len(result['errors'])}")
            for error in result['errors']:
                print(f"    - {error}")
        
        if result['success']:
            print(f"\n✅ Accessible PDF created successfully: {output_path}")
        else:
            print(f"\n❌ PDF recreation failed!")
            return 1
        
    except FileNotFoundError as e:
        print(f"Error: File not found - {e}")
        return 1
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in mapping file - {e}")
        return 1
    except Exception as e:
        logger.error(f"Recreation failed: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())