"""Registro de conectores: o campo `tipo` da fonte no YAML escolhe a função de leitura."""

from src.connectors.api import ler_api
from src.connectors.arquivos import ler_csv, ler_excel, ler_json, ler_jsonl

CONECTORES = {"api": ler_api, "excel": ler_excel, "csv": ler_csv, "jsonl": ler_jsonl, "json": ler_json}
