"""Indicadores técnicos em Python puro. Cada função devolve uma lista do mesmo
tamanho da entrada, com None onde ainda não há dados suficientes."""
import math


def sma(x, n):
    out = [None] * len(x)
    s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(x, n):
    out = [None] * len(x)
    if len(x) < n:
        return out
    k = 2 / (n + 1)
    m = sum(x[:n]) / n
    out[n - 1] = m
    for i in range(n, len(x)):
        m = x[i] * k + m * (1 - k)
        out[i] = m
    return out


def _wilder(x, n, inicio):
    """Média de Wilder (usada no RSI, ATR e ADX) começando no índice `inicio`."""
    out = [None] * len(x)
    if len(x) < inicio + n:
        return out
    m = sum(x[inicio:inicio + n]) / n
    out[inicio + n - 1] = m
    for i in range(inicio + n, len(x)):
        m = (m * (n - 1) + x[i]) / n
        out[i] = m
    return out


def rsi(c, n=14):
    ganhos = [0.0] * len(c)
    perdas = [0.0] * len(c)
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        ganhos[i] = d if d > 0 else 0.0
        perdas[i] = -d if d < 0 else 0.0
    mg, mp = _wilder(ganhos, n, 1), _wilder(perdas, n, 1)
    out = [None] * len(c)
    for i in range(len(c)):
        if mg[i] is None:
            continue
        out[i] = 100.0 if mp[i] == 0 else 100 - 100 / (1 + mg[i] / mp[i])
    return out


def macd(c, rapida=12, lenta=26, sinal=9):
    er, el = ema(c, rapida), ema(c, lenta)
    linha = [None if a is None or b is None else a - b for a, b in zip(er, el)]
    validos = [v for v in linha if v is not None]
    sig_v = ema(validos, sinal)
    sig = [None] * len(c)
    off = len(c) - len(validos)
    for j, v in enumerate(sig_v):
        sig[off + j] = v
    hist = [None if a is None or b is None else a - b for a, b in zip(linha, sig)]
    return linha, sig, hist


def bollinger(c, n=20, k=2.0):
    meio = [None] * len(c)
    cima = [None] * len(c)
    baixo = [None] * len(c)
    pctb = [None] * len(c)
    s = s2 = 0.0
    for i, v in enumerate(c):
        s += v; s2 += v * v
        if i >= n:
            s -= c[i - n]; s2 -= c[i - n] ** 2
        if i >= n - 1:
            m = s / n
            dp = math.sqrt(max(s2 / n - m * m, 0.0))
            meio[i], cima[i], baixo[i] = m, m + k * dp, m - k * dp
            larg = cima[i] - baixo[i]
            pctb[i] = 0.5 if larg == 0 else (v - baixo[i]) / larg
    return meio, cima, baixo, pctb


def true_range(h, l, c):
    tr = [h[0] - l[0]]
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return tr


def atr(h, l, c, n=14):
    return _wilder(true_range(h, l, c), n, 0)


def adx(h, l, c, n=14):
    tam = len(c)
    pdm = [0.0] * tam
    mdm = [0.0] * tam
    for i in range(1, tam):
        up, down = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm[i] = up if up > down and up > 0 else 0.0
        mdm[i] = down if down > up and down > 0 else 0.0
    tr = true_range(h, l, c)
    atr_ = _wilder(tr, n, 1)
    pdi_s, mdi_s = _wilder(pdm, n, 1), _wilder(mdm, n, 1)
    pdi = [None] * tam
    mdi = [None] * tam
    dx = [0.0] * tam
    primeiro = None
    for i in range(tam):
        if atr_[i] is None or atr_[i] == 0:
            continue
        pdi[i] = 100 * pdi_s[i] / atr_[i]
        mdi[i] = 100 * mdi_s[i] / atr_[i]
        soma = pdi[i] + mdi[i]
        dx[i] = 0.0 if soma == 0 else 100 * abs(pdi[i] - mdi[i]) / soma
        if primeiro is None:
            primeiro = i
    out = [None] * tam
    if primeiro is not None:
        out = _wilder(dx, n, primeiro)
    return out, pdi, mdi


def donchian(h, l, n=20):
    """Máxima e mínima dos n candles ANTERIORES (sem o atual), para detectar rompimentos."""
    alto = [None] * len(h)
    baixo = [None] * len(h)
    for i in range(n, len(h)):
        alto[i] = max(h[i - n:i])
        baixo[i] = min(l[i - n:i])
    return alto, baixo


def zscore(x, n=20):
    out = [None] * len(x)
    s = s2 = 0.0
    for i, v in enumerate(x):
        s += v; s2 += v * v
        if i >= n:
            s -= x[i - n]; s2 -= x[i - n] ** 2
        if i >= n - 1:
            m = s / n
            dp = math.sqrt(max(s2 / n - m * m, 0.0))
            out[i] = 0.0 if dp == 0 else (v - m) / dp
    return out


def vol_retornos(c, passo=24, janela=720):
    """Desvio padrão dos retornos de `passo` candles (ex.: 24 = um dia em 1h) nas últimas `janela` velas.
    Mede o tamanho de um dia "normal" de oscilação, em fração do preço."""
    tam = len(c)
    r = [0.0] * tam
    for i in range(passo, tam):
        r[i] = c[i] / c[i - passo] - 1
    out = [None] * tam
    s = s2 = 0.0
    ini = passo
    for i in range(ini, tam):
        s += r[i]; s2 += r[i] * r[i]
        if i - ini >= janela:
            v = r[i - janela]
            s -= v; s2 -= v * v
        if i - ini >= janela - 1:
            m = s / janela
            out[i] = math.sqrt(max(s2 / janela - m * m, 1e-12))
    return out


def max_min_janela(h, l, n):
    """Máxima e mínima dos n candles ANTERIORES (sem o atual), em O(n) com filas monotônicas."""
    from collections import deque
    tam = len(h)
    alto = [None] * tam
    baixo = [None] * tam
    qa, qb = deque(), deque()
    for i in range(tam):
        if i >= n:
            alto[i] = h[qa[0]]
            baixo[i] = l[qb[0]]
        while qa and qa[0] <= i - n:
            qa.popleft()
        while qb and qb[0] <= i - n:
            qb.popleft()
        while qa and h[qa[-1]] <= h[i]:
            qa.pop()
        qa.append(i)
        while qb and l[qb[-1]] >= l[i]:
            qb.pop()
        qb.append(i)
    return alto, baixo
