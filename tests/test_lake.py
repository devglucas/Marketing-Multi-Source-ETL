import pandas as pd
import pyarrow as pa
import pytest

from src.lake import ESQUEMAS, escrever, ler


def _clientes():
    return pd.DataFrame({"cliente_id": ["A"], "uf": ["SP"], "cadastrado_em": pd.to_datetime(["2025-01-01"])})


def test_schema_explicito_barra_tipo_inesperado(tmp_path):
    invalido = _clientes().assign(cadastrado_em=["ontem"])
    with pytest.raises((pa.ArrowInvalid, pa.ArrowTypeError)):
        escrever(invalido, tmp_path, "curated", "clientes", ESQUEMAS["clientes"])


def test_escrita_particionada_e_filtro_le_so_o_mes(tmp_path):
    df = pd.DataFrame({"x": [1, 2, 3], "ano_mes": ["2025-01", "2025-01", "2025-02"]})
    escrever(df, tmp_path, "curated", "t", particoes=["ano_mes"])
    assert {p.name for p in (tmp_path / "curated" / "t").iterdir()} == {"ano_mes=2025-01", "ano_mes=2025-02"}
    assert ler(tmp_path, "curated", "t", filtros=[("ano_mes", "=", "2025-02")])["x"].tolist() == [3]


def test_reescrever_substitui_a_particao_e_preserva_as_outras(tmp_path):
    escrever(pd.DataFrame({"x": [1, 2], "ano_mes": ["2025-01", "2025-02"]}), tmp_path, "curated", "t", particoes=["ano_mes"])
    escrever(pd.DataFrame({"x": [9], "ano_mes": ["2025-02"]}), tmp_path, "curated", "t", particoes=["ano_mes"])
    resultado = ler(tmp_path, "curated", "t").sort_values("x")
    assert resultado["x"].tolist() == [1, 9]            # sem duplicar o mês reprocessado
