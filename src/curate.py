"""
Camada curada: cada fonte vira tabelas limpas, tipadas e comparáveis.

- gasto_midia unifica Google (API), Meta (Excel) e e-mail (CSV) em um único formato
- sessoes classifica o canal pelas UTMs e remove robôs e homologação
- pedidos remove testes e duplicados e calcula a receita líquida
"""

from __future__ import annotations

import pandas as pd

from src.settings import Configuracao
from src.utils import configurar_logger, parse_numero

log = configurar_logger("curate")

COLUNAS_GASTO = ["data", "plataforma", "canal", "campanha", "objetivo", "impressoes", "cliques", "custo",
                 "conversoes_plataforma", "ano_mes"]


def classificar_canal(fonte: pd.Series, meio: pd.Series, canais: dict) -> pd.Series:
    """Aplica as regras do YAML em ordem. Sem UTM = direto; UTM fora das regras = outros."""
    f, m = fonte.astype("string").str.strip().str.lower(), meio.astype("string").str.strip().str.lower()
    canal = pd.Series(pd.NA, index=fonte.index, dtype="string")
    for regra in canais["regras"]:
        casa = pd.Series(True, index=fonte.index)
        if "fonte" in regra:
            casa &= f.str.contains(regra["fonte"], regex=True, na=False)
        if "meio" in regra:
            casa &= m.str.contains(regra["meio"], regex=True, na=False)
        canal = canal.mask(canal.isna() & casa, regra["canal"])
    sem_utm = f.isna() & m.isna()
    return canal.mask(canal.isna() & sem_utm, canais["canal_sem_utm"]).fillna(canais["canal_desconhecido"])


def normalizar_campanha(serie: pd.Series) -> pd.Series:
    return serie.astype("string").str.strip().str.upper()


def objetivo_da_campanha(campanha: pd.Series) -> pd.Series:
    """Padrão de nomes da empresa: BR_<OBJETIVO>_... ; newsletters são NEWS_..."""
    objetivo = campanha.str.extract(r"^BR_(BRAND|PROSP|REMARK)_", expand=False).str.lower()
    return objetivo.mask(campanha.str.startswith("NEWS_", na=False), "newsletter").fillna("outros")


def curar_sessoes(df: pd.DataFrame, config: Configuracao) -> tuple[pd.DataFrame, pd.DataFrame]:
    regras = config.regras
    homologacao = df["hostname"] != regras["hostname_producao"]
    momento = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    limpas = df.assign(momento=momento, dia=momento.dt.strftime("%Y-%m-%d"))

    por_dia = limpas.groupby(["visitor_id", "dia"])["session_id"].transform("size")
    robos = limpas.loc[por_dia > regras["sessoes_por_dia_robo"], "visitor_id"].unique()
    e_robo = limpas["visitor_id"].isin(robos)
    duplicada = limpas.duplicated("session_id")
    quarentena = pd.concat([
        pd.DataFrame({"tabela": "sessoes", "motivo": "homologacao", "chave": limpas.loc[homologacao, "session_id"]}),
        pd.DataFrame({"tabela": "sessoes", "motivo": "robo", "chave": limpas.loc[e_robo, "session_id"]}),
        pd.DataFrame({"tabela": "sessoes", "motivo": "duplicada", "chave": limpas.loc[duplicada, "session_id"]}),
    ])
    limpas = limpas.loc[~(homologacao | e_robo | duplicada)]

    curadas = pd.DataFrame({
        "session_id": limpas["session_id"], "visitor_id": limpas["visitor_id"], "momento": limpas["momento"],
        "canal": classificar_canal(limpas["utm_source"], limpas["utm_medium"], config.canais),
        "fonte": limpas["utm_source"].astype("string").str.strip().str.lower(),
        "meio": limpas["utm_medium"].astype("string").str.strip().str.lower(),
        "campanha": normalizar_campanha(limpas["utm_campaign"]),
        "device": limpas["device"], "pageviews": limpas["pageviews"].astype("int32"),
        "add_to_cart": limpas["add_to_cart"].astype(bool), "begin_checkout": limpas["begin_checkout"].astype(bool),
        "purchase": limpas["purchase"].astype(bool), "ano_mes": limpas["momento"].dt.strftime("%Y-%m"),
    })
    return curadas, quarentena


def curar_pedidos(df: pd.DataFrame, config: Configuracao) -> tuple[pd.DataFrame, pd.DataFrame]:
    regras = config.regras
    valores = {c: pd.to_numeric(df[c]) for c in ["valor_produtos", "desconto", "frete"]}
    limpos = df.assign(**valores)
    teste = limpos["cliente_id"].eq(regras["cliente_teste"]) | limpos["valor_produtos"].lt(regras["valor_minimo_pedido"])
    duplicado = limpos.duplicated("pedido_id")
    quarentena = pd.concat([
        pd.DataFrame({"tabela": "pedidos", "motivo": "pedido_de_teste", "chave": limpos.loc[teste, "pedido_id"]}),
        pd.DataFrame({"tabela": "pedidos", "motivo": "duplicado", "chave": limpos.loc[duplicado & ~teste, "pedido_id"]}),
    ])
    limpos = limpos.loc[~(teste | duplicado)]
    momento = pd.to_datetime(limpos["criado_em"], format="%Y-%m-%d %H:%M:%S").dt.tz_localize("UTC")
    curados = limpos.assign(momento=momento, receita_liquida=(limpos["valor_produtos"] - limpos["desconto"]).round(2),
                            valido=limpos["status"].isin(regras["status_receita"]), ano_mes=momento.dt.strftime("%Y-%m"))
    return curados[["pedido_id", "cliente_id", "visitor_id", "momento", "valor_produtos", "desconto", "frete", "receita_liquida",
                    "status", "valido", "ano_mes"]], quarentena


def gasto_google(df: pd.DataFrame) -> pd.DataFrame:
    campanha = normalizar_campanha(df["campaign_name"])
    return pd.DataFrame({
        "data": pd.to_datetime(df["segments_date"]), "plataforma": "google_ads", "canal": "paid_search", "campanha": campanha,
        "impressoes": pd.to_numeric(df["metrics_impressions"]), "cliques": pd.to_numeric(df["metrics_clicks"]),
        "custo": pd.to_numeric(df["metrics_costMicros"]) / 1_000_000,   # a API informa o custo em milionésimos
        "conversoes_plataforma": pd.to_numeric(df["metrics_conversions"]),
    })


def gasto_meta(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa as linhas de total de cada aba, usadas como controle: a soma precisa bater com elas."""
    total = df["Dia"].astype("string").str.lower().eq("total")
    custo = parse_numero(df["Valor usado (BRL)"])
    linhas = df.loc[~total]
    gasto = pd.DataFrame({
        "data": pd.to_datetime(linhas["Dia"]), "plataforma": "meta_ads", "canal": "paid_social",
        "campanha": normalizar_campanha(linhas["Nome da campanha"]),
        "impressoes": pd.to_numeric(linhas["Impressões"]), "cliques": pd.to_numeric(linhas["Cliques no link"]),
        "custo": custo[~total], "conversoes_plataforma": pd.to_numeric(linhas["Compras"]),
    })
    controle = pd.DataFrame({"aba": df.loc[total, "_origem"], "total_planilha": custo[total]}).merge(
        gasto.assign(aba=linhas["_origem"]).groupby("aba", as_index=False)["custo"].sum(), on="aba")
    return gasto, controle.assign(diferenca=lambda d: (d["total_planilha"] - d["custo"]).round(2))


def gasto_email(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "data": pd.to_datetime(df["data_envio"], format="%d/%m/%Y"), "plataforma": "email", "canal": "email",
        "campanha": normalizar_campanha(df["campanha"]), "impressoes": pd.to_numeric(df["entregues"]),
        "cliques": pd.to_numeric(df["cliques"]), "custo": parse_numero(df["custo_brl"]), "conversoes_plataforma": 0.0,
    })


def curar(landing: dict[str, pd.DataFrame], config: Configuracao) -> dict:
    sessoes, q_sessoes = curar_sessoes(landing["sessoes"], config)
    pedidos, q_pedidos = curar_pedidos(landing["pedidos"], config)
    meta, controle_meta = gasto_meta(landing["meta_ads"])
    gasto = pd.concat([gasto_google(landing["google_ads"]), meta, gasto_email(landing["email"])], ignore_index=True)
    gasto = gasto.assign(objetivo=objetivo_da_campanha(gasto["campanha"]), ano_mes=gasto["data"].dt.strftime("%Y-%m"))[COLUNAS_GASTO]
    clientes = landing["clientes"].assign(cadastrado_em=lambda d: pd.to_datetime(d["cadastrado_em"]))[["cliente_id", "uf", "cadastrado_em"]]
    quarentena = pd.concat([q_sessoes, q_pedidos], ignore_index=True)
    log.info("sessões %d | pedidos %d | gasto R$ %.2f | quarentena %s", len(sessoes), len(pedidos), gasto["custo"].sum(),
             quarentena.groupby(["tabela", "motivo"]).size().to_dict())
    return {"sessoes": sessoes, "pedidos": pedidos, "gasto_midia": gasto, "clientes": clientes, "quarentena": quarentena,
            "controle_meta": controle_meta}
