"""
API de anúncios simulada, para exercitar a ingestão sem depender da internet.

Imita o comportamento de uma API real de mídia:
- exige token no cabeçalho Authorization
- pagina os resultados e limita o tamanho da página
- devolve métricas aninhadas, com números como texto e custo em micros
- responde 429 (limite de requisições, com Retry-After) e 500 de vez em quando
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DADOS = Path(__file__).parent / "dados" / "google_ads.json"
TOKEN_VALIDO = "token-da-api-simulada"
LIMITE_PAGINA = 500


class ApiAnuncios(BaseHTTPRequestHandler):
    def log_message(self, *_):  # silencia o log padrão do servidor
        pass

    def _responder(self, status: int, corpo: dict, cabecalhos: dict | None = None) -> None:
        conteudo = json.dumps(corpo).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(conteudo)))
        for chave, valor in (cabecalhos or {}).items():
            self.send_header(chave, valor)
        self.end_headers()
        self.wfile.write(conteudo)

    def do_GET(self):  # noqa: N802
        servidor = self.server
        url = urlparse(self.path)
        if url.path != "/v1/relatorios/campanhas":
            return self._responder(404, {"erro": "rota inexistente"})
        if self.headers.get("Authorization") != f"Bearer {TOKEN_VALIDO}":
            return self._responder(401, {"erro": "token inválido"})

        with servidor.trava:
            servidor.requisicoes += 1
            numero = servidor.requisicoes
        if numero % servidor.a_cada_429 == 0:
            return self._responder(429, {"erro": "limite de requisições"}, {"Retry-After": "0.01"})
        if numero % servidor.a_cada_500 == 0:
            return self._responder(500, {"erro": "falha interna"})

        params = parse_qs(url.query)
        inicio, fim = params["data_inicio"][0], params["data_fim"][0]
        pagina = int(params.get("pagina", ["1"])[0])
        por_pagina = min(int(params.get("por_pagina", ["100"])[0]), LIMITE_PAGINA)
        linhas = [l for l in servidor.linhas if inicio <= l["segments"]["date"] <= fim]
        total_paginas = max(1, -(-len(linhas) // por_pagina))
        trecho = linhas[(pagina - 1) * por_pagina: pagina * por_pagina]
        return self._responder(200, {"dados": trecho, "pagina": pagina, "total_paginas": total_paginas})


def iniciar_servidor(a_cada_429: int = 5, a_cada_500: int = 7, linhas: list | None = None) -> ThreadingHTTPServer:
    """Sobe a API em uma porta livre, em segundo plano. Use `servidor.shutdown()` para parar."""
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), ApiAnuncios)
    servidor.linhas = linhas if linhas is not None else json.loads(DADOS.read_text(encoding="utf-8"))
    servidor.requisicoes, servidor.trava = 0, threading.Lock()
    servidor.a_cada_429, servidor.a_cada_500 = a_cada_429, a_cada_500
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


def url_de(servidor: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{servidor.server_address[1]}"
