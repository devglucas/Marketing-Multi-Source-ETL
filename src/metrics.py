"""
Marts de marketing: as tabelas que respondem às perguntas do negócio.

Definições usadas (todas sobre pedidos pagos e receita líquida de frete):
    CPA   gasto / pedidos atribuídos
    CAC   gasto / clientes novos atribuídos (o primeiro pedido pago do cliente)
    ROAS  receita atribuída / gasto
    LTV   receita acumulada por cliente N dias depois do primeiro pedido
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ETAPAS = ["sessoes", "add_to_cart", "begin_checkout", "purchase"]


def _razao(numerador: pd.Series, denominador: pd.Series) -> pd.Series:
    """Divisão que devolve vazio, e não infinito, quando não há denominador (canal sem gasto, por exemplo)."""
    return (numerador / denominador.replace(0, np.nan)).astype(float)


def funil_por_canal(sessoes: pd.DataFrame) -> pd.DataFrame:
    funil = sessoes.groupby("canal", as_index=False).agg(
        sessoes=("session_id", "size"), add_to_cart=("add_to_cart", "sum"), begin_checkout=("begin_checkout", "sum"),
        purchase=("purchase", "sum"))
    return funil.assign(taxa_carrinho=_razao(funil["add_to_cart"], funil["sessoes"]),
                        taxa_checkout=_razao(funil["begin_checkout"], funil["add_to_cart"]),
                        taxa_compra=_razao(funil["purchase"], funil["begin_checkout"]),
                        conversao=_razao(funil["purchase"], funil["sessoes"])).sort_values("sessoes", ascending=False)


def primeiros_pedidos(pagos: pd.DataFrame) -> pd.DataFrame:
    return pagos.sort_values("momento", kind="stable").drop_duplicates("cliente_id")


def desempenho(atribuicao: pd.DataFrame, gasto: pd.DataFrame, pagos: pd.DataFrame, modelo: str, chave: str) -> pd.DataFrame:
    """Métricas de eficiência por canal ou campanha, em um modelo de atribuição."""
    credito = atribuicao[atribuicao["modelo"] == modelo]
    novos = primeiros_pedidos(pagos)["pedido_id"]
    tabela = credito.groupby(chave, as_index=False).agg(pedidos=("credito", "sum"), receita=("receita_atribuida", "sum"))
    clientes_novos = credito[credito["pedido_id"].isin(novos)].groupby(chave)["credito"].sum()
    tabela = tabela.merge(gasto.groupby(chave, as_index=False)["custo"].sum().rename(columns={"custo": "gasto"}), on=chave, how="outer")
    tabela = tabela.fillna({"pedidos": 0.0, "receita": 0.0, "gasto": 0.0})
    tabela["clientes_novos"] = tabela[chave].map(clientes_novos).fillna(0.0)
    pago = tabela["gasto"].where(tabela["gasto"] > 0)    # canal sem gasto não tem CAC zero: a métrica não se aplica
    return tabela.assign(cpa=_razao(pago, tabela["pedidos"]), cac=_razao(pago, tabela["clientes_novos"]),
                         roas=_razao(tabela["receita"], tabela["gasto"])).sort_values("receita", ascending=False, ignore_index=True)


def comparar_modelos(atribuicao: pd.DataFrame) -> pd.DataFrame:
    """Pedidos creditados a cada canal em cada modelo."""
    return atribuicao.pivot_table(index="canal", columns="modelo", values="credito", aggfunc="sum", fill_value=0.0).reset_index()


def roas_por_modelo(atribuicao: pd.DataFrame, gasto: pd.DataFrame) -> pd.DataFrame:
    """O ROAS de cada canal pago muda conforme o modelo: a decisão de verba depende dessa escolha."""
    receita = atribuicao.pivot_table(index="canal", columns="modelo", values="receita_atribuida", aggfunc="sum")
    custo = gasto.groupby("canal")["custo"].sum()
    return receita.loc[custo.index].div(custo, axis=0).reset_index().rename_axis(columns=None)


def plataforma_vs_atribuido(gasto: pd.DataFrame, atribuicao: pd.DataFrame, modelo: str, pedidos_reais: int) -> pd.DataFrame:
    """Cada plataforma reivindica as conversões que tocou. A soma passa do total real de pedidos."""
    declarado = gasto[gasto["plataforma"] != "email"].groupby("canal", as_index=False).agg(
        plataforma=("plataforma", "first"), conversoes_declaradas=("conversoes_plataforma", "sum"))
    atribuido = atribuicao[atribuicao["modelo"] == modelo].groupby("canal")["credito"].sum()
    tabela = declarado.assign(pedidos_atribuidos=declarado["canal"].map(atribuido))
    return tabela.assign(excesso=_razao(tabela["conversoes_declaradas"], tabela["pedidos_atribuidos"]) - 1, pedidos_reais=pedidos_reais)


def serie_mensal(gasto: pd.DataFrame, pagos: pd.DataFrame) -> pd.DataFrame:
    mensal = gasto.groupby("ano_mes", as_index=False)["custo"].sum().rename(columns={"custo": "gasto"}).merge(
        pagos.groupby("ano_mes", as_index=False).agg(pedidos=("pedido_id", "size"), receita=("receita_liquida", "sum")), on="ano_mes")
    novos = primeiros_pedidos(pagos).groupby("ano_mes").size()
    mensal = mensal.assign(receita=mensal["receita"].astype(float), clientes_novos=mensal["ano_mes"].map(novos))
    return mensal.assign(cac=_razao(mensal["gasto"], mensal["clientes_novos"]), roas=_razao(mensal["receita"], mensal["gasto"]))


def base_ltv(pagos: pd.DataFrame, atribuicao: pd.DataFrame, modelo: str) -> pd.DataFrame:
    """Uma linha por pedido, com a data do primeiro pedido, a coorte e o canal de aquisição do cliente."""
    primeiros = primeiros_pedidos(pagos)
    canal = atribuicao[atribuicao["modelo"] == modelo].sort_values("credito", ascending=False).drop_duplicates("pedido_id")
    aquisicao = primeiros[["cliente_id", "pedido_id", "momento", "ano_mes"]].rename(columns={"momento": "primeira_compra", "ano_mes": "coorte"})
    aquisicao = aquisicao.merge(canal[["pedido_id", "canal"]], on="pedido_id", how="left").drop(columns="pedido_id")
    base = pagos[["cliente_id", "momento", "receita_liquida"]].merge(aquisicao, on="cliente_id")
    return base.assign(dias=(base["momento"] - base["primeira_compra"]).dt.days, receita_liquida=base["receita_liquida"].astype(float))


def ltv(base: pd.DataFrame, marcos: list[int], fim: pd.Timestamp, chave: str) -> pd.DataFrame:
    """
    LTV acumulado por marco. Só entra no marco a coorte inteiramente observada: se o último
    cliente do mês ainda não completou N dias até o fim dos dados, a coorte fica de fora,
    porque o valor dela estaria artificialmente baixo.
    """
    fim_coorte = pd.PeriodIndex(base["coorte"], freq="M").end_time.tz_localize("UTC").normalize()
    linhas = []
    for marco in marcos:
        elegiveis = base[fim_coorte + pd.Timedelta(days=marco) <= fim]
        clientes = elegiveis.groupby(chave)["cliente_id"].nunique()
        receita = elegiveis[elegiveis["dias"] <= marco].groupby(chave)["receita_liquida"].sum()
        linhas.append(pd.DataFrame({"marco_dias": marco, "clientes": clientes, "ltv": receita / clientes}).reset_index())
    return pd.concat(linhas, ignore_index=True)


def construir_marts(curado: dict, atribuicao: pd.DataFrame, config) -> dict[str, pd.DataFrame]:
    pagos = curado["pedidos"][curado["pedidos"]["valido"]]
    gasto = curado["gasto_midia"]
    modelo = config.atribuicao["modelo_padrao"]
    fim = pd.Timestamp(config.fim, tz="UTC") + pd.Timedelta(days=1)
    base = base_ltv(pagos, atribuicao, modelo)
    canal = desempenho(atribuicao, gasto, pagos, modelo, "canal")
    ltv_canal = ltv(base, config.ltv["marcos_dias"], fim, "canal")
    ltv_cac = ltv_canal.merge(canal[["canal", "cac"]], on="canal", how="left")
    return {
        "funil_canal": funil_por_canal(curado["sessoes"]),
        "desempenho_canal": canal,
        "desempenho_campanha": desempenho(atribuicao, gasto, pagos, modelo, "campanha"),
        "comparacao_modelos": comparar_modelos(atribuicao),
        "roas_por_modelo": roas_por_modelo(atribuicao, gasto),
        "plataforma_vs_atribuido": plataforma_vs_atribuido(gasto, atribuicao, modelo, len(pagos)),
        "serie_mensal": serie_mensal(gasto, pagos),
        "ltv_coorte": ltv(base, config.ltv["marcos_dias"], fim, "coorte"),
        "ltv_canal": ltv_cac.assign(ltv_cac=_razao(ltv_cac["ltv"], ltv_cac["cac"])),
    }
