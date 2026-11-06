import pandas as pd
import pytest

from src.contracts import ContratoQuebrado, aplicar_contrato
from src.settings import ErroDeConfiguracao, carregar, token_da_fonte

CONTRATO = {"id": {"tipo": "inteiro", "obrigatoria": True},
            "custo": {"tipo": "numero", "obrigatoria": True, "apelidos": ["valor"]},
            "obs": {"tipo": "texto", "obrigatoria": False}}


def test_configuracao_do_projeto_e_valida():
    config = carregar()
    assert set(config.fontes) == {"google_ads", "meta_ads", "email", "sessoes", "pedidos", "clientes"}


def test_tipo_de_fonte_invalido_falha_na_partida(tmp_path):
    (tmp_path / "canais.yaml").write_text("regras: []\n", encoding="utf-8")
    arquivo = tmp_path / "p.yaml"
    arquivo.write_text("periodo: {inicio: 2025-01-01, fim: 2025-01-02}\nlake: {raiz: x}\nregras: {}\natribuicao: {}\nltv: {}\n"
                       "fontes:\n  a: {tipo: ftp, contrato: {x: {tipo: texto}}}\n", encoding="utf-8")
    with pytest.raises(ErroDeConfiguracao, match="tipo inválido"):
        carregar(arquivo)


def test_token_vem_do_ambiente(monkeypatch):
    fonte = {"token_env": "TOKEN_X", "url_base": "https://api.real", "token_padrao_mock": "mock"}
    monkeypatch.delenv("TOKEN_X", raising=False)
    with pytest.raises(ErroDeConfiguracao):
        token_da_fonte(fonte)
    monkeypatch.setenv("TOKEN_X", "segredo")
    assert token_da_fonte(fonte) == "segredo"


def test_contrato_unifica_coluna_renomeada_no_meio_do_arquivo():
    df = pd.DataFrame({"id": [1, 2], "custo": [10.0, None], "valor": [None, 20.0]})
    resultado, ocorrencias = aplicar_contrato(df, CONTRATO, "f")
    assert resultado["custo"].tolist() == [10.0, 20.0]
    assert [o["tipo"] for o in ocorrencias] == ["coluna_renomeada"]


def test_contrato_registra_coluna_nova_e_tipo_invalido():
    df = pd.DataFrame({"id": ["1", "x"], "custo": ["1.5", "2"], "extra": [1, 2]})
    resultado, ocorrencias = aplicar_contrato(df, CONTRATO, "f")
    assert "extra" not in resultado.columns
    assert sorted(o["tipo"] for o in ocorrencias) == ["coluna_nova", "tipo_invalido"]


def test_coluna_obrigatoria_ausente_quebra_o_contrato():
    with pytest.raises(ContratoQuebrado, match="custo"):
        aplicar_contrato(pd.DataFrame({"id": [1]}), CONTRATO, "f")
