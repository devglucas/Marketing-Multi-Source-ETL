"""Logger (console e arquivo) e formatação de relatórios."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd


def configurar_logger(nome: str = "pipeline") -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)-10s | %(message)s",
                        datefmt="%H:%M:%S")
    return logging.getLogger(nome)


def gravar_logs_em(caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    arquivo = logging.FileHandler(caminho, encoding="utf-8")
    arquivo.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)-10s | %(message)s"))
    logging.getLogger().addHandler(arquivo)


def parse_numero(serie: pd.Series) -> pd.Series:
    """'R$ 1.234,56', '1234.56' e 1234 -> float. Vírgula = formato brasileiro."""
    texto = serie.astype("string").str.replace(r"(?i)r\$", "", regex=True).str.replace(r"\s", "", regex=True)
    brasileiro = texto.str.contains(",", regex=False, na=False)
    texto = texto.mask(brasileiro, texto.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(texto, errors="coerce").astype("float64")


def formatar_br(valor, casas: int = 2) -> str:
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return ""
    if isinstance(valor, (bool, np.bool_)):
        return "sim" if valor else "não"
    if isinstance(valor, (int, np.integer)):
        return f"{valor:,}".replace(",", ".")
    if isinstance(valor, (float, np.floating)):
        return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(valor)


def df_para_markdown(df: pd.DataFrame, casas: int = 2) -> str:
    cabecalho = "| " + " | ".join(map(str, df.columns)) + " |"
    separador = "|" + "|".join("---" for _ in df.columns) + "|"
    linhas = ["| " + " | ".join("" if pd.isna(v) else formatar_br(v, casas) for v in linha) + " |"
              for linha in df.itertuples(index=False)]
    return "\n".join([cabecalho, separador, *linhas])
