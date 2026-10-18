"""Os agentes da agência. Cada um olha o mercado de um jeito e vota de -1 (vender ou
ficar fora) a +1 (comprar), sempre com o motivo em português.

Todos usam só dados até o candle atual (nada do futuro), então o mesmo código serve
para o backtest e para o modo ao vivo.

O que a pesquisa de 4 anos mostrou (ver relatorios/): sinais rápidos quase não vencem
as taxas; a Tendência Longa (média de 50 dias + força de 30 dias) é o que mais protege
o dinheiro nas quedas. Por isso ela é a voz principal dos robôs de tendência.
"""
from .binance import INTERVALO_MS
from .indicadores import adx, atr, bollinger, donchian, ema, macd, max_min_janela, rsi, sma, vol_retornos, zscore
from . import sentimento

DIA_MS = 86_400_000
DIAS_MEDIA_LONGA = 50
DIAS_FORCA = 30


def _lim(v, a=-1.0, b=1.0):
    return a if v < a else b if v > b else v


def velas_por_dia(intervalo):
    return max(1, DIA_MS // INTERVALO_MS[intervalo])


def aquecimento(intervalo):
    """Quantos candles os indicadores precisam antes do primeiro voto válido."""
    return velas_por_dia(intervalo) * (DIAS_MEDIA_LONGA + 2)


def regime_macro(btc):
    """Humor do mercado pelo Bitcoin num tempo gráfico maior (1h -> 4h; 15m -> 1h; 4h+ -> 1d).
    Devolve {tempo_do_candle: (valor, texto)}, conhecido no fechamento daquele candle."""
    iv = INTERVALO_MS[btc.intervalo]
    alto = 3_600_000 if iv < 3_600_000 else 14_400_000 if iv < 14_400_000 else DIA_MS
    rotulo = {3_600_000: "50h", 14_400_000: "50 velas de 4h", DIA_MS: "50 dias"}[alto]
    n, k = 50, 2 / 51
    fechamentos, emas = [], []
    atual = (0.0, "Sala Macro aquecendo: ainda juntando histórico do BTC")
    out = {}
    for i, t in enumerate(btc.t):
        if (t + iv) % alto == 0:
            c = btc.c[i]
            fechamentos.append(c)
            if len(fechamentos) == n:
                emas.append(sum(fechamentos) / n)
            elif len(fechamentos) > n:
                emas.append(c * k + emas[-1] * (1 - k))
            if len(emas) > 6:
                e, e_ant = emas[-1], emas[-6]
                dist = (c / e - 1) * 100
                if c > e and e > e_ant:
                    atual = (1.0, f"BTC {dist:+.1f}% acima da média de {rotulo} e subindo: mercado favorável")
                elif c < e and e < e_ant:
                    atual = (-1.0, f"BTC {dist:+.1f}% abaixo da média de {rotulo} e caindo: mercado defensivo")
                else:
                    atual = (0.0, f"BTC perto da média de {rotulo} ({dist:+.1f}%), sem direção clara")
        out[t] = atual
    return out


class Analise:
    """Indicadores de uma moeda calculados uma vez; os agentes leem pelo índice do candle."""

    def __init__(self, serie, macro=None, tabela_fng=None):
        s = serie
        self.s = s
        c, h, l, v = s.c, s.h, s.l, s.v
        vpd = velas_por_dia(s.intervalo)
        self.vpd = vpd
        self.e20, self.e50 = ema(c, 20), ema(c, 50)
        self.media_longa = sma(c, vpd * DIAS_MEDIA_LONGA)
        self.lag_forca = vpd * DIAS_FORCA
        self.rsi = rsi(c, 14)
        _, _, self.hist = macd(c)
        self.meio, _, _, self.pctb = bollinger(c, 20, 2.0)
        self.atr = atr(h, l, c, 14)
        self.adx, _, _ = adx(h, l, c, 14)
        self.dhi, self.dlo = donchian(h, l, 20)
        self.vz = zscore(v, 20)
        self.vol_dia = vol_retornos(c, vpd, vpd * 30)
        self.max20d, _ = max_min_janela(h, l, vpd * 20)
        _, self.min10d = max_min_janela(h, l, vpd * 10)
        self.macro = macro or {}
        self.fng = tabela_fng if tabela_fng is not None else {}

    def pronto(self, i):
        return (i >= self.lag_forca and None not in (
            self.media_longa[i], self.e50[i], self.rsi[i], self.hist[i], self.hist[i - 1],
            self.pctb[i], self.atr[i], self.adx[i], self.dhi[i], self.vz[i], self.vol_dia[i], self.max20d[i]))

    def item(self, i, score):
        """O que o robô precisa saber de uma moeda neste candle."""
        s = self.s
        return {"score": score, "atr": self.atr[i], "vol": self.vol_dia[i] * s.c[i], "c": s.c[i], "h": s.h[i],
                "meio": self.meio[i], "macro": self.macro.get(s.t[i], (0.0, ""))[0]}


# ---------------------------------------------------------------- agentes

def tendencia_longa(a, i, motivo=True):
    c, m = a.s.c[i], a.media_longa[i]
    antes = a.s.c[i - a.lag_forca]
    acima, forte = c > m, c > antes
    if acima and forte:
        v = 1.0
    elif not acima and not forte:
        v = -1.0
    elif acima:
        v = 0.3
    else:
        v = -0.3
    if not motivo:
        return v, ""
    dist = (c / m - 1) * 100
    forca = (c / antes - 1) * 100
    if v == 1.0:
        txt = f"{dist:+.1f}% acima da média de {DIAS_MEDIA_LONGA} dias e {forca:+.1f}% em {DIAS_FORCA} dias: tendência de alta"
    elif v == -1.0:
        txt = f"{dist:+.1f}% abaixo da média de {DIAS_MEDIA_LONGA} dias e {forca:+.1f}% em {DIAS_FORCA} dias: tendência de baixa, fico fora"
    else:
        txt = f"Sinais misturados: {dist:+.1f}% da média de {DIAS_MEDIA_LONGA} dias, {forca:+.1f}% em {DIAS_FORCA} dias"
    return v, txt


def tendencia(a, i, motivo=True):
    c, e20, e50, adx_ = a.s.c[i], a.e20[i], a.e50[i], a.adx[i]
    if e20 > e50 and c > e50:
        base = 1.0
    elif e20 < e50 and c < e50:
        base = -1.0
    else:
        base = 0.0
    v = base * _lim((adx_ - 15) / 25, 0.2, 1.0)
    if not motivo:
        return v, ""
    if base > 0:
        txt = f"Curto prazo em alta: média de 20 acima da de 50 (ADX {adx_:.0f}{', forte' if adx_ >= 25 else ''})"
    elif base < 0:
        txt = f"Curto prazo em baixa: média de 20 abaixo da de 50 (ADX {adx_:.0f})"
    else:
        txt = f"Curto prazo sem direção, médias embaralhadas (ADX {adx_:.0f})"
    return v, txt


def momento(a, i, motivo=True):
    hist, ant, r = a.hist[i], a.hist[i - 1], a.rsi[i]
    s = (0.5 if hist > 0 else -0.5) + (0.5 if hist > ant else -0.5)
    if 55 <= r <= 70:
        s += 0.2
    elif r < 45:
        s -= 0.2
    if r > 75:
        s -= 0.6
    v = _lim(s)
    if not motivo:
        return v, ""
    dire = "positivo" if hist > 0 else "negativo"
    acel = "ganhando força" if hist > ant else "perdendo força"
    return v, f"MACD {dire} e {acel}, RSI {r:.0f}{' — esticado, cuidado' if r > 75 else ''}"


def reversao(a, i, motivo=True):
    pb, r = a.pctb[i], a.rsi[i]
    if pb < 0 and r < 35:
        v, txt = 1.0, f"Furou a banda de baixo com RSI {r:.0f}: queda exagerada, chance de repique"
    elif pb < 0.15 and r < 40:
        v, txt = 0.5, f"Perto da banda de baixo, RSI {r:.0f}: começando a ficar barata"
    elif pb > 1 and r > 70:
        v, txt = -1.0, f"Furou a banda de cima com RSI {r:.0f}: subida exagerada"
    elif pb > 0.85 and r > 62:
        v, txt = -0.5, f"Perto da banda de cima, RSI {r:.0f}: ficando cara"
    else:
        v, txt = 0.0, f"Preço no meio das bandas (RSI {r:.0f}), sem exagero"
    return v, (txt if motivo else "")


def rompimento(a, i, motivo=True):
    c, hi, lo, vz = a.s.c[i], a.dhi[i], a.dlo[i], a.vz[i]
    if c > hi:
        v = _lim(0.6 + max(vz, 0) / 4) if vz > 0.5 else 0.5
        txt = f"Rompeu a máxima de 20 candles{' com volume forte' if vz > 0.5 else ', mas com pouco volume'}"
    elif c < lo:
        v, txt = -0.9, "Perdeu a mínima de 20 candles: rompimento para baixo"
    else:
        pos = 0.5 if hi == lo else (c - lo) / (hi - lo)
        v, txt = 0.0, f"Dentro do canal de 20 candles ({pos * 100:.0f}% do caminho até o topo)"
    return v, (txt if motivo else "")


def rompimento_longo(a, i, motivo=True):
    """Regra das Tartarugas (anos 80): entra quando rompe a máxima de 20 dias, sai quando perde a mínima de 10."""
    c, hi, lo = a.s.c[i], a.max20d[i], a.min10d[i]
    if c > hi:
        v, txt = 1.0, "Rompeu a máxima de 20 dias: pode ser o começo de uma alta forte"
    elif c < lo:
        v, txt = -1.0, "Perdeu a mínima de 10 dias: se havia tendência, acabou"
    else:
        pos = 0.5 if hi == lo else (c - lo) / (hi - lo)
        v, txt = 0.0, f"Entre a mínima de 10 dias e a máxima de 20 ({pos * 100:.0f}% do caminho até o rompimento)"
    return v, (txt if motivo else "")


def macro(a, i, motivo=True):
    v, txt = a.macro.get(a.s.t[i], (0.0, "Sem leitura do BTC"))
    return v, (txt if motivo else "")


def sentimento_(a, i, motivo=True):
    val = sentimento.valor_em(a.s.t[i], a.fng) if a.fng else None
    if val is None:
        return 0.0, ("Sem índice de medo e ganância hoje" if motivo else "")
    if val <= 20:
        v = 0.4
    elif val <= 35:
        v = 0.15
    elif val >= 80:
        v = -0.4
    elif val >= 65:
        v = -0.15
    else:
        v = 0.0
    if not motivo:
        return v, ""
    nota = {0.4: "medo extremo costuma ser oportunidade", 0.15: "medo no ar, leve viés de compra",
            -0.4: "euforia demais, hora de cautela", -0.15: "ganância subindo, cautela"}.get(v, "humor neutro")
    return v, f"Medo e Ganância em {val} ({sentimento.rotulo(val)}): {nota}"


AGENTES = [
    {"id": "tendencia_longa", "nome": "Tendência longa", "funcao": tendencia_longa},
    {"id": "tendencia", "nome": "Tendência curta", "funcao": tendencia},
    {"id": "momento", "nome": "Momento", "funcao": momento},
    {"id": "reversao", "nome": "Reversão", "funcao": reversao},
    {"id": "rompimento", "nome": "Rompimento curto", "funcao": rompimento},
    {"id": "rompimento_longo", "nome": "Rompimento 20 dias", "funcao": rompimento_longo},
    {"id": "macro", "nome": "Macro", "funcao": macro},
    {"id": "sentimento", "nome": "Sentimento", "funcao": sentimento_},
]
IDS = [ag["id"] for ag in AGENTES]
NOMES = {ag["id"]: ag["nome"] for ag in AGENTES}


def votar(a, i, motivo=True):
    """{id_agente: (valor, motivo)}"""
    return {ag["id"]: ag["funcao"](a, i, motivo) for ag in AGENTES}


def matriz_votos(a):
    """Votos (só valores) de todos os candles, para o backtest rodar rápido."""
    out = [None] * len(a.s)
    for i in range(len(a.s)):
        if a.pronto(i):
            out[i] = {ag["id"]: ag["funcao"](a, i, False)[0] for ag in AGENTES}
    return out
