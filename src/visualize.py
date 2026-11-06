"""Gráficos do relatório. Cada um responde a uma pergunta de decisão de verba."""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logging.getLogger("matplotlib").setLevel(logging.WARNING)

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
CINZA, TINTA_2, TINTA_3 = "#b5b3ab", "#52514e", "#898781"
GRADE, EIXO, SUPERFICIE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
MESES = {"01": "jan", "02": "fev", "03": "mar", "04": "abr", "05": "mai", "06": "jun"}
NOMES_CANAL = {"paid_search": "Busca paga", "paid_social": "Social pago", "email": "E-mail", "organic": "Orgânico",
               "direct": "Direto", "referral": "Referência", "nao_atribuido": "Não atribuído"}
NOMES_MODELO = {"primeiro_clique": "Primeiro clique", "linear": "Linear", "ultimo_nao_direto": "Último não direto"}


def _estilo() -> None:
    plt.rcParams.update({
        "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE, "savefig.facecolor": SUPERFICIE, "font.size": 11,
        "axes.edgecolor": EIXO, "axes.labelcolor": TINTA_2, "xtick.color": TINTA_2, "ytick.color": TINTA_2,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRADE,
        "axes.axisbelow": True, "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlepad": 24, "axes.titlelocation": "left",
    })


def _rs(texto: str) -> str:
    return texto.replace("$", r"\$")


def _salvar(fig, pasta: Path, nome: str) -> None:
    fig.tight_layout()
    fig.savefig(pasta / f"{nome}.png", dpi=150)
    plt.close(fig)


def modelos_mudam_o_credito(comparacao: pd.DataFrame, pasta: Path) -> None:
    dados = comparacao[comparacao["canal"].isin(["paid_search", "paid_social", "email", "organic"])].set_index("canal")
    dados = dados.loc[["paid_search", "paid_social", "email", "organic"]]
    fig, ax = plt.subplots(figsize=(9.5, 5))
    posicoes, largura = np.arange(len(dados)), 0.26
    for i, (modelo, nome) in enumerate(NOMES_MODELO.items()):
        barras = ax.bar(posicoes + (i - 1) * largura, dados[modelo], largura - 0.02, color=SERIES[i], label=nome)
        ax.bar_label(barras, fmt="%.0f", padding=3, fontsize=9, color=TINTA_2)
    ax.set_xticks(posicoes, [NOMES_CANAL[c] for c in dados.index])
    ax.set_ylabel("Pedidos creditados")
    ax.set_title("O social pago abre compras que o último clique não enxerga")
    ax.legend(frameon=False, ncols=3, loc="upper right")
    ax.margins(y=0.15)
    _salvar(fig, pasta, "01_pedidos_por_modelo")


def roas_campanhas(campanhas: pd.DataFrame, pasta: Path) -> None:
    pagas = campanhas[campanhas["campanha"].str.startswith("BR_")].sort_values("roas")
    fig, ax = plt.subplots(figsize=(9.5, 5))
    cores = [SERIES[1] if v < 1 else SERIES[0] for v in pagas["roas"]]
    barras = ax.barh(pagas["campanha"], pagas["roas"], color=cores)
    ax.axvline(1, color=TINTA_2, linewidth=1)
    ax.bar_label(barras, fmt="%.2f", padding=3, fontsize=9, color=TINTA_2)
    ax.text(1.04, -0.42, "receita = gasto", color=TINTA_2, fontsize=9)
    ax.grid(False)
    ax.set_xlabel("ROAS (receita atribuída / gasto)")
    fig.suptitle("No último não direto, as campanhas em laranja devolvem menos do que custam", x=0.02, ha="left",
                 fontsize=13, fontweight="bold")
    ax.margins(x=0.1)
    _salvar(fig, pasta, "02_roas_por_campanha")


def declarado_vs_atribuido(tabela: pd.DataFrame, pedidos_reais: int, pasta: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    nomes = ["Google Ads", "Meta Ads"]
    posicoes, largura = np.arange(2), 0.36
    a = ax.bar(posicoes - largura / 2, tabela["conversoes_declaradas"], largura - 0.02, color=CINZA, label="Declaradas pela plataforma")
    b = ax.bar(posicoes + largura / 2, tabela["pedidos_atribuidos"], largura - 0.02, color=SERIES[0], label="Atribuídas pelo pipeline")
    ax.bar_label(a, fmt="%.0f", padding=3, color=TINTA_2)
    ax.bar_label(b, fmt="%.0f", padding=3, color=TINTA_2)
    ax.set_xticks(posicoes, nomes)
    ax.set_ylabel("Conversões")
    declaradas = tabela["conversoes_declaradas"].sum()
    ax.set_title(f"As plataformas declaram {declaradas:.0f} conversões; a loja teve {pedidos_reais} pedidos")
    ax.legend(frameon=False, ncols=2, loc="lower left", bbox_to_anchor=(0, 1.0), borderaxespad=0, fontsize=10)
    ax.margins(y=0.12)
    _salvar(fig, pasta, "03_declarado_vs_atribuido")


def funil(funil_canal: pd.DataFrame, pasta: Path) -> None:
    dados = funil_canal.sort_values("conversao")
    fig, ax = plt.subplots(figsize=(9, 4.8))
    barras = ax.barh([NOMES_CANAL[c] for c in dados["canal"]], dados["conversao"] * 100, color=SERIES[0])
    ax.bar_label(barras, fmt="%.1f%%", padding=4, color=TINTA_2)
    ax.grid(False)
    ax.set_xlabel("Sessões que terminam em compra (%)")
    ax.set_title("O tráfego de social pago converte bem menos que os outros canais")
    ax.margins(x=0.1)
    _salvar(fig, pasta, "04_conversao_por_canal")


def cac_mensal(serie: pd.DataFrame, pasta: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.8))
    rotulos = [MESES[m[-2:]] for m in serie["ano_mes"]]
    ax.plot(rotulos, serie["cac"], color=SERIES[0], linewidth=2.2, marker="o")
    valores = serie["cac"].tolist()
    for i, (x, y) in enumerate(zip(rotulos, valores)):
        vizinhos = valores[max(i - 1, 0):i] + valores[i + 1:i + 2]
        deslocamento = -18 if y < sum(vizinhos) / len(vizinhos) else 10    # o rótulo fica do lado livre da linha
        ax.annotate(_rs(f"R$ {y:.0f}"), (x, y), textcoords="offset points", xytext=(0, deslocamento), ha="center", color=TINTA_2)
    ax.set_ylim(0, serie["cac"].max() * 1.25)
    ax.set_ylabel(_rs("CAC geral (R$)"))
    ax.set_title("O CAC subiu em abril e maio, quando o gasto mais cresceu")
    _salvar(fig, pasta, "05_cac_mensal")


def ltv_contra_cac(ltv_canal: pd.DataFrame, pasta: Path) -> None:
    maior_marco = ltv_canal["marco_dias"].max()
    dados = ltv_canal[(ltv_canal["marco_dias"] == maior_marco) & ltv_canal["cac"].notna()].set_index("canal")
    dados = dados.loc[["email", "paid_search", "paid_social"]]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    posicoes, largura = np.arange(len(dados)), 0.36
    a = ax.bar(posicoes - largura / 2, dados["ltv"], largura - 0.02, color=SERIES[0], label=f"LTV em {maior_marco} dias")
    b = ax.bar(posicoes + largura / 2, dados["cac"], largura - 0.02, color=SERIES[1], label="CAC")
    ax.bar_label(a, fmt="%.0f", padding=3, color=TINTA_2)
    ax.bar_label(b, fmt="%.0f", padding=3, color=TINTA_2)
    ax.set_xticks(posicoes, [NOMES_CANAL[c] for c in dados.index])
    ax.set_ylabel(_rs("R$ por cliente"))
    ax.set_title(f"Em {maior_marco} dias, o cliente do social pago apenas paga o próprio CAC")
    ax.legend(frameon=False, ncols=2, loc="lower left", bbox_to_anchor=(0, 1.0), borderaxespad=0, fontsize=10)
    ax.margins(y=0.12)
    _salvar(fig, pasta, "06_ltv_contra_cac")


def benchmark(tabela: pd.DataFrame, pasta: Path) -> None:
    dados = tabela.iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    barras = ax.barh(dados["medida"].str.replace(r" \(.*\)", "", regex=True), dados["vantagem"], color=SERIES[0])
    ax.bar_label(barras, fmt="%.1fx", padding=4, color=TINTA_2)
    ax.grid(False)
    ax.set_xlabel("Vantagem do Parquet sobre o CSV (vezes)")
    ax.set_title("A maior vantagem do Parquet aparece ao ler um único mês")
    ax.margins(x=0.1)
    _salvar(fig, pasta, "07_csv_vs_parquet")


def gerar(marts: dict, pedidos_reais: int, tabela_benchmark: pd.DataFrame | None, pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    _estilo()
    modelos_mudam_o_credito(marts["comparacao_modelos"], pasta)
    roas_campanhas(marts["desempenho_campanha"], pasta)
    declarado_vs_atribuido(marts["plataforma_vs_atribuido"], pedidos_reais, pasta)
    funil(marts["funil_canal"], pasta)
    cac_mensal(marts["serie_mensal"], pasta)
    ltv_contra_cac(marts["ltv_canal"], pasta)
    if tabela_benchmark is not None:
        benchmark(tabela_benchmark, pasta)
