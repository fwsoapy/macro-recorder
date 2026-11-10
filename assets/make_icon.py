"""Draws assets/icon.ico and assets/icon.png (the app, exe and installer icon). Needs Pillow at build time only."""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZE = 1024  # drawn large, then scaled down for each icon size

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((40, 40, SIZE - 40, SIZE - 40), radius=220, fill=(21, 23, 28, 255), outline=(69, 75, 88, 255),
                    width=28)
d.ellipse((190, 190, 640, 640), fill=(242, 102, 107, 255))           # record dot
d.polygon([(560, 470), (560, 860), (880, 665)], fill=(70, 194, 138, 255))  # play triangle
d.polygon([(560, 470), (560, 860), (880, 665)], outline=(21, 23, 28, 255), width=34)

img.resize((512, 512), Image.LANCZOS).save(HERE / "icon.png")
img.save(HERE.parent / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote icon.ico and assets/icon.png")
