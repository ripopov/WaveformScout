"""Color utilities for generating distinct palettes for overlapped rendering."""

import colorsys
from typing import List


def generate_rainbow_colors(count: int) -> List[str]:
    """Generate a rainbow color palette with distinct, evenly distributed colors.
    
    Args:
        count: Number of colors to generate
        
    Returns:
        List of hex color strings (e.g., ['#ff0000', '#00ff00', ...])
    """
    if count <= 0:
        return []
    
    if count == 1:
        return ['#ff0000']  # Red for single signal
    
    colors = []
    for i in range(count):
        # Calculate hue evenly distributed around the color wheel
        hue = i / count
        # Use high saturation and value for vibrant, visible colors
        saturation = 0.8
        value = 0.9
        
        # Convert HSV to RGB
        r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
        
        # Convert to hex string
        hex_color = f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
        colors.append(hex_color)
    
    return colors


def generate_contrasting_colors(count: int) -> List[str]:
    """Generate contrasting colors optimized for visibility on different backgrounds.
    
    Args:
        count: Number of colors to generate
        
    Returns:
        List of hex color strings with good contrast properties
    """
    if count <= 0:
        return []
    
    # Predefined high-contrast colors for common cases
    predefined = [
        '#ff0000',  # Red
        '#00ff00',  # Green  
        '#0000ff',  # Blue
        '#ffff00',  # Yellow
        '#ff00ff',  # Magenta
        '#00ffff',  # Cyan
        '#ff8000',  # Orange
        '#8000ff',  # Purple
        '#80ff00',  # Lime
        '#ff0080',  # Pink
    ]
    
    if count <= len(predefined):
        return predefined[:count]
    
    # For larger counts, fall back to rainbow generation
    return generate_rainbow_colors(count)