"""Carrega e valida a configuração. Erros aparecem na partida, não no meio da carga."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "output"
REPORTS_DIR = OUTPUT_DIR / "reports"
CHARTS_DIR = OUTPUT_DIR / "charts"
LOGS_DIR = OUTPUT_DIR / "logs"
TIPOS_FONTE = {"api", "excel", "csv", "jsonl", "json"}
TIPOS_COLUNA = {"texto", "inteiro", "numero", "data", "booleano"}


class ErroDeConfiguracao(Exception):
    pass


@dataclass(frozen=True)
class Configuracao:
    inicio: pd.Timestamp
    fim: pd.Timestamp
    raiz_lake: Path
    regras: dict
    atribuicao: dict
    ltv: dict
    fontes: dict
    canais: dict


def _validar_fontes(fontes: dict) -> None:
    for nome, fonte in fontes.items():
        if fonte.get("tipo") not in TIPOS_FONTE:
            raise ErroDeConfiguracao(f"fonte '{nome}': tipo inválido {fonte.get('tipo')!r}")
        if not fonte.get("contrato"):
            raise ErroDeConfiguracao(f"fonte '{nome}': contrato ausente")
        for coluna, regra in fonte["contrato"].items():
            if regra.get("tipo") not in TIPOS_COLUNA:
                raise ErroDeConfiguracao(f"fonte '{nome}', coluna '{coluna}': tipo inválido {regra.get('tipo')!r}")


def carregar(caminho: Path | str = ROOT_DIR / "config" / "pipeline.yaml") -> Configuracao:
    caminho = Path(caminho)
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    canais = yaml.safe_load((caminho.parent / "canais.yaml").read_text(encoding="utf-8"))
    faltando = {"periodo", "lake", "regras", "atribuicao", "ltv", "fontes"} - set(dados)
    if faltando:
        raise ErroDeConfiguracao(f"seções ausentes em {caminho.name}: {sorted(faltando)}")
    _validar_fontes(dados["fontes"])
    return Configuracao(
        inicio=pd.Timestamp(dados["periodo"]["inicio"]), fim=pd.Timestamp(dados["periodo"]["fim"]),
        raiz_lake=ROOT_DIR / dados["lake"]["raiz"], regras=dados["regras"], atribuicao=dados["atribuicao"], ltv=dados["ltv"],
        fontes=dados["fontes"], canais=canais,
    )


def token_da_fonte(fonte: dict) -> str:
    """Segredo vem do ambiente, nunca do repositório. O valor padrão só existe para a API simulada."""
    token = os.environ.get(fonte["token_env"])
    if token:
        return token
    if fonte["url_base"] == "mock":
        return fonte["token_padrao_mock"]
    raise ErroDeConfiguracao(f"variável de ambiente {fonte['token_env']} não definida")
