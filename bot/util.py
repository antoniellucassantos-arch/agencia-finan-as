"""Caminhos, configuração e pequenos utilitários compartilhados."""
import json
import os
import sys
import time
from datetime import datetime, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DADOS = os.path.join(RAIZ, "dados")
ESTADO = os.path.join(RAIZ, "estado")
RELATORIOS = os.path.join(RAIZ, "relatorios")
ESCRITORIO = os.path.join(RAIZ, "escritorio")

for _p in (DADOS, ESTADO, RELATORIOS):
    os.makedirs(_p, exist_ok=True)

# o terminal do Windows nem sempre é UTF-8; sem isso acentos e símbolos derrubam o print
for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def carregar_config():
    with open(os.path.join(RAIZ, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def agora_ms():
    return int(time.time() * 1000)


def data_hora(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().strftime("%d/%m %H:%M")


def dia_utc(ms):
    return int(ms // 86_400_000)


def salvar_json(caminho, obj):
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def ler_json(caminho, padrao=None):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def nome_moeda(simbolo):
    return simbolo[:-4] if simbolo.endswith("USDT") else simbolo


def brl(v):
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def num(v, casas=2):
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")
