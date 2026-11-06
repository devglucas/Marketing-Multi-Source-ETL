import pandas as pd

from src.curate import classificar_canal, curar_pedidos, curar_sessoes, gasto_google, gasto_meta, objetivo_da_campanha
from src.settings import carregar

CONFIG = carregar()


def test_canal_pelas_utms():
    fonte = pd.Series(["Google", "ig", "newsletter", None, "google", "blogx.com", "tv"])
    meio = pd.Series(["CPC", "cpc", "e-mail", None, "organic", "Referral", "offline"])
    assert classificar_canal(fonte, meio, CONFIG.canais).tolist() == [
        "paid_search", "paid_social", "email", "direct", "organic", "referral", "outros"]


def test_objetivo_pelo_padrao_de_nomes():
    assert objetivo_da_campanha(pd.Series(["BR_PROSP_IG_X", "BR_BRAND_SEARCH", "NEWS_2025_S01", "PROMO"], dtype="string")).tolist() == [
        "prosp", "brand", "newsletter", "outros"]


def _sessao(sid, visitante, host="www.auracosmeticos.com.br", ts="2025-02-10T10:00:00Z"):
    return {"session_id": sid, "visitor_id": visitante, "ts": ts, "hostname": host, "utm_source": None, "utm_medium": None,
            "utm_campaign": None, "device": "mobile", "pageviews": 1, "add_to_cart": False, "begin_checkout": False, "purchase": False}


def test_sessoes_removem_robos_e_homologacao():
    robo = [_sessao(f"b{i}", "bot") for i in range(40)]
    df = pd.DataFrame([_sessao("s1", "v1"), _sessao("s2", "v2", host="homolog.auracosmeticos.com.br"), *robo])
    curadas, quarentena = curar_sessoes(df, CONFIG)
    assert curadas["session_id"].tolist() == ["s1"]
    assert quarentena["motivo"].value_counts().to_dict() == {"robo": 40, "homologacao": 1}


def test_pedidos_removem_teste_e_duplicado_e_calculam_receita():
    df = pd.DataFrame({"pedido_id": ["P1", "P1", "T1", "P2"], "cliente_id": ["C1", "C1", "C999999", "C2"], "visitor_id": ["v", "v", None, "w"],
                       "criado_em": ["2025-01-05 10:00:00"] * 4, "valor_produtos": ["100", "100", "0.01", "50"],
                       "desconto": ["10", "10", "0", "0"], "frete": ["0", "0", "0", "5"], "status": ["pago", "pago", "pago", "cancelado"]})
    curados, _ = curar_pedidos(df, CONFIG)
    assert curados["pedido_id"].tolist() == ["P1", "P2"]
    assert curados["receita_liquida"].tolist() == [90.0, 50.0] and curados["valido"].tolist() == [True, False]


def test_custo_da_api_vem_em_micros():
    df = pd.DataFrame({"campaign_name": ["BR_BRAND_SEARCH"], "segments_date": ["2025-01-01"], "metrics_impressions": ["10"],
                       "metrics_clicks": ["2"], "metrics_costMicros": ["1500000"], "metrics_conversions": [1.0]})
    assert gasto_google(df)["custo"].iat[0] == 1.5


def test_meta_separa_total_e_confere_com_a_soma():
    df = pd.DataFrame({"Dia": ["2025-01-01", "2025-01-02", "Total"], "Nome da campanha": ["a", "b", None], "Impressões": [1, 1, 2],
                       "Cliques no link": [1, 1, 2], "Valor usado (BRL)": [10.0, "R$ 1.000,50", 1010.5], "Compras": [0, 0, 0],
                       "_origem": ["2025-01"] * 3})
    gasto, controle = gasto_meta(df)
    assert gasto["custo"].tolist() == [10.0, 1000.5]
    assert controle["diferenca"].iat[0] == 0
