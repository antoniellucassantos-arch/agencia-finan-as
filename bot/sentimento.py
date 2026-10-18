"""Índice de Medo e Ganância (alternative.me), gratuito e sem chave.
Fica em cache por 6 horas. Sem internet, o agente de Sentimento simplesmente vota neutro."""
import json
import os
import time
import urllib.request

from .util import DADOS, dia_utc

ARQ = os.path.join(DADOS, "medo_ganancia.json")
_cache = None


def _baixar():
    req = urllib.request.Request("https://api.alternative.me/fng/?limit=0&format=json", headers={"User-Agent": "agencia-cripto/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        dados = json.loads(r.read())["data"]
    return {str(dia_utc(int(d["timestamp"]) * 1000)): int(d["value"]) for d in dados}


def tabela():
    """{dia_utc: valor 0-100}"""
    global _cache
    if _cache is not None and time.time() - _cache[0] < 6 * 3600:
        return _cache[1]
    tab = None
    try:
        if os.path.exists(ARQ) and time.time() - os.path.getmtime(ARQ) < 6 * 3600:
            with open(ARQ, encoding="utf-8") as f:
                tab = json.load(f)
        else:
            tab = _baixar()
            with open(ARQ, "w", encoding="utf-8") as f:
                json.dump(tab, f)
    except Exception:
        try:
            with open(ARQ, encoding="utf-8") as f:
                tab = json.load(f)
        except Exception:
            tab = {}
    _cache = (time.time(), tab)
    return tab


def valor_em(ms, tab=None):
    tab = tabela() if tab is None else tab
    d = dia_utc(ms)
    for k in range(3):  # se o dia ainda não saiu, usa o anterior
        v = tab.get(str(d - k))
        if v is not None:
            return v
    return None


def rotulo(v):
    if v is None:
        return "sem dados"
    if v <= 20:
        return "medo extremo"
    if v <= 40:
        return "medo"
    if v < 60:
        return "neutro"
    if v < 80:
        return "ganância"
    return "ganância extrema"
