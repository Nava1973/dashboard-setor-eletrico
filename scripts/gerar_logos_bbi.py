"""Gera PNGs transparentes a partir dos JPGs originais BBI.

Saída:
  assets/logos/bbi_horizontal_red.png   — partir do vermelho, fundo→transparente
  assets/logos/bbi_horizontal_white.png — partir do preto, fundo→transparente E preto→branco
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "source_logos"
DST = ROOT / "assets" / "logos"
DST.mkdir(parents=True, exist_ok=True)

# Threshold de "branco" — pixels com R,G,B todos > 240 viram alpha=0
WHITE_THRESHOLD = 240
# Threshold de "escuro" — pixels com max(R,G,B) < 128 viram brancos puros
DARK_THRESHOLD = 128


def remove_white_bg(img: Image.Image) -> Image.Image:
    """Converte branco do fundo em alpha=0 com tolerância pra antialiasing."""
    img = img.convert("RGBA")
    arr = np.array(img)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    # Mask: pixel é "branco" se todos os 3 canais estão acima do threshold
    white_mask = (r > WHITE_THRESHOLD) & (g > WHITE_THRESHOLD) & (b > WHITE_THRESHOLD)
    # Pixels brancos puros: alpha=0
    arr[white_mask, 3] = 0
    # Pixels quase-brancos (antialiasing): alpha proporcional ao "quão escuro" é
    # — o canal mais escuro indica a presença de cor; quanto menor, mais opaco
    near_white_mask = ~white_mask & (
        (r > 200) & (g > 200) & (b > 200)
    )
    if near_white_mask.any():
        # min channel value — quanto menor, mais cor presente
        min_ch = np.minimum(np.minimum(r, g), b)
        # mapeia 200..255 → alpha 255..0 (linear)
        alpha = np.clip((255 - min_ch) * (255.0 / 55.0), 0, 255).astype(np.uint8)
        # aplica só nos pixels near-white
        arr[near_white_mask, 3] = alpha[near_white_mask]
    return Image.fromarray(arr, "RGBA")


def invert_dark_to_white(img: Image.Image) -> Image.Image:
    """Pixels não-transparentes que são escuros → brancos puros, preservando alpha."""
    arr = np.array(img.convert("RGBA"))
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    # Considera "escuro" qualquer pixel cuja luminosidade média seja baixa
    # (cobre preto puro #000000 e tons cinzas escuros do antialiasing).
    # Trabalha com TODOS os pixels visíveis (alpha > 0), preservando a opacidade.
    visible = a > 0
    # Inverte: pixels visíveis viram (255-r, 255-g, 255-b)
    # Como o logo é preto sobre branco já transparente, o preto puro (0,0,0)
    # vira (255,255,255) — branco puro. Tons cinzas (antialiasing das bordas)
    # viram tons claros, mas o canal alpha já carrega a borda suave do
    # remove_white_bg, então invertemos APENAS pra branco puro mesmo.
    arr[visible, 0] = 255
    arr[visible, 1] = 255
    arr[visible, 2] = 255
    # alpha preservado intacto
    return Image.fromarray(arr, "RGBA")


def processar_vermelho():
    src = SRC / "BBI_Logo_2.jpg"
    print(f"[red] lendo {src}")
    img = Image.open(src)
    print(f"[red] dimensões originais: {img.size}, modo: {img.mode}")
    out = remove_white_bg(img)
    dst = DST / "bbi_horizontal_red.png"
    out.save(dst, "PNG", optimize=True)
    size_kb = dst.stat().st_size / 1024
    print(f"[red] salvo: {dst} — {out.size}, {size_kb:.1f} KB")


def processar_branco():
    src = SRC / "Bradesco_BBIS_RGB_BLACK_1.jpg"
    print(f"[white] lendo {src}")
    img = Image.open(src)
    print(f"[white] dimensões originais: {img.size}, modo: {img.mode}")
    img_no_bg = remove_white_bg(img)
    img_inverted = invert_dark_to_white(img_no_bg)
    dst = DST / "bbi_horizontal_white.png"
    img_inverted.save(dst, "PNG", optimize=True)
    size_kb = dst.stat().st_size / 1024
    print(f"[white] salvo: {dst} — {img_inverted.size}, {size_kb:.1f} KB")


if __name__ == "__main__":
    processar_vermelho()
    processar_branco()
    print("\nOK.")
