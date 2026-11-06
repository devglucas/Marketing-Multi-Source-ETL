import pandas as pd

from src.benchmark import comparar
from src.lake import escrever


def test_compara_as_mesmas_medidas_nos_dois_formatos(tmp_path):
    df = pd.DataFrame({"canal": ["email"] * 200, "purchase": [True] * 200, "ano_mes": ["2025-03"] * 100 + ["2025-04"] * 100})
    escrever(df, tmp_path, "curated", "sessoes", particoes=["ano_mes"])
    tabela = comparar(df, tmp_path)
    assert len(tabela) == 4
    assert (tabela[["csv", "parquet", "vantagem"]] > 0).all().all()
