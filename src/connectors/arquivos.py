"""Conectores de arquivo. Tudo é lido sem inferir tipos: a conversão acontece depois do contrato."""

from __future__ import annotations

import pandas as pd

from src.settings import ROOT_DIR


def ler_csv(fonte: dict, _contexto: dict) -> pd.DataFrame:
    return pd.read_csv(ROOT_DIR / fonte["caminho"], dtype="string").assign(_origem=fonte["caminho"])


def ler_json(fonte: dict, _contexto: dict) -> pd.DataFrame:
    return pd.read_json(ROOT_DIR / fonte["caminho"], dtype=False).assign(_origem=fonte["caminho"])


def ler_jsonl(fonte: dict, _contexto: dict) -> pd.DataFrame:
    partes = [pd.read_json(caminho, lines=True, compression="gzip", dtype=False, convert_dates=False).assign(_origem=caminho.name)
              for caminho in sorted(ROOT_DIR.glob(fonte["padrao"]))]
    return pd.concat(partes, ignore_index=True)


def ler_excel(fonte: dict, _contexto: dict) -> pd.DataFrame:
    """Uma aba por mês. As abas podem ter colunas diferentes: o contrato unifica depois."""
    abas = pd.read_excel(ROOT_DIR / fonte["caminho"], sheet_name=None, header=fonte["linha_cabecalho"], dtype=object)
    return pd.concat([df.assign(_origem=aba) for aba, df in abas.items()], ignore_index=True)
