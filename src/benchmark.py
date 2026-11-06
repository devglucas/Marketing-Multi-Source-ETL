"""
CSV x Parquet com os mesmos dados: tamanho em disco e tempo de três leituras típicas.

Cada leitura roda algumas vezes e fica a mediana, para reduzir o efeito de ruído da máquina.
Os tempos variam entre computadores; a ordem de grandeza é o que interessa.
"""

from __future__ import annotations

import statistics
import tempfile
import time
from pathlib import Path

import pandas as pd

from src.lake import caminho

REPETICOES = 5


def _tamanho_mb(destino: Path) -> float:
    arquivos = [destino] if destino.is_file() else destino.rglob("*.parquet")
    return sum(a.stat().st_size for a in arquivos) / 1024 ** 2


def _tempo_ms(funcao) -> float:
    medidas = []
    for _ in range(REPETICOES):
        inicio = time.perf_counter()
        funcao()
        medidas.append((time.perf_counter() - inicio) * 1000)
    return statistics.median(medidas)


def _ler_mes_do_csv(csv: Path, mes: str) -> pd.DataFrame:
    """CSV não tem partição: para achar um mês, é preciso ler o arquivo inteiro."""
    df = pd.read_csv(csv)
    return df[df["ano_mes"] == mes]


def comparar(sessoes: pd.DataFrame, raiz: Path, mes: str = "2025-03") -> pd.DataFrame:
    parquet = caminho(raiz, "curated", "sessoes")
    colunas = ["canal", "purchase"]
    with tempfile.TemporaryDirectory() as pasta:
        csv = Path(pasta) / "sessoes.csv"
        sessoes.to_csv(csv, index=False)
        linhas = [
            ("tamanho em disco (MB)", _tamanho_mb(csv), _tamanho_mb(parquet)),
            ("ler a tabela inteira (ms)", _tempo_ms(lambda: pd.read_csv(csv)), _tempo_ms(lambda: pd.read_parquet(parquet))),
            ("ler 2 colunas (ms)", _tempo_ms(lambda: pd.read_csv(csv, usecols=colunas)), _tempo_ms(lambda: pd.read_parquet(parquet, columns=colunas))),
            ("ler 1 mês (ms)", _tempo_ms(lambda: _ler_mes_do_csv(csv, mes)),
             _tempo_ms(lambda: pd.read_parquet(parquet, filters=[("ano_mes", "=", mes)]))),
        ]
    tabela = pd.DataFrame(linhas, columns=["medida", "csv", "parquet"])
    return tabela.assign(vantagem=tabela["csv"] / tabela["parquet"])
