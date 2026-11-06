"""
Data lake em Parquet, em três camadas:

    landing/   o dado como chegou, tudo em texto, com origem e horário da ingestão
    curated/   dado limpo e tipado, com schema explícito e partições por mês
    marts/     tabelas prontas para análise

Por que Parquet: é colunar (ler 2 colunas não lê o arquivo inteiro), comprimido e guarda os
tipos. Partições (ano_mes=2025-03/) deixam a leitura pular meses inteiros.

Escritas são idempotentes: rodar de novo substitui a tabela ou as partições afetadas.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

COMPRESSAO = "zstd"

ESQUEMAS = {
    "sessoes": pa.schema([
        ("session_id", pa.string()), ("visitor_id", pa.string()), ("momento", pa.timestamp("us", tz="UTC")),
        ("canal", pa.string()), ("fonte", pa.string()), ("meio", pa.string()), ("campanha", pa.string()),
        ("device", pa.string()), ("pageviews", pa.int32()), ("add_to_cart", pa.bool_()), ("begin_checkout", pa.bool_()),
        ("purchase", pa.bool_()), ("ano_mes", pa.string()),
    ]),
    "pedidos": pa.schema([
        ("pedido_id", pa.string()), ("cliente_id", pa.string()), ("visitor_id", pa.string()),
        ("momento", pa.timestamp("us", tz="UTC")), ("valor_produtos", pa.float64()), ("desconto", pa.float64()),
        ("frete", pa.float64()), ("receita_liquida", pa.float64()), ("status", pa.string()), ("valido", pa.bool_()),
        ("ano_mes", pa.string()),
    ]),
    "gasto_midia": pa.schema([
        ("data", pa.timestamp("us")), ("plataforma", pa.string()), ("canal", pa.string()), ("campanha", pa.string()),
        ("objetivo", pa.string()), ("impressoes", pa.int64()), ("cliques", pa.int64()), ("custo", pa.float64()),
        ("conversoes_plataforma", pa.float64()), ("ano_mes", pa.string()),
    ]),
    "clientes": pa.schema([("cliente_id", pa.string()), ("uf", pa.string()), ("cadastrado_em", pa.timestamp("us"))]),
}


def caminho(raiz: Path, camada: str, tabela: str) -> Path:
    return raiz / camada / tabela


def escrever(df: pd.DataFrame, raiz: Path, camada: str, tabela: str, esquema: pa.Schema | None = None,
             particoes: list[str] | None = None) -> None:
    """Grava a tabela. Com schema explícito, um tipo inesperado falha aqui, e não em quem lê depois."""
    destino = caminho(raiz, camada, tabela)
    arrow = pa.Table.from_pandas(df, schema=esquema, preserve_index=False)
    if particoes:
        pq.write_to_dataset(arrow, destino, partition_cols=particoes, compression=COMPRESSAO,
                            existing_data_behavior="delete_matching")
    else:
        shutil.rmtree(destino, ignore_errors=True)
        destino.mkdir(parents=True)
        pq.write_table(arrow, destino / "dados.parquet", compression=COMPRESSAO)


def ler(raiz: Path, camada: str, tabela: str, colunas: list[str] | None = None, filtros: list | None = None) -> pd.DataFrame:
    return pd.read_parquet(caminho(raiz, camada, tabela), columns=colunas, filters=filtros)


def salvar_landing(df: pd.DataFrame, raiz: Path, fonte: str) -> None:
    """Guarda o dado bruto em texto: permite reprocessar sem consultar a fonte de novo."""
    bruto = df.astype("string").assign(_ingerido_em=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    escrever(bruto, raiz, "landing", fonte)
