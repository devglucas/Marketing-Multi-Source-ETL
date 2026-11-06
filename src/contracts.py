"""
Contratos de dados: o que cada fonte promete entregar.

A cada carga, o que chegou é comparado com o contrato declarado no YAML:
- coluna obrigatória ausente: a fonte quebrou o contrato, e a carga para (erro)
- coluna renomeada conhecida (apelido): unifica e registra (alerta)
- coluna nova: é mantida fora do pipeline e registrada (alerta)
- valores que não respeitam o tipo: registrado com a quantidade (alerta)
"""

from __future__ import annotations

import pandas as pd


class ContratoQuebrado(Exception):
    pass


def _nao_conforme(serie: pd.Series, tipo: str) -> int:
    preenchida = serie.dropna().astype("string")
    if tipo == "inteiro":
        return int((~preenchida.str.fullmatch(r"-?\d+(\.0+)?", na=False)).sum())
    if tipo == "numero":
        return int(pd.to_numeric(preenchida, errors="coerce").isna().sum())
    if tipo == "data":
        return int(pd.to_datetime(preenchida, errors="coerce", format="%Y-%m-%d").isna().sum())
    if tipo == "booleano":
        return int((~preenchida.str.lower().isin(["true", "false"])).sum())
    return 0


def aplicar_contrato(df: pd.DataFrame, contrato: dict, fonte: str) -> tuple[pd.DataFrame, list[dict]]:
    """Devolve o DataFrame só com as colunas do contrato e a lista de ocorrências."""
    ocorrencias, df = [], df.copy()
    tecnicas = [c for c in df.columns if c.startswith("_")]

    for coluna, regra in contrato.items():
        apelidos = [a for a in regra.get("apelidos", []) if a in df.columns]
        if apelidos:
            nomes = ([coluna] if coluna in df.columns else []) + apelidos
            df[coluna] = df[nomes].bfill(axis=1).iloc[:, 0]  # a coluna pode mudar de nome no meio do arquivo
            df = df.drop(columns=apelidos)
            ocorrencias.append({"fonte": fonte, "tipo": "coluna_renomeada", "coluna": coluna,
                                "detalhe": f"unificada com {apelidos}"})

    ausentes = [c for c, r in contrato.items() if c not in df.columns and r.get("obrigatoria")]
    if ausentes:
        raise ContratoQuebrado(f"{fonte}: colunas obrigatórias ausentes: {ausentes}")

    novas = [c for c in df.columns if c not in contrato and c not in tecnicas]
    for coluna in novas:
        ocorrencias.append({"fonte": fonte, "tipo": "coluna_nova", "coluna": coluna, "detalhe": "fora do contrato: ignorada"})

    for coluna, regra in contrato.items():
        if coluna not in df.columns:
            df[coluna] = pd.NA
            continue
        invalidos = _nao_conforme(df[coluna], regra["tipo"])
        if invalidos:
            ocorrencias.append({"fonte": fonte, "tipo": "tipo_invalido", "coluna": coluna,
                                "detalhe": f"{invalidos} valores não são {regra['tipo']}"})
        nulos = int(df[coluna].isna().sum())
        if regra.get("obrigatoria") and nulos:
            ocorrencias.append({"fonte": fonte, "tipo": "obrigatoria_nula", "coluna": coluna, "detalhe": f"{nulos} nulos"})
    return df[[*contrato, *tecnicas]], ocorrencias
