"""Dados públicos da Binance (sem conta e sem chave): candles, preços e câmbio.

Nada aqui envia ordens. Só lê dados de mercado.
"""
import csv
import json
import os
import time
import urllib.parse
import urllib.request

from .util import DADOS, agora_ms

# api.binance.com é a principal; data-api.binance.vision é o espelho público só de dados
BASES = ["https://api.binance.com", "https://data-api.binance.vision"]
INTERVALO_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "1d": 86_400_000,
}
_base_boa = 0


class ErroBinance(Exception):
    pass


def get_json(caminho, params=None, tentativas=3):
    global _base_boa
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    ultimo = None
    for tentativa in range(tentativas):
        for k in range(len(BASES)):
            base = BASES[(_base_boa + k) % len(BASES)]
            try:
                req = urllib.request.Request(base + caminho + qs, headers={"User-Agent": "agencia-cripto/1.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    dados = json.loads(r.read())
                _base_boa = (_base_boa + k) % len(BASES)
                return dados
            except Exception as e:  # rede instável: tenta o espelho e depois de novo
                ultimo = e
        time.sleep(1.5 * (tentativa + 1))
    raise ErroBinance(f"Falha ao falar com a Binance ({caminho}): {ultimo}")


class Serie:
    """Candles de uma moeda em listas paralelas (rápido em Python puro)."""
    __slots__ = ("simbolo", "intervalo", "t", "o", "h", "l", "c", "v")

    def __init__(self, simbolo, intervalo):
        self.simbolo, self.intervalo = simbolo, intervalo
        self.t, self.o, self.h, self.l, self.c, self.v = [], [], [], [], [], []

    def __len__(self):
        return len(self.t)

    def adicionar(self, t, o, h, l, c, v):
        self.t.append(int(t)); self.o.append(float(o)); self.h.append(float(h))
        self.l.append(float(l)); self.c.append(float(c)); self.v.append(float(v))

    def fatia(self, ini, fim=None):
        s = Serie(self.simbolo, self.intervalo)
        for nome in ("t", "o", "h", "l", "c", "v"):
            setattr(s, nome, getattr(self, nome)[ini:fim])
        return s


def klines(simbolo, intervalo, inicio_ms=None, fim_ms=None, limite=1000):
    p = {"symbol": simbolo, "interval": intervalo, "limit": limite}
    if inicio_ms is not None:
        p["startTime"] = int(inicio_ms)
    if fim_ms is not None:
        p["endTime"] = int(fim_ms)
    return get_json("/api/v3/klines", p)


def recentes(simbolo, intervalo, limite=500, incluir_aberto=False):
    """Últimos candles. Por padrão só os fechados (o último da Binance ainda está se formando)."""
    brutos = klines(simbolo, intervalo, limite=limite)
    s = Serie(simbolo, intervalo)
    agora = agora_ms()
    for k in brutos:
        if not incluir_aberto and int(k[6]) >= agora:
            continue
        s.adicionar(k[0], k[1], k[2], k[3], k[4], k[5])
    return s


def historico(simbolo, intervalo, dias, avisar=print):
    """Histórico com cache em CSV: baixa só o que falta."""
    iv = INTERVALO_MS[intervalo]
    arq = os.path.join(DADOS, f"{simbolo}_{intervalo}.csv")
    linhas = []
    if os.path.exists(arq):
        with open(arq, newline="") as f:
            linhas = [r for r in csv.reader(f) if r]
    agora = agora_ms()
    inicio_desejado = (agora - dias * 86_400_000) // iv * iv
    if linhas and int(linhas[0][0]) > inicio_desejado:
        linhas = []  # cache não cobre o período pedido: baixa tudo de novo
    prox = int(linhas[-1][0]) + iv if linhas else inicio_desejado
    novos = 0
    while prox + iv <= agora:
        lote = klines(simbolo, intervalo, inicio_ms=prox, limite=1000)
        if not lote:
            break
        for k in lote:
            if int(k[6]) >= agora:
                break
            linhas.append([k[0], k[1], k[2], k[3], k[4], k[5]])
            novos += 1
        ultimo = int(lote[-1][0])
        if ultimo + iv <= prox:
            break
        prox = ultimo + iv
        if len(lote) < 1000:
            break
    if novos:
        with open(arq, "w", newline="") as f:
            csv.writer(f).writerows(linhas)
        avisar(f"  {simbolo}: +{novos} candles baixados")
    s = Serie(simbolo, intervalo)
    for r in linhas:
        if int(r[0]) >= inicio_desejado:
            s.adicionar(*r)
    return s


def precos(simbolos):
    dados = get_json("/api/v3/ticker/price", {"symbols": json.dumps(simbolos, separators=(",", ":"))})
    return {d["symbol"]: float(d["price"]) for d in dados}


def variacao_24h(simbolos):
    dados = get_json("/api/v3/ticker/24hr", {"symbols": json.dumps(simbolos, separators=(",", ":")), "type": "MINI"})
    out = {}
    for d in dados:
        aberto = float(d["openPrice"]) or 1.0
        out[d["symbol"]] = (float(d["lastPrice"]) / aberto - 1) * 100
    return out


def usdt_brl():
    try:
        return float(get_json("/api/v3/ticker/price", {"symbol": "USDTBRL"})["price"])
    except Exception:
        return 5.0
