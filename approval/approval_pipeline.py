# approval/approval_pipeline.py
from pathlib import Path
from dataclasses import dataclass
import tempfile
import sys
import os

# Ensure we can import from parent directories
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

from pptx_processor import PPTXAccessibilityProcessor

@dataclass
class ApprovalOptions:
    include_context: bool = True
    image_max_width_px: int = 600  # for thumbnails if you generate any
    review_suffix: str = "_ALT_Review"
    
    @classmethod
    def from_config(cls, config_manager):
        """Create ApprovalOptions from config manager."""
        approval_config = config_manager.config.get('approval_docs', {})
        return cls(
            include_context=approval_config.get('include_context', True),
            image_max_width_px=approval_config.get('image_max_width_px', 600),
            review_suffix=approval_config.get('review_suffix', '_ALT_Review')
        )

def create_thumbnail(image_data: bytes, max_width: int = 600) -> str:
    """
    Create a thumbnail from image data and return the path to temporary file.
    Returns path to thumbnail file.
    """
    try:
        from PIL import Image
        import io
        
        # Open image from bytes
        with io.BytesIO(image_data) as img_buffer:
            img = Image.open(img_buffer)
            
            # Calculate thumbnail size maintaining aspect ratio
            if img.width > max_width:
                aspect_ratio = img.height / img.width
                new_width = max_width
                new_height = int(new_width * aspect_ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Convert to RGB if necessary (for JPEG compatibility)
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'RGBA':
                    rgb_img.paste(img, mask=img.split()[-1])
                else:
                    rgb_img.paste(img)
                img = rgb_img
            
            # Save to temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png', prefix='thumb_')
            img.save(temp_file.name, 'PNG')
            return temp_file.name
            
    except Exception as e:
        print(f"Warning: Could not create thumbnail: {e}")
        return None

def build_processed_images(pptx_path: str, cfg, generator, include_context=True):
    """
    Returns list[dict] shaped for generate_alt_review_doc.
    Uses current pptx_processor to iterate images and current unified_alt_generator for proposals.
    """
    from pptx_processor import PPTXAccessibilityProcessor
    
    # Create processor instance
    processor = PPTXAccessibilityProcessor(cfg)
    
    # Extract images using the existing processor
    presentation, image_infos = processor._extract_images_from_pptx(pptx_path)
    
    items = []
    for idx, img_info in enumerate(image_infos):
        # Generate ALT text proposal using current generator
        try:
            # Create a temporary file for the image data
            temp_image = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_image.write(img_info.image_data)
            temp_image.close()
            
            # Generate ALT text
            proposal = generator.generate_alt_text(temp_image.name)
            
            # Clean up temp file
            os.unlink(temp_image.name)
            
        except Exception as e:
            print(f"Warning: Could not generate ALT text for image {idx}: {e}")
            proposal = "[Generation failed]"
        
        # Create thumbnail
        thumbnail_path = create_thumbnail(img_info.image_data) if img_info.image_data else None
        
        # Get slide context from the presentation
        slide_title = ""
        slide_notes = ""
        
        if include_context and img_info.slide_idx < len(presentation.slides):
            slide = presentation.slides[img_info.slide_idx]
            
            # Extract slide title (usually the first text box)
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_title = shape.text.strip()
                    break
            
            # Extract slide notes
            if hasattr(slide, 'notes_slide') and slide.notes_slide:
                notes_text_frame = slide.notes_slide.notes_text_frame
                if notes_text_frame and hasattr(notes_text_frame, 'text'):
                    slide_notes = notes_text_frame.text.strip()
        
        # Get existing alt text from shape
        existing_alt = ""
        if hasattr(img_info.shape, 'element'):
            # Look for existing alt text in the shape
            try:
                pic_elements = img_info.shape.element.xpath('.//pic:cNvPr', namespaces={
                    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture'
                })
                if pic_elements:
                    existing_alt = pic_elements[0].get('descr', '')
            except Exception:
                pass
        
        items.append({
            "image_path": thumbnail_path,
            "slide_number": img_info.slide_idx + 1,
            "image_number": idx + 1,
            "current_alt": existing_alt or "[No ALT text]",
            "suggested_alt": proposal,
            "is_decorative": False,
            "image_key": img_info.image_key,
            "slide_title": slide_title if include_context else None,
            "slide_notes": slide_notes if include_context else None,
        })
    
    return items

def make_review_doc(pptx_path: str, out_dir: str, cfg, generator, opts: ApprovalOptions, final_alt_map: dict = None):
    processed = build_processed_images(pptx_path, cfg, generator, include_context=opts.include_context)
    from approval.docx_alt_review import generate_alt_review_doc
    base = Path(pptx_path).stem
    out = str(Path(out_dir) / f"{base}{opts.review_suffix}.docx")
    return generate_alt_review_doc(processed, lecture_title=base, output_path=out, original_pptx_path=pptx_path, final_alt_map=final_alt_map)