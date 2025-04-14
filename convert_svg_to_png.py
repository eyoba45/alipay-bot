import os
import cairosvg

# Convert SVG to PNG
def convert_svg_to_png(svg_path, png_path):
    """Convert SVG file to PNG using cairosvg"""
    try:
        cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=512, output_height=512)
        print(f"Successfully converted {svg_path} to {png_path}")
        return True
    except Exception as e:
        print(f"Error converting SVG to PNG: {e}")
        return False

# Convert our avatar
svg_path = "avatars/selam_avatar.svg"
png_path = "avatars/selam_avatar.png"

if os.path.exists(svg_path):
    convert_svg_to_png(svg_path, png_path)
else:
    print(f"SVG file not found: {svg_path}")
