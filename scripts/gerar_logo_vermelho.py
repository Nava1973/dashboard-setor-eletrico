"""Re-colore o PNG branco horizontal pra vermelho BBI (#CC092F),
preservando o canal alpha intacto. Sobrescreve bbi_horizontal_red.png.
Gera também preview com fundo cream Bauhaus pra validação visual."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
LOGOS = ROOT / "assets" / "logos"

VERMELHO_BBI = (204, 9, 47)  # #CC092F
CREAM_BAUHAUS = (245, 241, 232, 255)  # #F5F1E8

# 1. Re-colorir branco → vermelho BBI, preservando alpha
src = LOGOS / "bbi_horizontal_white.png"
dst = LOGOS / "bbi_horizontal_red.png"
print(f"lendo {src}")
img = Image.open(src).convert("RGBA")
arr = np.array(img)
print(f"dimensões: {img.size}")

visible = arr[:, :, 3] > 0
arr[visible, 0] = VERMELHO_BBI[0]
arr[visible, 1] = VERMELHO_BBI[1]
arr[visible, 2] = VERMELHO_BBI[2]
# alpha preservado intacto

out = Image.fromarray(arr, "RGBA")
out.save(dst, "PNG", optimize=True)
size_kb = dst.stat().st_size / 1024
print(f"salvo: {dst} — {out.size}, {size_kb:.1f} KB")

# 2. Preview vermelho sobre cream Bauhaus
preview_dst = LOGOS / "_preview_red_on_cream.png"
pad = 80
canvas = Image.new("RGBA", (out.width + pad * 2, out.height + pad * 2), CREAM_BAUHAUS)
canvas.paste(out, (pad, pad), out)
canvas.save(preview_dst, "PNG", optimize=True)
print(f"preview salvo: {preview_dst} ({canvas.size})")
