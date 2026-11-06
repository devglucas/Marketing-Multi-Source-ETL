import pandas as pd
import pytest

from src.metrics import base_ltv, desempenho, funil_por_canal, ltv, plataforma_vs_atribuido, primeiros_pedidos, roas_por_modelo


def _pagos():
    df = pd.DataFrame({"pedido_id": ["P1", "P2", "P3"], "cliente_id": ["A", "A", "B"],
                       "momento": ["2025-01-10", "2025-02-01", "2025-05-20"], "receita_liquida": [100.0, 50.0, 80.0],
                       "ano_mes": ["2025-01", "2025-02", "2025-05"]})
    return df.assign(momento=pd.to_datetime(df["momento"], utc=True))


def _atribuicao():
    return pd.DataFrame({"pedido_id": ["P1", "P2", "P3"], "modelo": "m", "canal": ["email", "email", "organic"],
                         "campanha": ["X", "X", "(sem campanha)"], "credito": 1.0, "receita_atribuida": [100.0, 50.0, 80.0]})


def _gasto():
    return pd.DataFrame({"canal": ["email"], "campanha": ["X"], "custo": [30.0], "plataforma": ["email"], "conversoes_plataforma": [0.0]})


def test_primeiro_pedido_define_cliente_novo():
    assert primeiros_pedidos(_pagos())["pedido_id"].tolist() == ["P1", "P3"]


def test_desempenho_calcula_cpa_cac_e_roas():
    t = desempenho(_atribuicao(), _gasto(), _pagos(), "m", "canal").set_index("canal")
    assert t.loc["email", "cpa"] == 15 and t.loc["email", "cac"] == 30 and t.loc["email", "roas"] == 5


def test_canal_sem_gasto_nao_tem_cac_zero():
    t = desempenho(_atribuicao(), _gasto(), _pagos(), "m", "canal").set_index("canal")
    assert pd.isna(t.loc["organic", "cac"]) and pd.isna(t.loc["organic", "roas"])


def test_ltv_acumula_ate_o_marco_por_cliente():
    base = base_ltv(_pagos(), _atribuicao(), "m")
    t = ltv(base, [30], pd.Timestamp("2025-07-01", tz="UTC"), "coorte").set_index("coorte")
    assert t.loc["2025-01", "ltv"] == 150           # a recompra aconteceu 22 dias depois


def test_coorte_nao_observada_por_inteiro_fica_fora_do_marco():
    base = base_ltv(_pagos(), _atribuicao(), "m")
    t = ltv(base, [60], pd.Timestamp("2025-07-01", tz="UTC"), "coorte")
    assert t["coorte"].tolist() == ["2025-01"]      # maio + 60 dias passa do fim dos dados


def test_funil_calcula_as_taxas_em_cada_etapa():
    s = pd.DataFrame({"session_id": list("abcd"), "canal": "email", "add_to_cart": [True, True, False, False],
                      "begin_checkout": [True, False, False, False], "purchase": [True, False, False, False]})
    f = funil_por_canal(s).iloc[0]
    assert (f["taxa_carrinho"], f["taxa_checkout"], f["conversao"]) == (0.5, 0.5, 0.25)


def test_excesso_compara_o_declarado_com_o_atribuido():
    gasto = pd.DataFrame({"canal": ["paid_search"], "plataforma": ["google_ads"], "conversoes_plataforma": [30.0]})
    atrib = pd.DataFrame({"modelo": "m", "canal": ["paid_search"], "credito": [10.0]})
    assert plataforma_vs_atribuido(gasto, atrib, "m", 10)["excesso"].iat[0] == pytest.approx(2.0)


def test_roas_por_modelo_so_para_canais_com_gasto():
    t = roas_por_modelo(_atribuicao(), _gasto())
    assert t["canal"].tolist() == ["email"] and t["m"].iat[0] == 5
