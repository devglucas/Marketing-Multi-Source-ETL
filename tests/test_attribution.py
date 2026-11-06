import pandas as pd
import pytest

from src.attribution import MODELOS, NAO_ATRIBUIDO, atribuir, pontos_de_contato


def _sessoes(*linhas):
    df = pd.DataFrame(linhas, columns=["visitor_id", "momento", "canal", "campanha"])
    return df.assign(momento=pd.to_datetime(df["momento"], utc=True))


def _pedidos(*linhas):
    df = pd.DataFrame(linhas, columns=["pedido_id", "visitor_id", "momento", "receita_liquida"])
    return df.assign(momento=pd.to_datetime(df["momento"], utc=True))


SESSOES = _sessoes(("v", "2025-03-01", "paid_social", "A"), ("v", "2025-03-09", "email", "B"), ("v", "2025-03-10", "direct", None))
PEDIDOS = _pedidos(("P1", "v", "2025-03-10 12:00", 100.0))


def _canais(modelo):
    r = atribuir(PEDIDOS, SESSOES, 30, 7)
    return r[r["modelo"] == modelo].set_index("canal")["credito"].to_dict()


def test_ultimo_clique_conta_o_direto():
    assert _canais("ultimo_clique") == {"direct": 1.0}


def test_ultimo_nao_direto_ignora_o_direto():
    assert _canais("ultimo_nao_direto") == {"email": 1.0}


def test_primeiro_clique():
    assert _canais("primeiro_clique") == {"paid_social": 1.0}


def test_linear_divide_igualmente():
    assert _canais("linear") == pytest.approx({"paid_social": 1 / 3, "email": 1 / 3, "direct": 1 / 3})


def test_decaimento_favorece_quem_esta_perto_da_compra():
    canais = _canais("decaimento_tempo")
    assert canais["direct"] > canais["email"] > canais["paid_social"]


def test_so_direto_fica_com_direto_no_ultimo_nao_direto():
    r = atribuir(PEDIDOS, _sessoes(("v", "2025-03-09", "direct", None)), 30, 7)
    assert r[r["modelo"] == "ultimo_nao_direto"]["canal"].tolist() == ["direct"]


def test_sessao_fora_da_janela_ou_depois_do_pedido_nao_conta():
    sessoes = _sessoes(("v", "2025-01-01", "email", "X"), ("v", "2025-03-20", "email", "Y"))
    assert pontos_de_contato(PEDIDOS, sessoes, 30).empty


def test_pedido_sem_visitante_fica_nao_atribuido_e_a_receita_fecha():
    pedidos = _pedidos(("P1", "v", "2025-03-10 12:00", 100.0), ("P2", None, "2025-03-10 12:00", 50.0))
    r = atribuir(pedidos, SESSOES, 30, 7)
    for modelo in MODELOS:
        do_modelo = r[r["modelo"] == modelo]
        assert do_modelo["receita_atribuida"].sum() == pytest.approx(150.0)
        assert do_modelo.groupby("pedido_id")["credito"].sum().tolist() == pytest.approx([1.0, 1.0])
        assert do_modelo.loc[do_modelo["pedido_id"] == "P2", "canal"].tolist() == [NAO_ATRIBUIDO]
