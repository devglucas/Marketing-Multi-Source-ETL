"""
Verificações do pipeline. Críticas interrompem a publicação; alertas ficam registrados no relatório.

A ideia central é conciliar: cada número final é comparado com outra origem independente
(a planilha, a fonte bruta, o gabarito do gerador ou uma identidade matemática).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.settings import ROOT_DIR

TOLERANCIA = 0.01


def _item(nome: str, severidade: str, ok: bool, detalhe: str) -> dict:
    return {"verificacao": nome, "severidade": severidade, "ok": bool(ok), "detalhe": detalhe}


def verificar_atribuicao(atribuicao: pd.DataFrame, pagos: pd.DataFrame) -> list[dict]:
    receita = float(pagos["receita_liquida"].sum())
    por_modelo = atribuicao.groupby("modelo")["receita_atribuida"].sum()
    maior_erro = float((por_modelo - receita).abs().max())
    creditos = atribuicao.groupby(["modelo", "pedido_id"])["credito"].sum()
    desvio = float((creditos - 1).abs().max())
    pedidos = atribuicao.groupby("modelo")["pedido_id"].nunique()
    return [
        _item("receita atribuída fecha com a receita paga em todos os modelos", "critica", maior_erro < TOLERANCIA, f"maior diferença: {maior_erro:.4f}"),
        _item("créditos de cada pedido somam 1", "critica", desvio < 1e-9, f"maior desvio: {desvio:.2e}"),
        _item("todo pedido pago aparece em todos os modelos", "critica", (pedidos == len(pagos)).all(), f"{len(pagos)} pedidos"),
    ]


def verificar_curado(curado: dict, landing: dict, config) -> list[dict]:
    sessoes, pedidos, gasto = curado["sessoes"], curado["pedidos"], curado["gasto_midia"]
    google_bruto = pd.to_numeric(landing["google_ads"]["metrics_costMicros"]).sum() / 1_000_000
    google = gasto.loc[gasto["plataforma"] == "google_ads", "custo"].sum()
    controle = curado["controle_meta"]
    pagas = sessoes.loc[sessoes["canal"].isin(["paid_search", "paid_social"]) & sessoes["campanha"].notna(), "campanha"]
    orfas = pagas[~pagas.isin(gasto["campanha"])]
    fora = ~sessoes["momento"].dt.tz_localize(None).dt.normalize().between(config.inicio, config.fim)
    return [
        _item("session_id único", "critica", sessoes["session_id"].is_unique, f"{len(sessoes)} sessões"),
        _item("pedido_id único", "critica", pedidos["pedido_id"].is_unique, f"{len(pedidos)} pedidos"),
        _item("gasto do Google igual ao bruto da API", "critica", abs(google - google_bruto) < TOLERANCIA, f"R$ {google:.2f}"),
        _item("gasto da Meta igual às linhas de total da planilha", "critica", controle["diferenca"].abs().max() < TOLERANCIA,
              f"{len(controle)} abas conferidas"),
        _item("nenhum gasto negativo", "critica", (gasto["custo"] >= 0).all(), f"{len(gasto)} linhas"),
        _item("sessões pagas têm campanha com gasto", "alerta", orfas.empty, f"{len(orfas)} sessões sem gasto correspondente"),
        _item("sessões dentro do período", "alerta", not fora.any(), f"{int(fora.sum())} fora do período"),
    ]


def verificar_gabarito(curado: dict, caminho: Path = ROOT_DIR / "data" / "external" / "gabarito.json") -> list[dict]:
    """O gerador grava os valores verdadeiros: confirma que a limpeza recuperou exatamente o que foi sujado."""
    if not caminho.exists():
        return []
    gabarito = json.loads(caminho.read_text(encoding="utf-8"))
    pagos = curado["pedidos"][curado["pedidos"]["valido"]]
    gasto = curado["gasto_midia"].groupby("plataforma")["custo"].sum()
    robos = (curado["quarentena"]["motivo"] == "robo").sum()
    comparacoes = {
        "pedidos_pagos": len(pagos), "receita_paga": float(pagos["receita_liquida"].sum()), "sessoes_validas": len(curado["sessoes"]),
        "sessoes_robo": int(robos), "clientes": len(curado["clientes"]), "gasto_google": gasto["google_ads"],
        "gasto_meta": gasto["meta_ads"], "gasto_email": gasto["email"],
    }
    return [_item(f"gabarito: {nome}", "critica", abs(valor - gabarito[nome]) < TOLERANCIA, f"{valor:.2f} x {gabarito[nome]:.2f}")
            for nome, valor in comparacoes.items()]


def verificar_fontes(ocorrencias: list[dict]) -> list[dict]:
    """Mudança de schema tratada pelo contrato não falha a carga, mas precisa ser vista por alguém."""
    return [_item(f"schema estável em {o['fonte']}", "alerta", False, f"{o['tipo']}: {o['detalhe']}") for o in ocorrencias]


def verificar_plataformas(tabela: pd.DataFrame, pedidos_reais: int) -> list[dict]:
    declarado = float(tabela["conversoes_declaradas"].sum())
    return [_item("conversões declaradas pelas plataformas cabem no total de pedidos", "alerta", declarado <= pedidos_reais,
                  f"{declarado:.0f} declaradas para {pedidos_reais} pedidos reais")]


def falhas_criticas(verificacoes: list[dict]) -> list[dict]:
    return [v for v in verificacoes if v["severidade"] == "critica" and not v["ok"]]
