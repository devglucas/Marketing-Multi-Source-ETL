"""
Conector de API: janelas de data, paginação e tentativas com espera exponencial.

Falhas temporárias são normais em APIs. 429 (limite de requisições) respeita o Retry-After e
5xx espera cada vez mais. Erros definitivos, como 401, falham na hora: tentar de novo não resolve.
"""

from __future__ import annotations

import time

import pandas as pd
import requests

from src.settings import token_da_fonte
from src.utils import configurar_logger

log = configurar_logger("api")


class ErroDeApi(Exception):
    pass


def requisitar(sessao: requests.Session, url: str, params: dict, fonte: dict, metricas: dict) -> dict:
    espera = fonte["espera_inicial_s"]
    for tentativa in range(1, fonte["tentativas"] + 1):
        metricas["requisicoes"] += 1
        try:
            resposta = sessao.get(url, params=params, timeout=fonte["timeout_s"])
        except requests.RequestException as erro:
            status, atraso = f"conexão: {erro}", espera
        else:
            if resposta.status_code == 200:
                return resposta.json()
            status = resposta.status_code
            if status != 429 and status < 500:
                raise ErroDeApi(f"{status} em {url}: {resposta.text[:200]}")
            atraso = float(resposta.headers.get("Retry-After", espera))
        metricas["novas_tentativas"] += 1
        log.debug("tentativa %d falhou (%s), aguardando %.2fs", tentativa, status, atraso)
        time.sleep(atraso)
        espera *= 2
    raise ErroDeApi(f"{url} falhou após {fonte['tentativas']} tentativas")


def janelas(inicio: pd.Timestamp, fim: pd.Timestamp, dias: int) -> list[tuple[str, str]]:
    resultado, atual = [], inicio
    while atual <= fim:
        ultimo = min(atual + pd.Timedelta(days=dias - 1), fim)
        resultado.append((atual.strftime("%Y-%m-%d"), ultimo.strftime("%Y-%m-%d")))
        atual = ultimo + pd.Timedelta(days=1)
    return resultado


def ler_api(fonte: dict, contexto: dict) -> pd.DataFrame:
    url = contexto["url_api"] + fonte["rota"]
    metricas = contexto["metricas_api"]
    registros = []
    with requests.Session() as sessao:
        sessao.headers["Authorization"] = f"Bearer {token_da_fonte(fonte)}"
        for inicio, fim in janelas(contexto["inicio"], contexto["fim"], fonte["janela_dias"]):
            pagina, total = 1, 1
            while pagina <= total:
                corpo = requisitar(sessao, url, {"data_inicio": inicio, "data_fim": fim, "pagina": pagina,
                                                 "por_pagina": fonte["por_pagina"]}, fonte, metricas)
                registros += corpo["dados"]
                total = corpo["total_paginas"]
                pagina += 1
    log.info("API: %d registros em %d requisições (%d novas tentativas)", len(registros), metricas["requisicoes"],
             metricas["novas_tentativas"])
    return pd.json_normalize(registros, sep="_")
