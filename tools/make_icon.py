"""Gera assets/icon.png e assets/icon.ico (ondas sonoras rosa sobre fundo escuro)."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(exist_ok=True)
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((0, 0, S - 1, S - 1), radius=230, fill=(30, 30, 30, 255))
d.rounded_rectangle((24, 24, S - 25, S - 25), radius=210, outline=(58, 58, 61, 255), width=6)
heights = [0.22, 0.42, 0.66, 0.5, 0.78, 0.36, 0.52, 0.2]
bw, gap = 62, 34
total = len(heights) * bw + (len(heights) - 1) * gap
x = (S - total) // 2
for i, h in enumerate(heights):
    bh = int(S * h * 0.82)
    col = (255, 77, 141, 255) if i != 4 else (255, 160, 196, 255)
    d.rounded_rectangle((x, S // 2 - bh // 2, x + bw, S // 2 + bh // 2), radius=bw // 2, fill=col)
    x += bw + gap
img.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
img.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ok")
