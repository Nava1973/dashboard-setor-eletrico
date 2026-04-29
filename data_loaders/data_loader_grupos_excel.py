"""
data_loader_grupos_excel.py
===========================

Carrega o mapeamento Nome_Arquivo (ONS) -> Proprietário (grupo econômico)
a partir do Excel `data/Excel_Curtailment_Base.xlsx`.

O Excel tem duas abas (Solar, Eólica) com schema:
    Nome_Arquivo            : nome do conjunto como aparece no ONS
    Participação na usina   : 0..1 (rateio entre sócios)
    Nome_Usina              : nome amigável (com sufixo "- X stk" em rateios)
    Estado                  : UF
    Proprietário            : grupo econômico

Adicionalmente, lê `data/aliases_curtailment.csv` que mapeia variações
de nome do ONS para nomes do Excel:
    nome_no_ons;nome_no_excel;observacao

Saída:
    DataFrame com schema padronizado (UPPER_SNAKE_CASE):
        NOME_ARQUIVO       : nome do Excel
        NOME_NORM          : nome normalizado (chave de junção)
        PARTICIPACAO       : 0..1
        NOME_USINA         : nome amigável (com diferenciação em rateios)
        UF
        PROPRIETARIO       : nome do grupo
        FONTE              : EOLICA ou SOLAR

Função auxiliar:
    normalizar_nome(s) - aplicada nos nomes do ONS na hora do join.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------------
# Caminhos default (relativos à raiz do projeto)
# ---------------------------------------------------------------------------

EXCEL_DEFAULT_PATH = "data/Excel_Curtailment_Base.xlsx"
ALIASES_DEFAULT_PATH = "data/aliases_curtailment.csv"


# ---------------------------------------------------------------------------
# Normalização (mesma lógica do script de validação)
# ---------------------------------------------------------------------------


def normalizar_nome(s) -> str:
    """
    Normaliza nome para matching tolerante:
      - uppercase
      - remove acentos
      - remove sufixos descritivos entre parênteses
      - expande FOTOV. -> FOTOVOLTAICO
      - remove prefixos descritivos em cascata
      - remove tudo que não é letra ou número

    Exemplos:
        "CONJ. ARACATI II"               -> "ARACATIII"
        "CONJUNTO FOTOVOLTAICO BOA SORTE" -> "BOASORTE"
        "CONJ. EÓLICO LIVRAMENTO 3"      -> "LIVRAMENTO3"
    """
    if pd.isna(s):
        return ""
    s = str(s).strip().upper()
    # Remove acentos
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # Remove sufixos descritivos entre parênteses
    s = re.sub(r"\s*\(\s*EOLICO\s*\)\s*$", "", s)
    s = re.sub(r"\s*\(\s*SOLAR\s*\)\s*$", "", s)
    s = re.sub(r"\s*\(\s*FOTOVOLTAICO\s*\)\s*$", "", s)
    # Expande abreviações
    s = re.sub(r"\bFOTOV\.\s*", "FOTOVOLTAICO ", s)
    # Remove prefixos descritivos em cascata
    prefixos = [
        "CONJUNTO FOTOVOLTAICO", "CONJUNTO EOLICO",
        "PARQUE EOLICO", "PARQUE SOLAR", "USINA EOLICA", "USINA SOLAR",
        "COMPLEXO EOLICO", "COMPLEXO",
        "CONJUNTO", "CONJ.", "CONJ ",
        "FOTOVOLTAICO", "EOLICO", "SOLAR", "EOLICA",
    ]
    mudou = True
    while mudou:
        mudou = False
        for p in prefixos:
            if s.startswith(p):
                s = s[len(p):].strip()
                mudou = True
                break
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registrar_erro(msg: str) -> None:
    try:
        if "_debug_erros" not in st.session_state:
            st.session_state["_debug_erros"] = []
        st.session_state["_debug_erros"].append(
            f"[{datetime.now().strftime('%H:%M:%S')}] [grupos_excel] {msg}"
        )
    except Exception:
        print(f"[grupos_excel] {msg}")


# ---------------------------------------------------------------------------
# Carregamento
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600, show_spinner=False)
def carregar_grupos_excel(caminho: str = EXCEL_DEFAULT_PATH) -> pd.DataFrame:
    """
    Carrega o Excel e retorna DataFrame consolidado com Solar + Eólica.

    Returns: DataFrame com schema padronizado UPPER_SNAKE_CASE.
    """
    p = Path(caminho)
    if not p.exists():
        # Tentar caminhos alternativos
        for alt in ["data/Excel_Curtailment_Base.xlsx",
                    "Excel_Curtailment_Base.xlsx"]:
            alt_p = Path(alt)
            if alt_p.exists():
                p = alt_p
                break
        else:
            _registrar_erro(f"Excel não encontrado em {caminho}")
            return pd.DataFrame()

    try:
        df_solar = pd.read_excel(p, sheet_name="Solar")
        df_solar["FONTE"] = "SOLAR"
        df_eolica = pd.read_excel(p, sheet_name="Eólica")
        df_eolica["FONTE"] = "EOLICA"
    except Exception as e:
        _registrar_erro(f"Erro lendo Excel: {e}")
        return pd.DataFrame()

    df = pd.concat([df_solar, df_eolica], ignore_index=True)

    # Padronizar colunas
    rename_map = {
        "Nome_Arquivo": "NOME_ARQUIVO",
        "Participação na usina": "PARTICIPACAO",
        "Nome_Usina": "NOME_USINA",
        "Estado": "UF",
        "Proprietário": "PROPRIETARIO",
    }
    df = df.rename(columns=rename_map)

    cols_obrigatorias = ["NOME_ARQUIVO", "PARTICIPACAO", "PROPRIETARIO", "FONTE"]
    if not all(c in df.columns for c in cols_obrigatorias):
        _registrar_erro(
            f"Colunas obrigatórias faltando. Encontradas: {list(df.columns)}"
        )
        return pd.DataFrame()

    # Tipos
    df["NOME_ARQUIVO"] = df["NOME_ARQUIVO"].astype(str).str.strip()
    df["PARTICIPACAO"] = pd.to_numeric(df["PARTICIPACAO"], errors="coerce").fillna(1.0)
    df["PROPRIETARIO"] = df["PROPRIETARIO"].astype(str).str.strip()
    if "NOME_USINA" in df.columns:
        df["NOME_USINA"] = df["NOME_USINA"].astype(str).str.strip()
    else:
        df["NOME_USINA"] = df["NOME_ARQUIVO"]
    if "UF" in df.columns:
        df["UF"] = df["UF"].astype(str).str.strip().str.upper()

    # Chave normalizada para matching
    df["NOME_NORM"] = df["NOME_ARQUIVO"].apply(normalizar_nome)

    # Limpar linhas inválidas
    df = df[df["NOME_NORM"] != ""]
    df = df.reset_index(drop=True)

    return df


@st.cache_data(ttl=3600, show_spinner=False)
def carregar_aliases(caminho: str = ALIASES_DEFAULT_PATH) -> dict:
    """
    Carrega aliases CSV. Retorna dict: {nome_norm_no_ons: nome_norm_no_excel}.

    Se o arquivo não existir, retorna dict vazio.
    """
    p = Path(caminho)
    if not p.exists():
        return {}

    try:
        df = pd.read_csv(p, sep=";", encoding="utf-8-sig",
                          dtype=str, comment="#")
    except Exception as e:
        _registrar_erro(f"Erro lendo aliases: {e}")
        return {}

    df.columns = [c.strip().lower() for c in df.columns]
    if "nome_no_ons" not in df.columns or "nome_no_excel" not in df.columns:
        _registrar_erro(
            f"aliases_curtailment.csv sem colunas obrigatórias "
            f"(nome_no_ons, nome_no_excel). Encontradas: {list(df.columns)}"
        )
        return {}

    aliases = {}
    for _, row in df.iterrows():
        ons = str(row.get("nome_no_ons", "")).strip()
        ex = str(row.get("nome_no_excel", "")).strip()
        if ons and ex and ons.lower() != "nan" and ex.lower() != "nan":
            aliases[normalizar_nome(ons)] = normalizar_nome(ex)
    return aliases


# ---------------------------------------------------------------------------
# Aplicação do mapeamento (join entre dados ONS e proprietários)
# ---------------------------------------------------------------------------


def construir_chave_match(
    df_ons: pd.DataFrame,
    aliases: dict,
    coluna_nome_ons: str = "USINA",
) -> pd.Series:
    """
    Constrói a chave de match para cada linha do ONS:
    1. Normaliza o nome do ONS
    2. Se há alias, substitui pela forma do Excel
    3. Retorna a chave normalizada final

    Args:
        df_ons: DataFrame de curtailment (saída de data_loader_curtailment)
        aliases: dict {chave_norm_ons: chave_norm_excel}
        coluna_nome_ons: nome da coluna com nome da usina no ONS

    Returns:
        Series com a chave de match para cada linha (mesmo índice do df_ons).
    """
    if coluna_nome_ons not in df_ons.columns:
        return pd.Series([""] * len(df_ons), index=df_ons.index)

    chave_norm = df_ons[coluna_nome_ons].apply(normalizar_nome)
    if aliases:
        chave_norm = chave_norm.map(lambda x: aliases.get(x, x))
    return chave_norm


def aplicar_rateio(
    df_curt: pd.DataFrame,
    df_grupos: pd.DataFrame,
    aliases: dict,
) -> pd.DataFrame:
    """
    Faz join do curtailment com o Excel de proprietários, aplicando RATEIO
    proporcional à participação de cada sócio.

    Lógica do rateio:
      - Para cada linha do curtailment com nome NOME_X que casa com Excel:
        - Se Excel tem 1 sócio (participação=1.0): linha sai como está, com
          PROPRIETARIO atribuído.
        - Se Excel tem N sócios com participações p1, p2, ..., pN (somando 1):
          a linha vira N linhas, com FRUSTRADO_MW e GERACAO_REF_FINAL_MW
          multiplicados pela participação de cada sócio.

    Para usinas SEM correspondência no Excel, a linha sai com
    PROPRIETARIO = "Other (sem mapeamento)".

    Args:
        df_curt: saída de carregar_curtailment(), com coluna USINA
        df_grupos: saída de carregar_grupos_excel()
        aliases: dict de aliases ONS->Excel

    Returns:
        DataFrame com schema do df_curt + colunas:
            PROPRIETARIO, NOME_USINA_DASH, PARTICIPACAO_RATEIO
        e com FRUSTRADO_MW, GERACAO_REF_FINAL_MW, GERACAO_MW já rateados.
    """
    if len(df_curt) == 0:
        return df_curt

    # 1. Construir chave de match em ambos os lados
    df_curt = df_curt.copy()
    df_curt["__CHAVE"] = construir_chave_match(df_curt, aliases, "USINA")

    # 2. Preparar df_grupos para junção
    if len(df_grupos) == 0:
        df_curt["PROPRIETARIO"] = "Other (sem mapeamento)"
        df_curt["NOME_USINA_DASH"] = df_curt.get("USINA", "")
        df_curt["PARTICIPACAO_RATEIO"] = 1.0
        return df_curt.drop(columns=["__CHAVE"])

    # FONTE preservada na chave de merge: 7 NOME_NORM aparecem em ambas as
    # abas (Solar+Eólica) do Excel — complexos híbridos como BABILÔNIA SUL.
    # Sem FONTE no merge, uma linha eólica do ONS daria match com 2 linhas
    # do Excel (Solar+Eólica) e duplicaria volume após PARTICIPACAO_RATEIO.
    df_grupos_join = df_grupos[
        ["NOME_NORM", "PARTICIPACAO", "PROPRIETARIO", "NOME_USINA", "FONTE"]
    ].rename(columns={
        "NOME_NORM": "__CHAVE",
        "NOME_USINA": "NOME_USINA_DASH",
        "PARTICIPACAO": "PARTICIPACAO_RATEIO",
    })

    # 3. Merge: cada linha do curtailment pode virar N linhas (uma por sócio
    # da MESMA fonte). Sem FONTE na chave, complexos híbridos duplicariam.
    df_join = df_curt.merge(df_grupos_join, on=["__CHAVE", "FONTE"], how="left")

    # 4. Linhas sem match: marcar como Other (sem mapeamento)
    sem_match = df_join["PROPRIETARIO"].isna()
    df_join.loc[sem_match, "PROPRIETARIO"] = "Other (sem mapeamento)"
    df_join.loc[sem_match, "NOME_USINA_DASH"] = df_join.loc[sem_match, "USINA"]
    df_join.loc[sem_match, "PARTICIPACAO_RATEIO"] = 1.0

    # 5. Aplicar rateio nas métricas físicas.
    # IMPORTANTE: precisa ratear TODAS as colunas que serão somadas
    # downstream (numerador e denominador dos cálculos), senão usinas
    # com N sócios contam o valor N vezes na agregação. Bug histórico
    # corrigido: FRUSTRADO_MWH e OUTPUT_MWH estavam fora da lista, fazendo
    # o denominador ser inflado pelo número de sócios da usina.
    cols_rateio = [
        "GERACAO_MW",
        "GERACAO_REF_FINAL_MW",
        "FRUSTRADO_MW",
        "FRUSTRADO_MWH",   # numerador novo (utils_curtailment usa este)
        "OUTPUT_MWH",      # denominador novo (utils_curtailment usa este)
    ]
    if "GERACAO_LIMITADA_MW" in df_join.columns:
        cols_rateio.append("GERACAO_LIMITADA_MW")
    if "GERACAO_REF_MW" in df_join.columns:
        cols_rateio.append("GERACAO_REF_MW")

    for col in cols_rateio:
        if col in df_join.columns:
            df_join[col] = df_join[col] * df_join["PARTICIPACAO_RATEIO"]

    df_join = df_join.drop(columns=["__CHAVE"])
    return df_join


# ---------------------------------------------------------------------------
# Diagnósticos para a sub-aba de debug
# ---------------------------------------------------------------------------


def diagnostico_cobertura(
    df_curt: pd.DataFrame,
    df_grupos: pd.DataFrame,
    aliases: dict,
) -> dict:
    """
    Retorna métricas de cobertura do mapeamento Excel↔ONS para o df de
    curtailment carregado.

    Returns:
        dict com:
            usinas_ons_total: int
            usinas_com_match: int
            usinas_sem_match: int
            taxa_cobertura: float (0..1)
            top_usinas_sem_match: DataFrame (top usinas em "Other" por linhas)
            usinas_excel_nao_apareceram: list (usinas no Excel sem nada no ONS)
    """
    if len(df_curt) == 0 or "USINA" not in df_curt.columns:
        return {
            "usinas_ons_total": 0,
            "usinas_com_match": 0,
            "usinas_sem_match": 0,
            "taxa_cobertura": 0.0,
            "top_usinas_sem_match": pd.DataFrame(),
            "usinas_excel_nao_apareceram": [],
        }

    chave_match = construir_chave_match(df_curt, aliases, "USINA")
    chaves_excel = set(df_grupos["NOME_NORM"].unique()) if len(df_grupos) > 0 else set()

    chaves_ons = chave_match.unique()
    com_match = sum(1 for c in chaves_ons if c in chaves_excel)
    sem_match = len(chaves_ons) - com_match

    # Top usinas sem match (por contagem de linhas)
    df_curt_aux = df_curt.copy()
    df_curt_aux["__CHAVE"] = chave_match
    sem_match_mask = ~df_curt_aux["__CHAVE"].isin(chaves_excel)
    top_sem = (
        df_curt_aux[sem_match_mask]
        .groupby("USINA")
        .size()
        .sort_values(ascending=False)
        .head(20)
        .reset_index()
        .rename(columns={0: "linhas_no_ons"})
    )
    if len(top_sem.columns) >= 2:
        top_sem.columns = ["USINA", "linhas_no_ons"]

    # Usinas no Excel que não apareceram no ONS
    usinas_excel_nao_apareceram = []
    if len(df_grupos) > 0:
        chaves_ons_set = set(chaves_ons)
        for _, row in df_grupos.drop_duplicates("NOME_NORM").iterrows():
            if row["NOME_NORM"] not in chaves_ons_set:
                usinas_excel_nao_apareceram.append({
                    "Nome_Arquivo": row["NOME_ARQUIVO"],
                    "Proprietario": row["PROPRIETARIO"],
                    "Fonte": row["FONTE"],
                    "UF": row.get("UF", ""),
                })

    return {
        "usinas_ons_total": len(chaves_ons),
        "usinas_com_match": com_match,
        "usinas_sem_match": sem_match,
        "taxa_cobertura": com_match / len(chaves_ons) if len(chaves_ons) > 0 else 0.0,
        "top_usinas_sem_match": top_sem,
        "usinas_excel_nao_apareceram": usinas_excel_nao_apareceram,
    }
