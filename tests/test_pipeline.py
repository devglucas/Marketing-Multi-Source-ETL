"""Teste de ponta a ponta: roda o pipeline de verdade, com a API simulada e o lake em pasta temporária."""

import dataclasses

import pandas as pd
import pytest

from main import executar
from src import lake
from src.settings import carregar


@pytest.fixture(scope="module")
def execucao(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("execucao")
    config = dataclasses.replace(carregar(), raiz_lake=pasta / "lake")
    return config, pasta, executar(config, pasta / "output", com_benchmark=False)


def test_nenhuma_verificacao_critica_falha(execucao):
    _, _, resultado = execucao
    assert resultado["manifesto"]["sucesso"]
    assert [v for v in resultado["verificacoes"] if v["severidade"] == "critica" and not v["ok"]] == []


def test_mudanca_de_coluna_da_meta_vira_alerta(execucao):
    _, _, resultado = execucao
    assert any(o["fonte"] == "meta_ads" for o in resultado["manifesto"]["ocorrencias_de_contrato"])


def test_api_precisou_de_novas_tentativas(execucao):
    _, _, resultado = execucao
    assert resultado["manifesto"]["api"]["novas_tentativas"] > 0


def test_lake_tem_as_tres_camadas_e_particoes_por_mes(execucao):
    config, _, _ = execucao
    assert {p.name for p in config.raiz_lake.iterdir()} == {"landing", "curated", "marts"}
    meses = {p.name for p in (config.raiz_lake / "curated" / "sessoes").iterdir()}
    assert len(meses) == 6 and "ano_mes=2025-03" in meses


def test_leitura_parcial_do_lake(execucao):
    config, _, _ = execucao
    marco = lake.ler(config.raiz_lake, "curated", "pedidos", colunas=["pedido_id", "ano_mes"], filtros=[("ano_mes", "=", "2025-03")])
    assert list(marco.columns) == ["pedido_id", "ano_mes"] and set(marco["ano_mes"]) == {"2025-03"}


def test_saidas_foram_geradas(execucao):
    _, pasta, _ = execucao
    assert (pasta / "output" / "relatorio.md").exists() and (pasta / "output" / "run_manifest.json").exists()
    assert len(list((pasta / "output" / "charts").glob("*.png"))) == 6


def test_reprocessar_e_idempotente(execucao):
    config, pasta, primeira = execucao
    segunda = executar(config, pasta / "output", com_benchmark=False)
    assert lake.ler(config.raiz_lake, "curated", "sessoes", colunas=["session_id"])["session_id"].is_unique
    pd.testing.assert_frame_equal(primeira["marts"]["desempenho_canal"], segunda["marts"]["desempenho_canal"])
