"""
validar_casamento_excel_ons.py
==============================

Script de validação do casamento entre o Excel de proprietários e os
arquivos de curtailment do ONS.

Uso:
    cd dashboard-setor-eletrico/
    python validar_casamento_excel_ons.py

O script:
    1. Carrega o Excel (Solar + Eólica)
    2. Baixa os 3 últimos meses de dados do ONS (eólica + solar)
    3. Identifica TODAS as colunas com nomes de usinas/conjuntos no ONS
    4. Para cada candidato, mede a taxa de match com o Excel
    5. Mostra:
       - Qual coluna do ONS é a melhor para casar
       - Quantos nomes do Excel não acharam par no ONS
       - Quantos nomes do ONS não estão no Excel
       - Sugestões de matching tolerante (uppercase, sem acentos, etc.)

Saída esperada: dois CSVs em ./relatorio_casamento/
    - excel_sem_par_no_ons.csv      (usinas do Excel que não casaram)
    - ons_sem_par_no_excel.csv      (usinas do ONS sem proprietário definido)
    - matching_report.txt            (resumo executivo)

Não modifica nada — só lê e gera relatório.
"""

from __future__ import annotations

import io
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

try:
    from curl_cffi import requests as creq
    HAS_CURL_CFFI = True
except ImportError:
    print("⚠ curl_cffi não instalado. Tentando com requests padrão (pode falhar por TLS fingerprint).")
    import requests as creq
    HAS_CURL_CFFI = False


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

# Ajuste se o Excel estiver em outro caminho
EXCEL_PATH = "data/Excel_Curtailment_Base.xlsx"

# Quantos meses recentes baixar do ONS para teste
N_MESES_TESTE = 12

# Pasta de saída
OUT_DIR = Path("relatorio_casamento")

URL_BASE_EOLICA = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/"
    "dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_{ano}_{mes:02d}.parquet"
)
URL_BASE_SOLAR = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/"
    "dataset/restricao_coff_fotovoltaica_tm/RESTRICAO_COFF_FOTOVOLTAICA_{ano}_{mes:02d}.parquet"
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://dados.ons.org.br/",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalizar_nome(s: str) -> str:
    """
    Normaliza nome para matching tolerante:
      - uppercase
      - remove acentos
      - remove sufixos descritivos entre parênteses no fim: (EÓLICO), (SOLAR)
      - expande abreviações: FOTOV. -> FOTOVOLTAICO
      - remove prefixos descritivos em CASCATA: CONJ. + EÓLICO + ... -> nome puro
      - remove caracteres não alfanuméricos

    Exemplos:
        "CONJ. ARACATI II"                    -> "ARACATIII"
        "CONJUNTO FOTOVOLTAICO BOA SORTE"     -> "BOASORTE"
        "CONJ. BOA SORTE"                     -> "BOASORTE"  # mesma chave!
        "CONJ. EÓLICO LIVRAMENTO 3"           -> "LIVRAMENTO3"
        "CONJ. LIVRAMENTO 3"                  -> "LIVRAMENTO3"  # idem
        "CONJ. SÃO BASÍLIO (SOLAR)"            -> "SAOBASILIO"
        "CONJ. FOTOV. SIMPLICE"                -> "SIMPLICE"
    """
    if pd.isna(s):
        return ""
    s = str(s).strip().upper()

    # 1. Remove acentos
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")

    # 2. Remove sufixos descritivos entre parênteses no final
    s = re.sub(r"\s*\(\s*EOLICO\s*\)\s*$", "", s)
    s = re.sub(r"\s*\(\s*SOLAR\s*\)\s*$", "", s)
    s = re.sub(r"\s*\(\s*FOTOVOLTAICO\s*\)\s*$", "", s)

    # 3. Expande abreviações
    s = re.sub(r"\bFOTOV\.\s*", "FOTOVOLTAICO ", s)

    # 4. Remove prefixos descritivos em CASCATA até não restar nenhum
    #    (lida com encadeamentos tipo "CONJ. EÓLICO X" -> "EÓLICO X" -> "X")
    prefixos = [
        "CONJUNTO FOTOVOLTAICO",
        "CONJUNTO EOLICO",
        "PARQUE EOLICO",
        "PARQUE SOLAR",
        "USINA EOLICA",
        "USINA SOLAR",
        "COMPLEXO EOLICO",
        "COMPLEXO",
        "CONJUNTO",
        "CONJ.",
        "CONJ ",
        "FOTOVOLTAICO",
        "EOLICO",
        "SOLAR",
    ]
    mudou = True
    while mudou:
        mudou = False
        for p in prefixos:
            if s.startswith(p):
                s = s[len(p):].strip()
                mudou = True
                break  # reinicia para tentar outro prefixo aninhado

    # 5. Remove tudo que não é letra ou número
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s


def http_get(url: str, timeout: int = 90) -> Optional[bytes]:
    try:
        if HAS_CURL_CFFI:
            r = creq.get(url, impersonate="chrome",
                         headers=BROWSER_HEADERS, timeout=timeout)
        else:
            r = creq.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 0:
            return r.content
        print(f"  HTTP {r.status_code} em {url[-60:]}")
        return None
    except Exception as e:
        print(f"  Erro: {type(e).__name__}: {e}")
        return None


def gerar_meses_recentes(n: int) -> list[tuple[int, int]]:
    """Lista (ano, mes) dos N meses mais recentes, do mais novo para o mais velho."""
    hoje = date.today()
    meses = []
    ano, mes = hoje.year, hoje.month
    for _ in range(n):
        meses.append((ano, mes))
        mes -= 1
        if mes == 0:
            mes = 12
            ano -= 1
    return meses


def baixar_amostra_ons(fonte: str, n_meses: int = N_MESES_TESTE) -> pd.DataFrame:
    """Baixa N meses recentes do ONS para a fonte (eolica/solar)."""
    base = URL_BASE_EOLICA if fonte == "eolica" else URL_BASE_SOLAR
    dfs = []
    for ano, mes in gerar_meses_recentes(n_meses):
        url = base.format(ano=ano, mes=mes)
        print(f"  Baixando {fonte} {ano}-{mes:02d}...", end=" ", flush=True)
        content = http_get(url)
        if not content:
            # Pode ser que o mês mais recente ainda não esteja publicado; tentamos o anterior
            print("(não disponível)")
            continue
        try:
            df = pd.read_parquet(io.BytesIO(content))
            # Padronizar colunas para uppercase
            df.columns = [str(c).strip().upper() for c in df.columns]
            df["__ANO_MES"] = f"{ano}-{mes:02d}"
            dfs.append(df)
            print(f"OK ({len(df):,} linhas)")
        except Exception as e:
            print(f"erro lendo: {e}")
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def detectar_colunas_nome(df: pd.DataFrame) -> list[str]:
    """Detecta colunas que parecem conter nomes de usinas/conjuntos."""
    candidatas = []
    keywords = ["NOM_USINA", "NOM_CONJUNTO", "CONJUNTO", "NOMUSINA",
                "NOMCONJUNTO", "USINA", "CEG"]
    for col in df.columns:
        col_upper = col.upper()
        for kw in keywords:
            if kw in col_upper and col not in candidatas:
                candidatas.append(col)
                break
    return candidatas


def validar_excel_internamente(df_excel: pd.DataFrame, fonte: str, out_lines: list) -> None:
    """
    Pré-validação: verifica se a normalização do Nome_Arquivo cria
    colisões com proprietários conflitantes no próprio Excel.
    """
    df = df_excel.copy()
    df["__norm"] = df["Nome_Arquivo"].apply(normalizar_nome)

    # Colisões: nomes diferentes que viraram o mesmo normalizado
    colisoes = []
    conflitos_proprietario = []

    for k, group in df.groupby("__norm"):
        if len(group) <= 1:
            continue
        nomes_distintos = group["Nome_Arquivo"].nunique()
        if nomes_distintos > 1:
            # Há nomes diferentes que viraram a mesma chave
            props = group["Proprietário"].unique()

            # Verifica se é apenas rateio (mesmo Nome_Arquivo várias vezes)
            apenas_rateio = group["Nome_Arquivo"].duplicated(keep=False).all()

            if not apenas_rateio:
                colisoes.append({
                    "chave_norm": k,
                    "nomes": list(group["Nome_Arquivo"].unique()),
                    "proprietarios": list(props),
                })
                if len(props) > 1:
                    # Conflito real: mesma usina (após norm) com proprietários diferentes
                    conflitos_proprietario.append({
                        "chave_norm": k,
                        "linhas": group[["Nome_Arquivo", "Proprietário",
                                          "Participação na usina"]].to_dict("records"),
                    })

    out_lines.append(f"\n{'─'*70}")
    out_lines.append(f"PRÉ-VALIDAÇÃO INTERNA DO EXCEL ({fonte.upper()})")
    out_lines.append(f"{'─'*70}")
    out_lines.append(f"Linhas: {len(df)}")
    out_lines.append(f"Nomes únicos (raw): {df['Nome_Arquivo'].nunique()}")
    out_lines.append(f"Nomes únicos (normalizados): {df['__norm'].nunique()}")
    out_lines.append(f"Colisões de normalização: {len(colisoes)}")
    out_lines.append(f"  → das quais com proprietários conflitantes: {len(conflitos_proprietario)}")

    if conflitos_proprietario:
        out_lines.append("")
        out_lines.append("⚠ CONFLITOS NO EXCEL (mesma usina com proprietários diferentes):")
        for c in conflitos_proprietario:
            out_lines.append(f"  '{c['chave_norm']}':")
            for linha in c["linhas"]:
                out_lines.append(
                    f"    {linha['Nome_Arquivo']:<50s} -> "
                    f"{linha['Proprietário']} ({linha['Participação na usina']*100:.0f}%)"
                )
        out_lines.append("  → AÇÃO: revise essas duplicatas no Excel antes de usar.")

    if colisoes and not conflitos_proprietario:
        out_lines.append("")
        out_lines.append("ℹ Colisões sem conflito (mesmo proprietário, só grafia diferente):")
        for c in colisoes[:10]:
            out_lines.append(f"  '{c['chave_norm']}': {c['nomes']}")


def validar_casamento_para_fonte(
    df_ons: pd.DataFrame,
    df_excel: pd.DataFrame,
    fonte: str,
    out_lines: list,
) -> dict:
    """Valida o casamento Excel ↔ ONS para uma fonte."""
    out_lines.append(f"\n{'='*70}")
    out_lines.append(f"VALIDAÇÃO: {fonte.upper()}")
    out_lines.append(f"{'='*70}\n")

    out_lines.append(f"Linhas Excel: {len(df_excel)}")
    out_lines.append(f"Linhas ONS amostra: {len(df_ons):,}")
    out_lines.append(f"Colunas ONS: {list(df_ons.columns)[:20]}")

    # Detectar colunas candidatas
    cols_candidatas = detectar_colunas_nome(df_ons)
    out_lines.append(f"\nColunas candidatas no ONS: {cols_candidatas}")

    if not cols_candidatas:
        out_lines.append("✗ NENHUMA coluna candidata encontrada. Schema ONS pode ter mudado.")
        return {}

    # Conjunto de nomes do Excel (originais e normalizados)
    excel_originais = set(df_excel["Nome_Arquivo"].astype(str).str.strip())
    excel_norm = {normalizar_nome(n): n for n in excel_originais}

    out_lines.append(f"\nNomes únicos no Excel: {len(excel_originais)}")

    # Para cada coluna candidata, medir taxa de match
    melhor_col = None
    melhor_taxa = 0.0
    melhor_match_norm = 0.0

    out_lines.append(f"\n{'-'*70}")
    out_lines.append("Taxa de match por coluna candidata:")
    out_lines.append(f"{'-'*70}")
    out_lines.append(f"{'Coluna':<25} {'Únicos ONS':>10} {'Match exato':>12} {'Match norm.':>12}")

    for col in cols_candidatas:
        ons_originais = set(df_ons[col].dropna().astype(str).str.strip())
        ons_originais.discard("")
        ons_norm = {normalizar_nome(n) for n in ons_originais}

        # Match exato (case-sensitive, com acentos)
        intersect_exato = excel_originais & ons_originais
        # Match normalizado
        intersect_norm = set(excel_norm.keys()) & ons_norm

        taxa_exata = len(intersect_exato) / max(len(excel_originais), 1)
        taxa_norm = len(intersect_norm) / max(len(excel_originais), 1)

        out_lines.append(
            f"{col:<25} {len(ons_originais):>10,} "
            f"{len(intersect_exato):>5} ({taxa_exata*100:>4.0f}%) "
            f"{len(intersect_norm):>5} ({taxa_norm*100:>4.0f}%)"
        )

        if taxa_norm > melhor_match_norm:
            melhor_col = col
            melhor_taxa = taxa_exata
            melhor_match_norm = taxa_norm

    out_lines.append(f"\n→ Melhor coluna: {melhor_col}")
    out_lines.append(f"  Taxa exata:      {melhor_taxa*100:.1f}%")
    out_lines.append(f"  Taxa normalizada: {melhor_match_norm*100:.1f}%")

    if not melhor_col:
        return {}

    # Detalhar mismatches usando a melhor coluna
    ons_originais = set(df_ons[melhor_col].dropna().astype(str).str.strip())
    ons_originais.discard("")
    ons_norm = {normalizar_nome(n): n for n in ons_originais}

    excel_norm_set = set(excel_norm.keys())
    ons_norm_set = set(ons_norm.keys())

    excel_sem_par = excel_norm_set - ons_norm_set
    ons_sem_par = ons_norm_set - excel_norm_set

    out_lines.append(f"\nMismatches usando {melhor_col} (com normalização):")
    out_lines.append(f"  Excel SEM par no ONS: {len(excel_sem_par)}")
    out_lines.append(f"  ONS SEM par no Excel: {len(ons_sem_par)}")

    # Salvar CSVs
    OUT_DIR.mkdir(exist_ok=True)

    # Excel sem par
    if excel_sem_par:
        df_excel_sem_par = df_excel[
            df_excel["Nome_Arquivo"].astype(str).str.strip().apply(
                lambda x: normalizar_nome(x) in excel_sem_par
            )
        ]
        out_path = OUT_DIR / f"{fonte}_excel_sem_par_no_ons.csv"
        df_excel_sem_par.to_csv(out_path, sep=";", encoding="utf-8-sig", index=False)
        out_lines.append(f"  → Salvo: {out_path}")

    # ONS sem par (com contagem de aparições para priorizar)
    if ons_sem_par:
        contagem_ons = (
            df_ons[df_ons[melhor_col].astype(str).str.strip().apply(
                lambda x: normalizar_nome(x) in ons_sem_par
            )]
            .groupby(melhor_col)
            .size()
            .sort_values(ascending=False)
            .reset_index()
            .rename(columns={0: "linhas_no_ons"})
        )
        if len(contagem_ons.columns) >= 2:
            contagem_ons.columns = [melhor_col, "linhas_no_ons"]
        out_path = OUT_DIR / f"{fonte}_ons_sem_par_no_excel.csv"
        contagem_ons.to_csv(out_path, sep=";", encoding="utf-8-sig", index=False)
        out_lines.append(f"  → Salvo: {out_path} (top 5 abaixo)")
        for _, row in contagem_ons.head(5).iterrows():
            out_lines.append(f"      {row[melhor_col]} ({row['linhas_no_ons']:,} linhas)")

    return {
        "melhor_col": melhor_col,
        "taxa_exata": melhor_taxa,
        "taxa_norm": melhor_match_norm,
        "excel_sem_par": len(excel_sem_par),
        "ons_sem_par": len(ons_sem_par),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print(f"\n{'='*70}")
    print(f"VALIDAÇÃO: Excel de Proprietários ↔ ONS Constrained-off")
    print(f"{'='*70}\n")

    # 1. Carregar Excel
    excel_path = Path(EXCEL_PATH)
    if not excel_path.exists():
        # Tentar caminhos alternativos
        for alt in ["Excel_Curtailment_Base__1_.xlsx", "Excel_Curtailment_Base.xlsx"]:
            alt_path = Path(alt)
            if alt_path.exists():
                excel_path = alt_path
                break
        else:
            print(f"✗ Excel não encontrado em {EXCEL_PATH}")
            print("  Coloque em data/Excel_Curtailment_Base.xlsx ou na raiz do projeto.")
            sys.exit(1)

    print(f"✓ Excel: {excel_path}")
    df_solar_excel = pd.read_excel(excel_path, sheet_name="Solar")
    df_eolica_excel = pd.read_excel(excel_path, sheet_name="Eólica")
    print(f"  Solar:  {len(df_solar_excel)} linhas")
    print(f"  Eólica: {len(df_eolica_excel)} linhas")

    out_lines = []
    out_lines.append("RELATÓRIO DE CASAMENTO Excel ↔ ONS")
    out_lines.append(f"Gerado em: {date.today().isoformat()}")
    out_lines.append(f"Excel: {excel_path}")
    out_lines.append(f"Meses do ONS testados: {N_MESES_TESTE}")

    # Pré-validação interna do Excel
    validar_excel_internamente(df_solar_excel, "solar", out_lines)
    validar_excel_internamente(df_eolica_excel, "eolica", out_lines)

    # 2. Baixar ONS
    print(f"\n[1/2] Baixando amostra ONS eólica ({N_MESES_TESTE} meses)...")
    df_eolica_ons = baixar_amostra_ons("eolica", N_MESES_TESTE)
    print(f"\n[2/2] Baixando amostra ONS solar ({N_MESES_TESTE} meses)...")
    df_solar_ons = baixar_amostra_ons("solar", N_MESES_TESTE)

    if len(df_eolica_ons) == 0 and len(df_solar_ons) == 0:
        print("\n✗ Não consegui baixar nenhum dado do ONS. Verifique conexão e firewall.")
        sys.exit(1)

    # 3. Validar casamento
    resumo = {}
    if len(df_eolica_ons) > 0:
        resumo["eolica"] = validar_casamento_para_fonte(
            df_eolica_ons, df_eolica_excel, "eolica", out_lines,
        )
    else:
        out_lines.append("\n⚠ Sem dados ONS de eólica para validar.")

    if len(df_solar_ons) > 0:
        resumo["solar"] = validar_casamento_para_fonte(
            df_solar_ons, df_solar_excel, "solar", out_lines,
        )
    else:
        out_lines.append("\n⚠ Sem dados ONS de solar para validar.")

    # 4. Salvar relatório
    OUT_DIR.mkdir(exist_ok=True)
    relatorio = OUT_DIR / "matching_report.txt"
    relatorio.write_text("\n".join(out_lines), encoding="utf-8")

    print("\n" + "\n".join(out_lines[-25:]))
    print(f"\n✓ Relatório completo: {relatorio}")
    print(f"✓ CSVs detalhados em: {OUT_DIR}/")

    # Recomendação final
    print(f"\n{'='*70}")
    print("PRÓXIMOS PASSOS")
    print(f"{'='*70}")

    if resumo:
        for fonte, r in resumo.items():
            if not r:
                continue
            taxa = r["taxa_norm"] * 100
            if taxa > 95:
                print(f"  ✓ {fonte.upper()}: matching está sólido ({taxa:.1f}%) — "
                      f"podemos prosseguir. Usar coluna '{r['melhor_col']}' "
                      f"+ normalização (uppercase, sem acentos, só alfanum).")
            elif taxa > 80:
                print(f"  ⚠ {fonte.upper()}: matching parcial ({taxa:.1f}%). "
                      f"Revise os {r['excel_sem_par']} casos no CSV antes de prosseguir.")
            else:
                print(f"  ✗ {fonte.upper()}: matching baixo ({taxa:.1f}%). "
                      f"Coluna correta provavelmente é outra. Me mande o "
                      f"matching_report.txt para eu investigar.")


if __name__ == "__main__":
    main()
