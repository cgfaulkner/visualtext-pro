#!/usr/bin/env python3
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "shared"))

from config_manager import ConfigManager
from unified_alt_generator import FlexibleAltGenerator

config_manager = ConfigManager()
alt_generator = FlexibleAltGenerator(config_manager)

# Test the exact prompt from our test
line_prompt = """Slide context: Performance Dashboard...

Shape: A connector sized 436x37 pixels located in the lower area of the slide

Create appropriate ALT text for this visual element considering the slide context. If it appears decorative, respond with 'decorative [element type]':"""

print("Testing line prompt:")
print(f"Prompt:\n{line_prompt}\n")

# Add debug logging
import logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

result = alt_generator._create_shape_fallback_from_prompt(line_prompt)
print(f"Result: {result}")

# Let's also debug the parsing manually
lines = line_prompt.split('\n')
for line in lines:
    if line.strip().lower().startswith('shape:'):
        shape_info = line.strip()[6:].strip()  # Remove "Shape:" prefix
        print(f"Extracted shape_info: '{shape_info}'")
        
        if " a " in shape_info.lower():
            parts = shape_info.lower().split(" a ", 1)
            if len(parts) > 1:
                type_part = parts[1].split()[0]
                print(f"Extracted type_part: '{type_part}'")
                
                is_line_type = type_part in ["connector", "line"]
                print(f"Is line type: {is_line_type}")
                
                # Check dimensions
                import re
                dimension_pattern = r'(\d+)x(\d+)\s*pixels?'
                match = re.search(dimension_pattern, shape_info, re.IGNORECASE)
                if match:
                    width, height = match.groups()
                    print(f"Dimensions: {width}x{height}")
                    
                    if is_line_type:
                        width_px = int(width)
                        height_px = int(height)
                        print(f"Width: {width_px}, Height: {height_px}, Ratio: {width_px/height_px:.1f}")
                        if width_px > height_px * 3:
                            print("Should be horizontal line")
        break