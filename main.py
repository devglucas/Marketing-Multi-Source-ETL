"""
Pipeline de marketing: fontes -> landing -> curated -> atribuição -> marts -> relatório.

    python main.py                 execução completa
    python main.py --sem-benchmark pula a comparação CSV x Parquet
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

from mock.ads_api import iniciar_servidor, url_de
from src import benchmark as bench
from src import lake, quality, report, visualize
from src.attribution import atribuir
from src.connectors import CONECTORES
from src.contracts import aplicar_contrato
from src.curate import curar
from src.metrics import construir_marts
from src.settings import OUTPUT_DIR, Configuracao, carregar
from src.utils import configurar_logger, gravar_logs_em

log = configurar_logger("main")


@contextmanager
def api_simulada():
    servidor = iniciar_servidor()
    try:
        yield url_de(servidor)
    finally:
        servidor.shutdown()


def ingerir(config: Configuracao, url_api: str | None) -> tuple[dict, list[dict], dict]:
    """Lê cada fonte, guarda o bruto na landing e aplica o contrato."""
    contexto = {"url_api": url_api, "inicio": config.inicio, "fim": config.fim, "metricas_api": {"requisicoes": 0, "novas_tentativas": 0}}
    tabelas, ocorrencias = {}, []
    for nome, fonte in config.fontes.items():
        bruto = CONECTORES[fonte["tipo"]](fonte, contexto)
        lake.salvar_landing(bruto, config.raiz_lake, nome)
        tabelas[nome], achados = aplicar_contrato(bruto, fonte["contrato"], nome)
        ocorrencias += achados
        log.info("%-11s %7d linhas | %d ocorrências de contrato", nome, len(bruto), len(achados))
    return tabelas, ocorrencias, contexto["metricas_api"]


def publicar_curado(curado: dict, config: Configuracao) -> None:
    for tabela in ["sessoes", "pedidos", "gasto_midia"]:
        lake.escrever(curado[tabela], config.raiz_lake, "curated", tabela, lake.ESQUEMAS[tabela], particoes=["ano_mes"])
    lake.escrever(curado["clientes"], config.raiz_lake, "curated", "clientes", lake.ESQUEMAS["clientes"])
    lake.escrever(curado["quarentena"], config.raiz_lake, "curated", "quarentena")


def executar(config: Configuracao, saida: Path = OUTPUT_DIR, com_benchmark: bool = True) -> dict:
    inicio = time.perf_counter()
    etapas: dict[str, float] = {}

    def marcar(etapa: str, comeco: float) -> None:
        etapas[etapa] = round(time.perf_counter() - comeco, 2)

    t = time.perf_counter()
    usa_mock = config.fontes["google_ads"].get("url_base") == "mock"
    with api_simulada() if usa_mock else nullcontext(config.fontes["google_ads"].get("url_base")) as url:
        landing, ocorrencias, metricas_api = ingerir(config, url)
    marcar("ingestao", t)

    t = time.perf_counter()
    curado = curar(landing, config)
    publicar_curado(curado, config)
    marcar("curadoria", t)

    # A partir daqui tudo sai do lake: só as colunas necessárias, como faria um consumidor real.
    t = time.perf_counter()
    raiz = config.raiz_lake
    sessoes = lake.ler(raiz, "curated", "sessoes")
    pedidos = lake.ler(raiz, "curated", "pedidos")
    pagos = pedidos[pedidos["valido"]]
    regras = config.atribuicao
    atribuicao = atribuir(pagos, sessoes[["visitor_id", "momento", "canal", "campanha"]], regras["janela_dias"], regras["meia_vida_dias"])
    lake.escrever(atribuicao, raiz, "marts", "atribuicao")
    marts = construir_marts({**curado, "sessoes": sessoes, "pedidos": pedidos}, atribuicao, config)
    for nome, tabela in marts.items():
        lake.escrever(tabela, raiz, "marts", nome)
    marcar("atribuicao_e_marts", t)

    verificacoes = [
        *quality.verificar_curado(curado, landing, config), *quality.verificar_gabarito(curado),
        *quality.verificar_atribuicao(atribuicao, pagos), *quality.verificar_fontes(ocorrencias),
        *quality.verificar_plataformas(marts["plataforma_vs_atribuido"], len(pagos)),
    ]
    falhas = quality.falhas_criticas(verificacoes)

    t = time.perf_counter()
    tabela_benchmark = bench.comparar(sessoes, raiz) if com_benchmark else None
    marcar("benchmark", t)

    gasto, receita = float(curado["gasto_midia"]["custo"].sum()), float(pagos["receita_liquida"].sum())
    novos = pagos["cliente_id"].nunique()
    resumo = {"inicio": f"{config.inicio:%Y-%m-%d}", "fim": f"{config.fim:%Y-%m-%d}", "modelo": regras["modelo_padrao"], "gasto": gasto, "receita": receita,
              "pedidos": len(pagos), "clientes_novos": novos, "cac": gasto / novos, "roas": receita / gasto}

    t = time.perf_counter()
    report.exportar({**marts, **({"benchmark": tabela_benchmark} if tabela_benchmark is not None else {}),
                     "quarentena_resumo": curado["quarentena"].groupby(["tabela", "motivo"], as_index=False).size()}, saida / "reports")
    report.escrever(marts, verificacoes, resumo, tabela_benchmark, saida / "relatorio.md")
    visualize.gerar(marts, len(pagos), tabela_benchmark, saida / "charts")
    marcar("relatorio", t)

    manifesto = {
        "executado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sucesso": not falhas,
        "duracao_s": round(time.perf_counter() - inicio, 2), "etapas_s": etapas, "linhas_por_fonte": {k: len(v) for k, v in landing.items()},
        "api": metricas_api, "ocorrencias_de_contrato": ocorrencias, "resumo": resumo,
        "verificacoes": {"total": len(verificacoes), "criticas_com_falha": len(falhas),
                         "alertas": sum(1 for v in verificacoes if v["severidade"] == "alerta" and not v["ok"])},
    }
    (saida / "run_manifest.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for falha in falhas:
        log.error("verificação crítica falhou: %s (%s)", falha["verificacao"], falha["detalhe"])
    log.info("concluído em %.1fs | %d verificações, %d críticas com falha", manifesto["duracao_s"], len(verificacoes), len(falhas))
    return {"manifesto": manifesto, "marts": marts, "verificacoes": verificacoes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sem-benchmark", action="store_true")
    argumentos = parser.parse_args()
    gravar_logs_em(OUTPUT_DIR / "logs" / "pipeline.log")
    resultado = executar(carregar(), com_benchmark=not argumentos.sem_benchmark)
    return 0 if resultado["manifesto"]["sucesso"] else 1


if __name__ == "__main__":
    sys.exit(main())
