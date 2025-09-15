# approval/docx_alt_review.py
from pathlib import Path
from datetime import datetime
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def set_cell_margins(cell, left=None, right=None, top=None, bottom=None):
    """Set cell margins in twips (1/20 pt). 180 ≈ 0.125"."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for side, val in (('top', top), ('start', left), ('bottom', bottom), ('end', right)):
        if val is None:
            continue
        el = OxmlElement(f'w:{side}')
        el.set(qn('w:w'), str(val))
        el.set(qn('w:type'), 'dxa')
        tcMar.append(el)
    tcPr.append(tcMar)

def force_portrait_with_sane_geometry(doc):
    """Force portrait and set sane page geometry."""
    section = doc.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.left_margin = Inches(0.5)
    section.right_margin = Inches(0.5) 
    section.top_margin = Inches(0.5)
    section.bottom_margin = Inches(0.5)

def collect_original_alts(pptx_path) -> dict:
    """Collect original ALT text from PPTX before injection."""
    from pptx import Presentation
    try:
        prs = Presentation(pptx_path)
        cache = {}
        for s_idx, slide in enumerate(prs.slides):
            for shape in slide.shapes:
                try:
                    # Create same stable key as used in processing
                    if hasattr(shape, 'shape_id'):
                        shape_id = shape.shape_id
                    else:
                        continue  # Skip shapes without stable ID
                    
                    # Try to get image hash for complete key
                    image_hash = ""
                    try:
                        if hasattr(shape, 'image') and hasattr(shape.image, 'blob'):
                            from hashlib import md5
                            image_hash = md5(shape.image.blob).hexdigest()[:8]
                    except:
                        pass
                    
                    key = f"slide_{s_idx}_shapeid_{shape_id}_hash_{image_hash}"
                    
                    # Get ALT text - try alternative_text first, then title
                    alt = ""
                    try:
                        alt = getattr(shape, "alternative_text", "") or ""
                    except:
                        alt = ""
                    if not alt:
                        try:
                            alt = getattr(shape, "title", "") or ""
                        except:
                            pass
                    
                    cache[key] = alt.strip()
                except Exception:
                    continue
        return cache
    except Exception as e:
        print(f"Warning: Could not collect original ALT text: {e}")
        return {}

def force_print_layout(doc, zoom_percent=110):
    """Force Word to open in Print Layout mode with specified zoom."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    
    settings = doc._part.document.settings._element
    view = settings.find(qn('w:view'))
    if view is None:
        view = OxmlElement('w:view')
        settings.append(view)
    view.set(qn('w:val'), 'print')
    
    zoom = settings.find(qn('w:zoom'))
    if zoom is None:
        zoom = OxmlElement('w:zoom')
        settings.append(zoom)
    zoom.set(qn('w:percent'), str(zoom_percent))

def repeat_header_on_each_page(row):
    """Make table header row repeat on every page."""
    tr = row._tr
    trPr = tr.get_or_add_trPr()
    tblHeader = OxmlElement('w:tblHeader')
    tblHeader.set(qn('w:val'), "true")
    trPr.append(tblHeader)

def set_row_no_break(row):
    """Prevent row from breaking across pages."""
    trPr = row._tr.get_or_add_trPr()
    cantSplit = OxmlElement('w:cantSplit')
    trPr.append(cantSplit)

def shade_cell(cell, hex_color):
    """Apply background shading to a cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)

def set_font_properties(run, size=11, bold=False, italic=False, color=None):
    """Set font properties for a run."""
    run.font.name = 'Calibri'
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = RGBColor.from_string(color)

def add_header_footer(doc, title, input_filename):
    """Add professional header and footer."""
    for section in doc.sections:
        # Header
        header = section.header
        header_para = header.paragraphs[0]
        header_para.clear()
        
        # Left-aligned title
        title_run = header_para.add_run(f"{title} – ALT Review")
        set_font_properties(title_run, size=11, bold=True)
        
        # Right-aligned date/time
        header_para.add_run('\t' * 6)  # Tab to right side for portrait
        date_run = header_para.add_run(datetime.now().strftime("%Y-%m-%d %H:%M"))
        set_font_properties(date_run, size=10)
        
        header_para.paragraph_format.tab_stops.add_tab_stop(Inches(6.5))  # Portrait tab stop
        
        # Footer
        footer = section.footer
        footer_para = footer.paragraphs[0]
        footer_para.clear()
        
        # Left-aligned filename
        filename_run = footer_para.add_run(input_filename)
        set_font_properties(filename_run, size=10, color="666666")
        
        # Right-aligned page numbers
        footer_para.add_run('\t' * 6)
        page_run = footer_para.add_run("Page ")
        set_font_properties(page_run, size=10, color="666666")
        
        footer_para.paragraph_format.tab_stops.add_tab_stop(Inches(6.5))  # Portrait tab stop

# ALT text skip set from injector preserve mode
SKIP_ALT_VALUES = {"", "undefined", "(None)", "N/A", "Not reviewed", "n/a"}

def get_current_alt_from_shape(shape):
    """Extract current ALT text from shape's cNvPr element."""
    try:
        if hasattr(shape, '_element'):
            # Look for cNvPr in picture elements
            cNvPr_elements = shape._element.xpath('.//pic:cNvPr', namespaces={
                'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture'
            })
            if cNvPr_elements:
                cNvPr = cNvPr_elements[0]
                # descr is the actual ALT text; title is a fallback
                alt_text = cNvPr.get('descr') or cNvPr.get('title') or ''
                return alt_text.strip()
    except Exception:
        pass
    return ""

def process_alt_for_report(current_alt, generate_alt_func=None):
    """
    Process ALT text for report based on current ALT and skip logic.
    
    Args:
        current_alt: Current ALT text from shape
        generate_alt_func: Function to generate new ALT text (called only if needed)
    
    Returns:
        Tuple of (current_alt_display, suggested_alt_display)
    """
    current_cleaned = (current_alt or "").strip()
    has_current = current_cleaned and current_cleaned not in SKIP_ALT_VALUES
    
    if has_current:
        # Current ALT exists and is valid - don't generate, just mirror
        return current_cleaned, current_cleaned
    else:
        # Current ALT is missing or in skip set - generate suggested
        suggested = ""
        if generate_alt_func:
            try:
                suggested = generate_alt_func() or ""
            except Exception:
                suggested = ""
        
        return "[No ALT text]", normalize_alt_text(suggested)

def normalize_alt_text(text):
    """Ensure ALT text ends with proper punctuation."""
    if not text or not text.strip():
        return text
    text = text.strip()
    if text and text[-1] not in ('.', '!', '?'):
        text += '.'
    return text

def pick_alts_for_report(key, final_alt_map, existing_alt_from_ppt):
    """
    - If the PPT had ALT already, use it for BOTH Current and Suggested
      (so they match exactly).
    - If the PPT had none, Suggested = generated canonical ALT; Current = "".
    """
    existing = (existing_alt_from_ppt or "").strip()
    generated = (final_alt_map.get(key) or "").strip()

    if existing:
        return existing, existing  # Current, Suggested
    return "", generated

def generate_alt_review_doc(processed_images, lecture_title: str, output_path: str, original_pptx_path: str = None, final_alt_map: dict = None):
    """
    Generate a professional matrix-style accessibility review document.
    
    processed_images: list[dict] with keys:
      image_path, slide_number, image_number, current_alt, suggested_alt,
      is_decorative, image_key, (optional) slide_title, slide_notes, status_info
    """
    doc = Document()
    
    # Force portrait orientation with sane geometry and print layout
    force_portrait_with_sane_geometry(doc)
    force_print_layout(doc, zoom_percent=110)
    
    # Collect original ALT text if we have the source PPTX path
    original_alt_cache = {}
    if original_pptx_path:
        original_alt_cache = collect_original_alts(original_pptx_path)
    
    # Set default style to Calibri 11pt
    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(11)
    
    # Add header and footer
    input_filename = Path(output_path).stem.replace('_ALT_Review', '')
    add_header_footer(doc, lecture_title, input_filename)
    
    # Title
    title_para = doc.add_paragraph()
    title_run = title_para.add_run(f"{lecture_title} – Accessibility ALT Review")
    set_font_properties(title_run, size=16, bold=True)
    title_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    title_para.paragraph_format.space_after = Pt(12)
    
    # Intro paragraph
    intro_para = doc.add_paragraph()
    intro_run = intro_para.add_run(
        "Review Suggested ALT, check Decorative as needed, and add Review Notes. "
        "Leave Approved ALT blank if Decorative is checked."
    )
    set_font_properties(intro_run, size=11)
    intro_para.paragraph_format.space_after = Pt(8)
    
    # Process ALT text for all images with corrected logic
    processed_alt_data = []
    identical_count = 0
    missing_current = 0
    
    for item in processed_images:
        # Get the image key and look up original ALT text
        image_key = item.get('image_key', '')
        original_alt = original_alt_cache.get(image_key, '').strip() if image_key else ''
        
        # Use canonical final_alt_map if provided, otherwise fall back to processed_images
        if final_alt_map:
            current_alt, suggested_alt = pick_alts_for_report(image_key, final_alt_map, original_alt)
        else:
            # Fallback to old logic for backward compatibility
            generated_alt = item.get('suggested_alt', '').strip()
            current_alt = original_alt if original_alt else ""
            suggested_alt = original_alt if original_alt else (generated_alt if generated_alt else "")
        
        # For display
        current_display = current_alt if current_alt else "[No ALT text]"
        suggested_display = suggested_alt if suggested_alt else "[No ALT text]"
        
        # Track statistics
        if current_display == "[No ALT text]":
            missing_current += 1
        if (current_display != "[No ALT text]" and 
            suggested_display != "[No ALT text]" and 
            current_display == suggested_display):
            identical_count += 1
            
        # Store processed data for table building
        processed_item = item.copy()
        processed_item['current_alt_display'] = current_display
        processed_item['suggested_alt_display'] = suggested_display
        processed_alt_data.append(processed_item)
    
    total_images = len(processed_images)
    
    summary_para = doc.add_paragraph()
    summary_run = summary_para.add_run(
        f"Total images: {total_images}   •   "
        f"Identical current/suggested: {identical_count}   •   "
        f"Missing current ALT: {missing_current}"
    )
    set_font_properties(summary_run, size=10, color="666666")
    summary_para.paragraph_format.space_after = Pt(12)
    
    # Fixed table with optimized columns for portrait layout
    table = doc.add_table(rows=1, cols=6)
    table.autofit = False  # Critical: let our fixed widths win
    
    # Columns: [Slide / Img, Thumbnail, Current ALT, Suggested ALT, Status, Decorative]  
    # 8.5" page - 1.0" margins = 7.5" usable width
    col_widths = [Inches(0.80), Inches(1.30), Inches(1.90), Inches(1.90), Inches(1.00), Inches(0.60)]
    for i, w in enumerate(col_widths):
        table.columns[i].width = w
        for cell in table.columns[i].cells:
            cell.width = w
    
    hdr = table.rows[0].cells
    header_names = ["Slide / Img", "Thumbnail", "Current ALT Text", "Suggested ALT Text", "Status", "Decorative"]
    
    for i, name in enumerate(header_names):
        hdr[i].text = name
        # Header formatting to prevent letter-wrapping
        p = hdr[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        hdr[i].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p.paragraph_format.keep_together = True
        p.paragraph_format.keep_with_next = True
        
        # Header styling
        for r in p.runs:
            set_font_properties(r, size=9.5, bold=True, color="FFFFFF")
        
        # Dark gray header background
        shade_cell(hdr[i], "4F4F4F")
    
    # Make header repeat on every page
    repeat_header_on_each_page(table.rows[0])
    
    # Data rows with improved cell formatting
    for row_idx, item in enumerate(processed_alt_data):
        row = table.add_row()
        set_row_no_break(row)
        cells = row.cells
        
        # Apply zebra striping (light gray on even rows)
        if row_idx % 2 == 0:
            for cell in cells:
                shade_cell(cell, "F7F7F7")
        
        # Set all cell widths and basic formatting
        for i, cell in enumerate(cells):
            cell.width = col_widths[i]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP  # Top-left align body cells
        
        # Column 0: Slide / Img (combined)
        cell = cells[0]
        para = cell.paragraphs[0]
        para.clear()
        slide_num = item.get('slide_number', '')
        image_num = item.get('image_number', '')
        run = para.add_run(f"S{slide_num} / I{image_num}")
        set_font_properties(run, size=11, bold=True)
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.0
        
        # Column 1: Thumbnail with improved sizing and right padding
        cell = cells[1]
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER  # Center thumbnail vertically
        set_cell_margins(cell, right=180)  # ~0.125" gutter on the right
        para = cell.paragraphs[0]
        para.clear()
        
        thumb_path = item.get('image_path')
        if thumb_path and Path(thumb_path).exists():
            try:
                # Add thumbnail with constrained sizing
                run = para.add_run()
                pic = run.add_picture(thumb_path, width=Inches(1.40))  # a hair smaller than the column
                    
                # Add ALT text to picture for accessibility
                pic._inline.graphic.graphicData.pic.nvPicPr.cNvPr.set('descr', 
                    f"Thumbnail of slide {item.get('slide_number', '')} image {item.get('image_number', '')}")
            except Exception:
                run = para.add_run("(thumbnail unavailable)")
                set_font_properties(run, size=10, italic=True, color="999999")
        else:
            run = para.add_run("(no thumbnail)")
            set_font_properties(run, size=10, italic=True, color="999999")
        
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.0
        
        # Column 2: Current ALT Text (using processed data)
        cell = cells[2]
        para = cell.paragraphs[0]
        para.clear()
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT  # Top-left align
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.0
        
        current_alt_display = item.get('current_alt_display', '[No ALT text]')
        
        if current_alt_display == "[No ALT text]":
            run = para.add_run(current_alt_display)
            set_font_properties(run, size=10.5, color="999999")
            # Highlight missing current ALT with yellow background
            shade_cell(cell, "FFF2CC")
        else:
            run = para.add_run(current_alt_display)
            set_font_properties(run, size=10.5)
        
        # Column 3: Suggested ALT Text (using processed data)
        cell = cells[3]
        para = cell.paragraphs[0]
        para.clear()
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT  # Top-left align
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.0
        
        suggested_alt_display = item.get('suggested_alt_display', '[No suggestion]')
        
        if not suggested_alt_display or suggested_alt_display == "[No suggestion]":
            run = para.add_run("[No suggestion]")
            set_font_properties(run, size=10.5, color="999999")
        else:
            run = para.add_run(suggested_alt_display)
            set_font_properties(run, size=10.5)
            
            # Highlight identical current/suggested with green background
            if (current_alt_display != "[No ALT text]" and 
                current_alt_display == suggested_alt_display):
                shade_cell(cell, "E2F0D9")
        
        # Column 4: Status information
        cell = cells[4]
        para = cell.paragraphs[0]
        para.clear()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.0
        
        # Get status information from fallback policies
        status_info = item.get('status_info', {})
        status_display = status_info.get('status', 'Generated')
        
        # Import fallback policies to get display helper
        try:
            from fallback_policies import get_review_status_display
            status_text = get_review_status_display(status_info)
        except ImportError:
            # Fallback display logic
            if status_display == 'generated':
                status_text = 'Generated'
            elif status_display == 'preserved':
                status_text = 'Preserved'
            elif status_display.startswith('NEEDS ALT'):
                status_text = 'Needs ALT'
            elif status_display.startswith('AUTO-LOWCONF'):
                status_text = 'Low Confidence'
            elif status_display == 'FALLBACK_INJECTED':
                status_text = 'Fallback'
            else:
                status_text = status_display
        
        run = para.add_run(status_text)
        
        # Color code the status
        if 'NEEDS ALT' in status_display or 'needs' in status_text.lower():
            set_font_properties(run, size=9, color="CC0000")  # Red for needs attention
            shade_cell(cell, "FFE6E6")
        elif 'FALLBACK' in status_display or 'fallback' in status_text.lower():
            set_font_properties(run, size=9, color="FF8C00")  # Orange for fallback
            shade_cell(cell, "FFF2E6")
        elif 'LOWCONF' in status_display or 'low confidence' in status_text.lower():
            set_font_properties(run, size=9, color="CC8800")  # Yellow-orange for low confidence
            shade_cell(cell, "FFFAE6")
        elif 'preserved' in status_text.lower():
            set_font_properties(run, size=9, color="0066CC")  # Blue for preserved
        else:
            set_font_properties(run, size=9, color="006600")  # Green for generated
        
        # Column 5: Decorative checkbox (single line, centered)
        cell = cells[5]
        para = cell.paragraphs[0]
        para.clear()
        run = para.add_run("Yes" if item.get('is_decorative', False) else "No")
        set_font_properties(run, size=11)
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.0
    
    # Final portrait enforcement (catches any stray landscape sections)
    force_portrait_with_sane_geometry(doc)
    
    # Save document
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    return output_path