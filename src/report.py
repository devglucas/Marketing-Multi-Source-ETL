"""Relatório em Markdown e exportação dos marts em CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.utils import df_para_markdown, formatar_br


def exportar(marts: dict[str, pd.DataFrame], pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, tabela in marts.items():
        tabela.to_csv(pasta / f"{nome}.csv", index=False, float_format="%.4f")


def _tabela_verificacoes(verificacoes: list[dict]) -> str:
    tabela = pd.DataFrame(verificacoes).assign(resultado=lambda d: d["ok"].map({True: "ok", False: "falhou"}))
    return df_para_markdown(tabela[["verificacao", "severidade", "resultado", "detalhe"]])


def escrever(marts: dict, verificacoes: list[dict], resumo: dict, benchmark: pd.DataFrame | None, destino: Path) -> None:
    canal = marts["desempenho_canal"]
    plataformas = marts["plataforma_vs_atribuido"]
    declaradas = plataformas["conversoes_declaradas"].sum()
    partes = [
        "# Relatório de marketing: Aura Cosméticos\n",
        f"Período: {resumo['inicio']} a {resumo['fim']}. Modelo de atribuição padrão: `{resumo['modelo']}`.\n",
        "## Resumo\n",
        f"- Gasto de mídia: R$ {formatar_br(resumo['gasto'])}",
        f"- Receita paga: R$ {formatar_br(resumo['receita'])} em {formatar_br(resumo['pedidos'], 0)} pedidos",
        f"- CAC geral: R$ {formatar_br(resumo['cac'])} | ROAS geral: {formatar_br(resumo['roas'])}",
        f"- Plataformas declararam {formatar_br(declaradas, 0)} conversões, contra {formatar_br(resumo['pedidos'], 0)} pedidos reais em toda a loja\n",
        "## Desempenho por canal\n", df_para_markdown(canal), "",
        "## ROAS por modelo de atribuição\n", df_para_markdown(marts["roas_por_modelo"]), "",
        "## Pedidos por canal em cada modelo\n", df_para_markdown(marts["comparacao_modelos"], 0), "",
        "## Funil por canal\n", df_para_markdown(marts["funil_canal"], 3), "",
        "## Conversões declaradas x atribuídas\n", df_para_markdown(plataformas), "",
        "## Evolução mensal\n", df_para_markdown(marts["serie_mensal"]), "",
        "## LTV por coorte\n", df_para_markdown(marts["ltv_coorte"]), "",
        "## LTV por canal de aquisição\n", df_para_markdown(marts["ltv_canal"]), "",
    ]
    if benchmark is not None:
        partes += ["## CSV x Parquet\n", df_para_markdown(benchmark, 1), ""]
    partes += ["## Verificações\n", _tabela_verificacoes(verificacoes), ""]
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(partes), encoding="utf-8")
