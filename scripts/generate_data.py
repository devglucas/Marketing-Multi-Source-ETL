"""
Gerador de dados sintéticos da "Aura Cosméticos".

Simula as jornadas de 45 mil visitantes no 1º semestre de 2025: cada um chega por um canal,
volta por outros e pode comprar. Depois escreve o que cada sistema enxergaria:

    mock/dados/google_ads.json            servido pela API simulada (ver mock/ads_api.py)
    data/raw/meta/meta_ads_2025.xlsx      exportação manual, uma aba por mês
    data/raw/email/email_campanhas.csv    plataforma de e-mail
    data/raw/web/sessoes_AAAA-MM.jsonl.gz analytics do site, com UTMs
    data/raw/loja/pedidos.csv             e-commerce
    data/raw/loja/clientes.json           e-commerce
    data/external/gabarito.json           totais verdadeiros, para conferência

Problemas inseridos: UTMs escritas de várias formas ou ausentes, tráfego de robôs e de homologação,
pedidos de teste e duplicados, custo em micros e métricas como texto na API, coluna renomeada na planilha do
Meta a partir de abril, títulos e linhas de total, e conversões das plataformas que se sobrepõem.

Dados fictícios.

Uso:
    python scripts/generate_data.py
"""

from __future__ import annotations

import gzip
import json
import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 606
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
EXTERNAL_DIR = ROOT / "data" / "external"
API_DIR = ROOT / "mock" / "dados"

INICIO, FIM = pd.Timestamp("2025-01-01"), pd.Timestamp("2025-06-30")
N_VISITANTES = 45_000

# campanha: (custo por clique, taxa de clique, papel na jornada)
GOOGLE = {"BR_BRAND_SEARCH": (1.40, 0.12, "retorno"), "BR_PROSP_SEARCH_SKINCARE": (5.20, 0.04, "aquisicao"),
          "BR_PROSP_SHOPPING_CABELOS": (3.80, 0.02, "aquisicao"), "BR_REMARK_DISPLAY_CARRINHO": (2.10, 0.008, "retorno")}
META = {"BR_PROSP_IG_SKINCARE": (3.30, 0.012, "aquisicao"), "BR_PROSP_FB_MAQUIAGEM": (2.90, 0.010, "aquisicao"),
        "BR_REMARK_IG_CARRINHO": (2.00, 0.015, "retorno")}

PRIMEIRO_TOQUE = {"paid_social": 0.32, "paid_search": 0.26, "organic": 0.20, "direct": 0.08, "referral": 0.06, "email": 0.08}
RETORNO = {"direct": 0.30, "email": 0.20, "paid_search": 0.20, "organic": 0.18, "paid_social": 0.12}
# chance de comprar na sessão: mídia social apresenta a marca; direto e e-mail fecham a venda
CONVERSAO = {"direct": 0.028, "email": 0.032, "paid_search": 0.022, "organic": 0.018, "referral": 0.014, "paid_social": 0.005}
RECOMPRA = {"email": 0.45, "organic": 0.40, "direct": 0.38, "referral": 0.35, "paid_search": 0.33, "paid_social": 0.24}

VARIANTES_UTM = {
    "paid_search": (["google", "Google", "GOOGLE", "gads"], ["cpc", "CPC", "ppc", "paid"]),
    "paid_social": (["instagram", "ig", "facebook", "fb", "Meta", "meta"], ["paid_social", "paidsocial", "cpc", "Paid-Social"]),
    "email": (["newsletter", "email", "Email", "mail"], ["email", "e-mail", "Email"]),
    "organic": (["google", "bing", "Google"], ["organic", "Organic"]),
    "referral": (["blogdabeleza.com", "guiadepele.com.br", "revistabem.com"], ["referral", "Referral"]),
}
FORMATO_TS = "%Y-%m-%dT%H:%M:%SZ"


def br(valor: float) -> str:
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pesos_diarios(dias: pd.DatetimeIndex) -> np.ndarray:
    tendencia = 1 + 0.5 * np.linspace(0, 1, len(dias))
    pesos = tendencia * np.where(dias.dayofweek >= 5, 0.8, 1.0)
    pesos[(dias >= "2025-03-10") & (dias <= "2025-03-16")] *= 1.8   # semana do consumidor
    pesos[(dias >= "2025-04-28") & (dias <= "2025-05-11")] *= 2.0   # Dia das Mães
    return pesos / pesos.sum()


def campanha_de_email(data: pd.Timestamp) -> str:
    return f"news_2025_s{data.isocalendar()[1]:02d}"


def escolher_campanha(rng, canal: str, retorno: bool, data: pd.Timestamp) -> str | None:
    if canal == "email":
        return campanha_de_email(data)
    if canal not in ("paid_search", "paid_social"):
        return None
    catalogo = GOOGLE if canal == "paid_search" else META
    papel = "retorno" if retorno else "aquisicao"
    opcoes = [c for c, v in catalogo.items() if v[2] == papel]
    return opcoes[rng.integers(len(opcoes))]


def simular_jornadas(rng) -> tuple[list, list, dict]:
    dias = pd.date_range(INICIO, FIM, freq="D")
    p_dias = pesos_diarios(dias)
    sessoes, pedidos = [], []
    conversoes_plataforma = defaultdict(int)
    canais, p_primeiro = list(PRIMEIRO_TOQUE), list(PRIMEIRO_TOQUE.values())
    retornos, p_retorno = list(RETORNO), list(RETORNO.values())
    sequencia_pedido, sequencia_cliente = 0, 0

    for v in range(1, N_VISITANTES + 1):
        visitante = f"v{v:06d}"
        dia = dias[rng.choice(len(dias), p=p_dias)]
        canal_inicial = str(rng.choice(canais, p=p_primeiro))
        canal, retorno, indice = canal_inicial, False, 0
        momento = dia + pd.Timedelta(seconds=int(rng.integers(0, 86400)))
        cliente, tocadas = None, []
        n_sessoes = int(min(rng.geometric(0.42), 8))

        while True:
            campanha = escolher_campanha(rng, canal, retorno, momento)
            comprou = rng.random() < CONVERSAO[canal] * (1 + 0.6 * indice)
            carrinho = comprou or rng.random() < 0.14
            checkout = comprou or (carrinho and rng.random() < 0.42)
            sessoes.append({"visitante": visitante, "momento": momento, "canal": canal, "campanha": campanha,
                            "carrinho": carrinho, "checkout": checkout, "comprou": comprou})
            if campanha and canal.startswith("paid"):
                tocadas.append(campanha)
            indice += 1
            if comprou:
                if cliente is None:
                    sequencia_cliente += 1
                    cliente = f"C{sequencia_cliente:06d}"
                sequencia_pedido += 1
                valor = round(float(np.clip(rng.lognormal(np.log(150), 0.55), 35, 900)), 2)
                pedidos.append({"pedido_id": f"P{sequencia_pedido:07d}", "visitante": visitante if rng.random() > 0.06 else None,
                                "cliente": cliente, "momento": momento + pd.Timedelta(minutes=int(rng.integers(3, 25))),
                                "valor": valor, "desconto": round(valor * float(rng.choice([0, 0.1, 0.15], p=[0.65, 0.25, 0.1])), 2),
                                "frete": 0.0 if valor >= 199 else round(float(rng.uniform(12, 28)), 2),
                                "status": str(rng.choice(["pago", "cancelado", "reembolsado"], p=[0.92, 0.05, 0.03]))})
                # cada plataforma reivindica a venda de qualquer campanha que tocou a jornada
                for campanha_tocada in set(tocadas):
                    conversoes_plataforma[(campanha_tocada, momento.normalize())] += 1
                tocadas = []
                if rng.random() < RECOMPRA[canal_inicial]:
                    momento += pd.Timedelta(days=int(rng.integers(20, 100)))
                    canal, retorno, indice, n_sessoes = str(rng.choice(["email", "direct"], p=[0.6, 0.4])), True, 1, indice + 2
                else:
                    break
            elif indice >= n_sessoes:
                break
            else:
                momento += pd.Timedelta(hours=float(rng.exponential(72)))
                canal, retorno = str(rng.choice(retornos, p=p_retorno)), True
            if momento > FIM + pd.Timedelta(days=1):
                break
    return [s for s in sessoes if s["momento"] <= FIM + pd.Timedelta(hours=23, minutes=59)], \
        [p for p in pedidos if p["momento"] <= FIM + pd.Timedelta(hours=23, minutes=59)], conversoes_plataforma


def formatar_sessoes(rng, sessoes: pd.DataFrame) -> pd.DataFrame:
    n = len(sessoes)
    fontes, meios = [], []
    for canal in sessoes["canal"]:
        if canal == "direct" or (canal.startswith("paid") and rng.random() < 0.02):  # link sem UTM
            fontes.append(None); meios.append(None)
        else:
            f, m = VARIANTES_UTM[canal]
            fontes.append(f[rng.integers(len(f))]); meios.append(m[rng.integers(len(m))])
    campanhas = [None if pd.isna(c) else c if rng.random() > 0.15 else (c.lower() if rng.random() < 0.7 else f" {c} ")
                 for c in sessoes["campanha"]]
    campanhas = [None if f is None else c for f, c in zip(fontes, campanhas)]
    return pd.DataFrame({
        "session_id": [f"s{i:08d}" for i in rng.permutation(n)], "visitor_id": sessoes["visitante"],
        "ts": sessoes["momento"].dt.strftime(FORMATO_TS), "hostname": "www.auracosmeticos.com.br",
        "utm_source": fontes, "utm_medium": meios, "utm_campaign": campanhas,
        "device": rng.choice(["mobile", "desktop", "tablet"], n, p=[0.72, 0.24, 0.04]),
        "pageviews": 1 + rng.poisson(3, n), "add_to_cart": sessoes["carrinho"], "begin_checkout": sessoes["checkout"],
        "purchase": sessoes["comprou"],
    })


def adicionar_ruido_web(rng, sessoes: pd.DataFrame) -> pd.DataFrame:
    homolog = rng.choice(sessoes.index, int(len(sessoes) * 0.01), replace=False)
    sessoes.loc[homolog, "hostname"] = "homolog.auracosmeticos.com.br"
    robos = []
    for r in range(3):  # cliques automáticos em anúncios: poucos visitantes, milhares de sessões
        dia = INICIO + pd.Timedelta(days=int(rng.integers(20, 150)))
        horarios = dia + pd.to_timedelta(rng.integers(0, 3 * 86400, 1500), unit="s")
        robos.append(pd.DataFrame({
            "session_id": [f"b{r}{i:06d}" for i in range(1500)], "visitor_id": f"bot{r}", "ts": horarios.strftime(FORMATO_TS),
            "hostname": "www.auracosmeticos.com.br", "utm_source": "google", "utm_medium": "cpc",
            "utm_campaign": "BR_PROSP_SEARCH_SKINCARE", "device": "desktop", "pageviews": 1, "add_to_cart": False,
            "begin_checkout": False, "purchase": False}))
    return pd.concat([sessoes, *robos], ignore_index=True).sample(frac=1, random_state=SEED).reset_index(drop=True)


def gravar_sessoes(sessoes: pd.DataFrame) -> None:
    pasta = RAW_DIR / "web"
    pasta.mkdir(parents=True)
    for mes, bloco in sessoes.groupby(sessoes["ts"].str[:7]):
        conteudo = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in bloco.to_dict("records"))
        with open(pasta / f"sessoes_{mes}.jsonl.gz", "wb") as bruto, gzip.GzipFile(filename="", mode="wb", fileobj=bruto, mtime=0) as arq:
            arq.write(conteudo.encode("utf-8"))


def montar_midia(rng, sessoes: pd.DataFrame, conversoes: dict) -> tuple[list, pd.DataFrame]:
    """Cliques e custo por campanha e dia, a partir das sessões (robôs também custam dinheiro)."""
    pagas = sessoes[sessoes["utm_campaign"].notna()].assign(
        campanha=lambda d: d["utm_campaign"].str.strip().str.upper(), dia=lambda d: d["ts"].str[:10])
    por_dia = pagas.groupby(["campanha", "dia"]).size()
    api, meta = [], []
    for (campanha, dia), n in por_dia.items():
        catalogo = GOOGLE if campanha in GOOGLE else META if campanha in META else None
        if catalogo is None:
            continue
        cpc, ctr, _ = catalogo[campanha]
        cliques = int(n / 0.92)
        custo = round(cliques * cpc * float(rng.uniform(0.9, 1.1)), 2)
        impressoes = int(cliques / ctr * float(rng.uniform(0.9, 1.1)))
        convertidas = conversoes.get((campanha, pd.Timestamp(dia)), 0)
        if campanha in GOOGLE:
            api.append({"campaign": {"id": str(1000 + list(GOOGLE).index(campanha)), "name": campanha},
                        "segments": {"date": dia},
                        "metrics": {"impressions": str(impressoes), "clicks": str(cliques),
                                    "costMicros": str(int(round(custo * 1_000_000))), "conversions": float(convertidas)}})
        else:
            meta.append({"dia": dia, "campanha": campanha, "impressoes": impressoes, "alcance": int(impressoes * 0.7),
                         "cliques": cliques, "custo": custo, "compras": convertidas})
    return api, pd.DataFrame(meta)


def gravar_meta(rng, meta: pd.DataFrame) -> None:
    pasta = RAW_DIR / "meta"
    pasta.mkdir(parents=True)
    with pd.ExcelWriter(pasta / "meta_ads_2025.xlsx", engine="openpyxl") as writer:
        for mes, bloco in meta.groupby(meta["dia"].str[:7]):
            coluna_custo = "Valor usado (BRL)" if mes < "2025-04" else "Valor gasto (BRL)"  # o Meta renomeou a coluna
            planilha = pd.DataFrame({
                "Dia": bloco["dia"], "Nome da campanha": [c if rng.random() > 0.1 else c.title() for c in bloco["campanha"]],
                "Alcance": bloco["alcance"], "Impressões": bloco["impressoes"], "Cliques no link": bloco["cliques"],
                coluna_custo: [v if rng.random() > 0.3 else f"R$ {br(v)}" for v in bloco["custo"]], "Compras": bloco["compras"],
            })
            total = {"Dia": "Total", "Alcance": None, "Impressões": bloco["impressoes"].sum(), "Cliques no link": bloco["cliques"].sum(),
                     coluna_custo: round(bloco["custo"].sum(), 2), "Compras": bloco["compras"].sum()}
            planilha = pd.concat([planilha, pd.DataFrame([total])], ignore_index=True)
            planilha.to_excel(writer, sheet_name=mes, index=False, startrow=3)
            writer.sheets[mes]["A1"] = f"Relatório de anúncios - {mes}"
            writer.sheets[mes]["A2"] = "Conta: Aura Cosméticos"


def gravar_email(rng, sessoes: pd.DataFrame) -> pd.DataFrame:
    campanhas = sessoes[sessoes["utm_medium"].fillna("").str.lower().isin(["email", "e-mail"])]
    cliques = campanhas.groupby("utm_campaign", dropna=True).size()
    cliques.index = cliques.index.str.strip().str.lower()
    cliques = cliques.groupby(level=0).sum()
    linhas = []
    for campanha, n in cliques.items():
        semana = int(campanha[-2:])
        data = pd.Timestamp("2024-12-30") + pd.Timedelta(weeks=semana - 1, days=1)
        enviados = int(38_000 + semana * 900 + rng.integers(-1500, 1500))
        entregues = int(enviados * rng.uniform(0.95, 0.985))
        custo = round(enviados * 0.0065, 2)
        linhas.append({"campanha": campanha, "data_envio": data.strftime("%d/%m/%Y"), "enviados": enviados, "entregues": entregues,
                       "aberturas": int(entregues * rng.uniform(0.18, 0.28)), "cliques": int(n / 0.9),
                       "descadastros": int(entregues * rng.uniform(0.001, 0.004)), "custo_brl": br(custo), "_custo": custo})
    df = pd.DataFrame(linhas)
    (RAW_DIR / "email").mkdir(parents=True)
    df.drop(columns="_custo").to_csv(RAW_DIR / "email" / "email_campanhas.csv", index=False)
    return df


def gravar_loja(rng, pedidos: pd.DataFrame) -> dict:
    pasta = RAW_DIR / "loja"
    pasta.mkdir(parents=True)
    saida = pd.DataFrame({
        "pedido_id": pedidos["pedido_id"], "cliente_id": pedidos["cliente"], "visitor_id": pedidos["visitante"],
        "criado_em": pedidos["momento"].dt.strftime("%Y-%m-%d %H:%M:%S"), "valor_produtos": pedidos["valor"],
        "desconto": pedidos["desconto"], "frete": pedidos["frete"], "status": pedidos["status"],
    })
    teste = pd.DataFrame({"pedido_id": [f"T{i:04d}" for i in range(25)], "cliente_id": "C999999", "visitor_id": None,
                          "criado_em": "2025-02-10 10:00:00", "valor_produtos": 0.01, "desconto": 0.0, "frete": 0.0, "status": "pago"})
    duplicados = saida.sample(frac=0.005, random_state=SEED)
    pd.concat([saida, teste, duplicados], ignore_index=True).to_csv(pasta / "pedidos.csv", index=False)

    clientes = pedidos.groupby("cliente")["momento"].min().reset_index()
    registros = [{"cliente_id": c, "uf": str(rng.choice(["SP", "RJ", "MG", "PR", "RS", "BA", "PE", "DF"])),
                  "cadastrado_em": m.strftime("%Y-%m-%d")} for c, m in zip(clientes["cliente"], clientes["momento"])]
    (pasta / "clientes.json").write_text(json.dumps(registros, ensure_ascii=False), encoding="utf-8")
    pagos = saida[saida["status"] == "pago"]
    return {"pedidos_pagos": int(len(pagos)), "receita_paga": round(float((pagos["valor_produtos"] - pagos["desconto"]).sum()), 2),
            "clientes": int(len(clientes))}


def main() -> None:
    rng = np.random.default_rng(SEED)
    for pasta in (RAW_DIR, API_DIR):
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True)
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)

    sessoes, pedidos, conversoes = simular_jornadas(rng)
    web = adicionar_ruido_web(rng, formatar_sessoes(rng, pd.DataFrame(sessoes)))
    gravar_sessoes(web)
    api, meta = montar_midia(rng, web, conversoes)
    (API_DIR / "google_ads.json").write_text(json.dumps(api), encoding="utf-8")
    gravar_meta(rng, meta)
    email = gravar_email(rng, web)
    loja = gravar_loja(rng, pd.DataFrame(pedidos))

    gasto_google = sum(int(l["metrics"]["costMicros"]) for l in api) / 1e6
    gabarito = {**loja, "sessoes_validas": int(len(sessoes) - (web["hostname"] != "www.auracosmeticos.com.br").sum()),
                "sessoes_robo": 4500, "gasto_google": round(gasto_google, 2), "gasto_meta": round(float(meta["custo"].sum()), 2),
                "gasto_email": round(float(email["_custo"].sum()), 2)}
    (EXTERNAL_DIR / "gabarito.json").write_text(json.dumps(gabarito, indent=1), encoding="utf-8")
    tamanho = sum(f.stat().st_size for f in RAW_DIR.rglob("*") if f.is_file()) / 1024 / 1024
    print(json.dumps(gabarito, indent=1), f"\nraw: {tamanho:.1f} MB | linhas API: {len(api)} | Meta: {len(meta)} | e-mail: {len(email)}")


if __name__ == "__main__":
    main()
