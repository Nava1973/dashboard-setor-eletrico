"""Gera preview temporário do logo branco sobre fundo preto Bauhaus
pra permitir validação visual no chat. Arquivo NÃO faz parte do app."""
import sys
from pathlib import Path
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
src = ROOT / "assets" / "logos" / "bbi_horizontal_white.png"
dst = ROOT / "assets" / "logos" / "_preview_white_on_black.png"

logo = Image.open(src).convert("RGBA")
# Cria canvas preto Bauhaus #1A1A1A com padding
pad = 80
canvas = Image.new(
    "RGBA",
    (logo.width + pad * 2, logo.height + pad * 2),
    (26, 26, 26, 255),
)
canvas.paste(logo, (pad, pad), logo)
canvas.save(dst, "PNG", optimize=True)
print(f"preview salvo em {dst} ({canvas.size})")
