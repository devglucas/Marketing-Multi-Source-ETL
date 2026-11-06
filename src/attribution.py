"""
Atribuição multi-touch: quanto de cada pedido vai para cada canal.

Um pedido costuma ter várias sessões antes da compra. Cada modelo responde de um jeito
diferente, e essa é a utilidade de comparar:

    ultimo_clique      tudo para a última sessão, inclusive direto
    ultimo_nao_direto  tudo para a última sessão que não seja direto (modelo padrão)
    primeiro_clique    tudo para a primeira sessão da janela
    linear             partes iguais entre as sessões
    decaimento_tempo   mais peso para quem está perto da compra (meia-vida configurável)

Regra que sustenta tudo: em qualquer modelo, os créditos de um pedido somam exatamente 1.
Pedido sem visitante ou sem sessão na janela entra como nao_atribuido, para a receita fechar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

NAO_ATRIBUIDO = "nao_atribuido"
DIRETO = "direct"
MODELOS = ["ultimo_nao_direto", "ultimo_clique", "primeiro_clique", "linear", "decaimento_tempo"]


def pontos_de_contato(pedidos: pd.DataFrame, sessoes: pd.DataFrame, janela_dias: int) -> pd.DataFrame:
    """Sessões do mesmo visitante nos N dias anteriores ao pedido, em ordem cronológica."""
    base = pedidos.loc[pedidos["visitor_id"].notna(), ["pedido_id", "visitor_id", "momento"]].rename(columns={"momento": "momento_pedido"})
    toques = base.merge(sessoes[["visitor_id", "momento", "canal", "campanha"]], on="visitor_id")
    dias = (toques["momento_pedido"] - toques["momento"]).dt.total_seconds() / 86_400
    toques = toques.assign(dias_ate_pedido=dias).loc[(dias >= 0) & (dias <= janela_dias)]
    return toques.sort_values(["pedido_id", "momento"], kind="stable").reset_index(drop=True)


def _peso_unico(toques: pd.DataFrame, indices: pd.Index) -> pd.Series:
    return pd.Series(0.0, index=toques.index).where(~toques.index.isin(indices), 1.0)


def pesos(toques: pd.DataFrame, modelo: str, meia_vida_dias: float) -> pd.Series:
    grupos = toques.groupby("pedido_id", sort=False)
    if modelo == "ultimo_clique":
        return _peso_unico(toques, grupos.tail(1).index)
    if modelo == "primeiro_clique":
        return _peso_unico(toques, grupos.head(1).index)
    if modelo == "linear":
        return 1 / grupos["canal"].transform("size")
    if modelo == "decaimento_tempo":
        bruto = np.power(0.5, toques["dias_ate_pedido"] / meia_vida_dias)
        return bruto / bruto.groupby(toques["pedido_id"]).transform("sum")
    if modelo == "ultimo_nao_direto":
        ultimos_nao_diretos = toques[toques["canal"] != DIRETO].groupby("pedido_id", sort=False).tail(1)
        so_direto = toques[~toques["pedido_id"].isin(ultimos_nao_diretos["pedido_id"])].groupby("pedido_id", sort=False).tail(1)
        return _peso_unico(toques, ultimos_nao_diretos.index.union(so_direto.index))
    raise ValueError(f"modelo de atribuição desconhecido: {modelo}")


def atribuir(pedidos: pd.DataFrame, sessoes: pd.DataFrame, janela_dias: int, meia_vida_dias: float) -> pd.DataFrame:
    """Uma linha por pedido, modelo, canal e campanha, com o crédito e a receita correspondente."""
    toques = pontos_de_contato(pedidos, sessoes, janela_dias)
    receita = pedidos.set_index("pedido_id")["receita_liquida"].astype(float)
    sem_toque = pedidos.loc[~pedidos["pedido_id"].isin(toques["pedido_id"]), "pedido_id"]

    partes = []
    for modelo in MODELOS:
        creditos = toques.assign(credito=pesos(toques, modelo, meia_vida_dias), campanha=toques["campanha"].fillna("(sem campanha)"))
        creditos = creditos[creditos["credito"] > 0].groupby(["pedido_id", "canal", "campanha"], as_index=False)["credito"].sum()
        orfaos = pd.DataFrame({"pedido_id": sem_toque.to_numpy(), "canal": NAO_ATRIBUIDO, "campanha": "(sem campanha)", "credito": 1.0})
        partes.append(pd.concat([creditos, orfaos], ignore_index=True).assign(modelo=modelo))
    resultado = pd.concat(partes, ignore_index=True)
    resultado["receita_atribuida"] = resultado["credito"] * resultado["pedido_id"].map(receita)
    return resultado[["pedido_id", "modelo", "canal", "campanha", "credito", "receita_atribuida"]]
