import pandas as pd
import pytest

from mock.ads_api import iniciar_servidor, url_de
from src.connectors.api import ErroDeApi, janelas, ler_api

FONTE = {"rota": "/v1/relatorios/campanhas", "token_env": "TOKEN_API_TESTE", "url_base": "mock",
         "token_padrao_mock": "token-da-api-simulada", "janela_dias": 31, "por_pagina": 10, "tentativas": 6,
         "espera_inicial_s": 0.001, "timeout_s": 5}


def _linhas(n):
    return [{"campaign": {"id": "1", "name": "C"}, "segments": {"date": f"2025-01-{(i % 28) + 1:02d}"},
             "metrics": {"impressions": "10", "clicks": "1", "costMicros": "1000000", "conversions": 0.0}} for i in range(n)]


def _contexto(servidor):
    return {"url_api": url_de(servidor), "inicio": pd.Timestamp("2025-01-01"), "fim": pd.Timestamp("2025-01-31"),
            "metricas_api": {"requisicoes": 0, "novas_tentativas": 0}}


def test_janelas_cobrem_o_periodo_sem_sobrepor():
    assert janelas(pd.Timestamp("2025-01-01"), pd.Timestamp("2025-02-10"), 31) == [("2025-01-01", "2025-01-31"), ("2025-02-01", "2025-02-10")]


def test_pagina_e_sobrevive_a_429_e_500():
    servidor = iniciar_servidor(a_cada_429=3, a_cada_500=4, linhas=_linhas(45))
    contexto = _contexto(servidor)
    df = ler_api(FONTE, contexto)
    servidor.shutdown()
    assert len(df) == 45                                          # 5 páginas, sem perder nem repetir linhas
    assert "metrics_costMicros" in df.columns                     # JSON aninhado achatado
    assert contexto["metricas_api"]["novas_tentativas"] > 0


def test_token_invalido_falha_sem_tentar_de_novo(monkeypatch):
    monkeypatch.setenv("TOKEN_API_TESTE", "errado")
    servidor = iniciar_servidor(a_cada_429=10**6, a_cada_500=10**6, linhas=_linhas(5))
    contexto = _contexto(servidor)
    with pytest.raises(ErroDeApi, match="401"):
        ler_api(FONTE, contexto)
    servidor.shutdown()
    assert contexto["metricas_api"]["requisicoes"] == 1


def test_desiste_depois_do_limite_de_tentativas():
    servidor = iniciar_servidor(a_cada_429=1, a_cada_500=10**6, linhas=_linhas(5))   # sempre 429
    contexto = _contexto(servidor)
    with pytest.raises(ErroDeApi, match="tentativas"):
        ler_api(dict(FONTE, tentativas=3), contexto)
    servidor.shutdown()
