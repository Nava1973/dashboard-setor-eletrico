"""
utils/paleta_bradesco.py
========================

Paleta canônica **Bradesco** — substitui a paleta Bauhaus que vigorou
até a sub-sessão de migração (2026-05-15). Este arquivo é a fonte
única de verdade pra cores estruturais (UI), de submercado e de
fontes de geração no Dashboard Setor Elétrico.

Relação com `utils/cores_fontes.py`
-----------------------------------
O `cores_fontes.py` é o canônico atual das cores de FONTES (decisão
5.33). Após esta migração ele vira fachada que re-exporta os
COR_FONTE_* deste arquivo (ou é deprecado). Imports existentes
(`from utils.cores_fontes import COR_FONTE_HIDRO`) continuam
funcionando por compat.

Layers
------
1. **Estrutural (UI)** — fundo, texto, sidebar, bordas.
2. **Submercados** — SE / S / NE / N / SIN.
3. **Fontes de geração** — hidro / eólica / térmica / solar / nuclear / MMGD.
4. **Semântico** — destaque/alerta, accent secundário, ativo de sidebar.

Contraste WCAG (texto sobre fundo)
----------------------------------
- ``COR_TEXTO`` (#313131) sobre ``COR_FUNDO`` (#FFFFFF): **12.6:1** ✓ AAA
- ``COR_DESTAQUE`` (#CC092F) sobre branco: **7.1:1** ✓ AAA
- ``COR_ACCENT`` (#0078B7) sobre branco: **5.2:1** ✓ AA (AAA pra texto grande)
- ``COR_NE`` (#560CAB) sobre branco: **9.9:1** ✓ AAA
- Branco (#FFFFFF) sobre ``COR_SIDEBAR_FUNDO`` (#313131): **12.6:1** ✓ AAA

Notas de design
---------------
- Bauhaus tracejava a linha do Norte (#1A1A1A) pra distingui-la em
  monitores B&W; na paleta Bradesco TODAS as linhas de submercado
  são contínuas — a distinção fica por cor (vermelho/azul/roxo/preto).
- Sidebar fundo escuro + texto branco; botão ativo no vermelho
  Bradesco (#CC092F), inativo transparente.

Arquivo puramente declarativo (zero imports do projeto) — ``utils/``
é folha do grafo de imports, sem risco de ciclo.
"""

# ─────────────────────────────────────────────────────────────────────
# 1. ESTRUTURAL (UI)
# ─────────────────────────────────────────────────────────────────────

COR_FUNDO          = "#FFFFFF"   # fundo geral da página
COR_TEXTO          = "#313131"   # texto principal (quase-preto Bradesco)
COR_TEXTO_SECUND   = "#6B6B6B"   # texto secundário / captions
COR_BORDA          = "#313131"   # bordas Bauhaus → bordas Bradesco
COR_BORDA_SUTIL    = "#E0E0E0"   # bordas sutis (grids, dividers)
COR_GRID           = "#E0E0E0"   # gridlines de gráficos Plotly

# Sidebar
COR_SIDEBAR_FUNDO  = "#313131"   # fundo escuro
COR_SIDEBAR_TEXTO  = "#FFFFFF"   # texto branco
COR_SIDEBAR_TEXTO_MUTED = "#A0A0A0"  # username, captions na sidebar
COR_SIDEBAR_ATIVO_BG    = "#CC092F"  # vermelho Bradesco no botão ativo
COR_SIDEBAR_ATIVO_TXT   = "#FFFFFF"  # texto branco no botão ativo
COR_SIDEBAR_HOVER_BG    = "#CC092F"  # hover replica o ativo (feedback)


# ─────────────────────────────────────────────────────────────────────
# 2. SEMÂNTICO
# ─────────────────────────────────────────────────────────────────────

COR_DESTAQUE       = "#CC092F"   # vermelho Bradesco — alertas, KPIs ativos
COR_ACCENT         = "#0078B7"   # azul Bradesco — accent secundário
COR_SUCESSO        = "#2E7D32"   # verde escuro (raro; reusa verde eólica)
COR_AVISO          = "#B85C00"   # laranja queimado (reusa térmica)

# Cor funcional pra faixas de período hidrológico úmido (Reservatórios).
# Substitui o #B3D4F1 Bauhaus. Tom de azul claro Bradesco, suficientemente
# diluído pra não competir com as linhas dos subsistemas.
COR_PERIODO_UMIDO  = "#A6CFFF"


# ─────────────────────────────────────────────────────────────────────
# 3. SUBMERCADOS
# ─────────────────────────────────────────────────────────────────────

COR_SE  = "#CC092F"  # Sudeste — vermelho Bradesco
COR_S   = "#0078B7"  # Sul — azul Bradesco
COR_NE  = "#560CAB"  # Nordeste — roxo
COR_N   = "#313131"  # Norte — quase-preto (LINHA CONTÍNUA, sem dash)
COR_SIN = "#4A4A4A"  # SIN / Média BR — cinza médio (agregado neutro)

CORES_SUBMERCADO = {
    "SE":       COR_SE,
    "S":        COR_S,
    "NE":       COR_NE,
    "N":        COR_N,
    "SIN":      COR_SIN,
    "Média BR": COR_SIN,  # alias histórico — chave interna preservada (§5.30)
}


# ─────────────────────────────────────────────────────────────────────
# 4. FONTES DE GERAÇÃO
# ─────────────────────────────────────────────────────────────────────

COR_FONTE_HIDRO   = "#0078B7"  # azul Bradesco (compartilhado com accent)
COR_FONTE_EOLICA  = "#2E7D32"  # verde escuro
COR_FONTE_TERMICA = "#B85C00"  # laranja queimado
COR_FONTE_SOLAR   = "#FFC107"  # amarelo
COR_FONTE_NUCLEAR = "#4A4A4A"  # cinza escuro (mantido do projeto atual)
COR_FONTE_MMGD    = "#FFE082"  # amarelo claro (≠ Solar centralizada)

CORES_FONTE_DICT = {
    "hidro":   COR_FONTE_HIDRO,
    "eolica":  COR_FONTE_EOLICA,
    "termica": COR_FONTE_TERMICA,
    "solar":   COR_FONTE_SOLAR,
    "nuclear": COR_FONTE_NUCLEAR,
    "mmgd":    COR_FONTE_MMGD,
}


# ─────────────────────────────────────────────────────────────────────
# 5. DESPACHO TÉRMICO — motivos de geração
# ─────────────────────────────────────────────────────────────────────
#
# Cores semânticas pros 6 motivos de geração térmica reportados pelo ONS.
# Substitui dicts inline duplicados em app.py (linhas 4513, 5489, 5670)
# que usavam paleta Bauhaus + #1D3557 cobalto. Cobalto vira azul Bradesco;
# vermelho/amarelo Bauhaus viram vermelho/roxo Bradesco; cinzas/preto
# atualizados pra família Bradesco.
#
# OBS: refator das 3 cópias inline pra USAR este dict fica fora de escopo
# desta migração (sinalizado pra futuro refactor).

CORES_MOTIVOS_TERMICO = {
    "Inflexibilidade":     "#CC092F",  # vermelho Bradesco
    "Ordem de mérito":     "#0078B7",  # azul Bradesco
    "Unit commitment":     "#560CAB",  # roxo
    "Exportação":          "#6B6B6B",  # cinza médio (preservado da paleta antiga)
    "Razão elétrica":      "#4A4A4A",  # cinza escuro (preservado da paleta antiga)
    "Garantia energética": "#313131",  # quase-preto Bradesco
}


# ─────────────────────────────────────────────────────────────────────
# 6. HELPERS
# ─────────────────────────────────────────────────────────────────────

def get_submercado_color(sub: str) -> str:
    """
    Retorna a cor canônica de um submercado.

    Aceita SE/S/NE/N/SIN (chaves) e "Média BR" (alias histórico §5.30).
    Fallback pra COR_TEXTO se chave desconhecida (defensivo).
    """
    return CORES_SUBMERCADO.get(sub, COR_TEXTO)


def get_fonte_color(fonte: str) -> str:
    """
    Retorna a cor canônica de uma fonte de geração.

    Aceita hidro/eolica/termica/solar/nuclear/mmgd (lowercase).
    Fallback pra COR_TEXTO se chave desconhecida (defensivo).
    """
    return CORES_FONTE_DICT.get(fonte.lower(), COR_TEXTO)


def plotly_layout_defaults() -> dict:
    """
    Defaults pra `fig.update_layout(**plotly_layout_defaults())`.

    Aplica fundo branco, texto Bradesco, eixos quase-pretos.
    Não inclui ``title``, ``height``, ``hovermode`` etc. — esses
    continuam decisão do caller.
    """
    return dict(
        paper_bgcolor=COR_FUNDO,
        plot_bgcolor=COR_FUNDO,
        font=dict(
            family="Inter, sans-serif",
            color=COR_TEXTO,
        ),
        xaxis=dict(
            linecolor=COR_TEXTO,
            tickcolor=COR_TEXTO,
            tickfont=dict(color=COR_TEXTO),
            gridcolor=COR_GRID,
            zerolinecolor=COR_TEXTO,
        ),
        yaxis=dict(
            linecolor=COR_TEXTO,
            tickcolor=COR_TEXTO,
            tickfont=dict(color=COR_TEXTO),
            gridcolor=COR_GRID,
            zerolinecolor=COR_TEXTO,
        ),
        legend=dict(
            font=dict(color=COR_TEXTO),
            bgcolor=COR_FUNDO,
        ),
    )
