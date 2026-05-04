"""Cropa as margens transparentes do bbi_horizontal_white.png.

O JPG fonte original (Bradesco_BBIS_RGB_BLACK_1.jpg) tem ~5.5% de margem
branca lateral e ~20.7% de margem branca vertical, que viraram transparente
após o remove_white_bg do gerar_logos_bbi.py. Essa margem transparente
desloca o conteúdo visual em relação ao bounding box do PNG, prejudicando
o alinhamento do logo na sidebar (logo aparenta deslocado vs. texto).

Este script cropa pro tight bounding box do conteúdo, mantendo o aspect
ratio correto do logo visível. Sobrescreve o arquivo. Idempotente.

NÃO TOCAR no bbi_horizontal_red.png (já está em uso na tela de login com
proporção que combina com o título — qualquer ajuste no aspect ratio
desse arquivo regrediria o layout do login).
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "assets" / "logos" / "bbi_horizontal_white.png"

img = Image.open(PATH).convert("RGBA")
arr = np.array(img)
alpha = arr[:, :, 3]

non_t_cols = np.any(alpha > 0, axis=0)
non_t_rows = np.any(alpha > 0, axis=1)
left = int(np.argmax(non_t_cols))
right = arr.shape[1] - int(np.argmax(non_t_cols[::-1]))
top = int(np.argmax(non_t_rows))
bottom = arr.shape[0] - int(np.argmax(non_t_rows[::-1]))

print(f"Original: {img.size}, content bbox ({left},{top}) -> ({right},{bottom})")

cropped = img.crop((left, top, right, bottom))
cropped.save(PATH, "PNG", optimize=True)
size_kb = PATH.stat().st_size / 1024
print(f"Cropped to {cropped.size}, {size_kb:.1f} KB")
