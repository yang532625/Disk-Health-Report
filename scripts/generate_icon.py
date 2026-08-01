"""Generate application icon for Disk Health Report."""
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow required: pip install pillow")
    raise

OUT = Path(__file__).resolve().parent.parent / "packaging" / "assets" / "app.ico"
OUT.parent.mkdir(parents=True, exist_ok=True)

size = 256
img = Image.new("RGBA", (size, size), (0, 86, 179, 255))
draw = ImageDraw.Draw(img)

# Outer disk
draw.ellipse([32, 32, 224, 224], fill=(255, 255, 255, 255), outline=(200, 220, 240, 255), width=4)
# Inner hub
draw.ellipse([96, 96, 160, 160], fill=(0, 86, 179, 255))
# Check mark (health)
draw.line([(72, 128), (108, 164), (184, 72)], fill=(40, 167, 69, 255), width=14)

img.save(OUT, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print(f"Icon saved: {OUT}")
