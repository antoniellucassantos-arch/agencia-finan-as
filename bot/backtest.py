"""Backtest: roda os robôs sobre meses de preços reais do passado e compara com o
"comprar e segurar". Uso:  python -m bot.backtest  [--dias 180]
"""
import argparse
import math
import os
import time

from . import sentimento
from .agentes import IDS, NOMES, Analise, aquecimento, matriz_votos, regime_macro
from .binance import INTERVALO_MS, historico, usdt_brl
from .carteira import Carteira
from .perfis import carregar_perfis
from .robo import Robo, placar_valores
from .util import RELATORIOS, carregar_config, data_hora, nome_moeda, salvar_json

HORIZONTE_ACERTO = 4  # candles à frente para medir se o agente acertou a direção


def preparar(cfg, dias, avisar=print):
    iv_txt = cfg["tempo_grafico"]
    moedas = list(cfg["moedas"])
    avisar(f"Baixando/atualizando {dias} dias de candles de {iv_txt}...")
    series = {m: historico(m, iv_txt, dias, avisar) for m in moedas}
    btc = series.get("BTCUSDT") or historico("BTCUSDT", iv_txt, dias, avisar)
    macro = regime_macro(btc)
    fng = sentimento.tabela()
    analises, votos = {}, {}
    avisar("Calculando indicadores e votos dos agentes...")
    for m, s in series.items():
        a = Analise(s, macro, fng)
        analises[m] = a
        votos[m] = matriz_votos(a)
    # pré-calcula o que não muda entre robôs: a ordem dos candles e os dados de cada moeda/candle
    indices = {m: {t: i for i, t in enumerate(s.t)} for m, s in series.items()}
    passos = []
    for t in btc.t:
        passos.append((t, [(m, indices[m][t]) for m in series if t in indices[m]]))
    itens = {m: [analises[m].item(i, 0.0) if votos[m][i] is not None else None for i in range(len(s))]
             for m, s in series.items()}
    for m in series:
        for i, it in enumerate(itens[m]):
            if it is not None:
                it["votos"] = votos[m][i]
    return {"series": series, "analises": analises, "votos": votos, "btc": btc, "iv": INTERVALO_MS[iv_txt],
            "passos": passos, "itens": itens}


def simular(perfil, base, cfg, capital, ini=None, fim=None, guardar_eventos=False):
    series, iv, itens_base = base["series"], base["iv"], base["itens"]
    pesos = perfil["pesos"]
    robo = Robo(perfil, Carteira(capital, cfg["taxa"], cfg["derrapagem"]), iv)
    precos, curva, eventos = {}, [], []
    for t, lista in base["passos"]:
        if ini is not None and t < ini:
            continue
        if fim is not None and t >= fim:
            break
        itens, ev = {}, []
        for m, i in lista:
            s = series[m]
            precos[m] = s.c[i]
            if m in robo.cart.posicoes:
                robo.checar_protecoes(m, t + iv, s.o[i], s.h[i], s.l[i], ev)
            it = itens_base[m][i]
            if it is None:
                continue
            it["score"] = placar_valores(it["votos"], pesos)
            itens[m] = it
        ev += robo.ao_fechar(t + iv, itens, precos)
        if guardar_eventos:
            eventos += [e for e in ev if e["tipo"] != "rejeitado"]
        curva.append((t + iv, robo.cart.patrimonio(precos)))
    return {"robo": robo, "curva": curva, "eventos": eventos, "precos": precos}


def comprar_e_segurar(base, cfg, capital, ini=None, fim=None):
    """Divide o dinheiro igualmente entre as moedas no começo e não mexe mais."""
    series, iv = base["series"], base["iv"]
    qtd, curva = {}, []
    t0 = None
    indices = {m: {t: i for i, t in enumerate(s.t)} for m, s in series.items()}
    precos = {}
    for t in base["btc"].t:
        if ini is not None and t < ini:
            continue
        if fim is not None and t >= fim:
            break
        for m, s in series.items():
            i = indices[m].get(t)
            if i is not None:
                precos[m] = s.c[i]
        if t0 is None and len(precos) == len(series):
            t0 = t
            fatia = capital / len(series) * (1 - cfg["taxa"] - cfg["derrapagem"])
            qtd = {m: fatia / precos[m] for m in series}
        if t0 is not None:
            curva.append((t + iv, sum(qtd[m] * precos[m] for m in series)))
    return curva


def metricas(curva, trades, iv, capital):
    if not curva:
        return {}
    final = curva[-1][1]
    pico, mdd = capital, 0.0
    rets = []
    ant = capital
    for _, v in curva:
        pico = max(pico, v)
        mdd = max(mdd, (pico - v) / pico if pico else 0)
        rets.append(v / ant - 1 if ant else 0)
        ant = v
    n = len(rets)
    media = sum(rets) / n
    dp = math.sqrt(sum((r - media) ** 2 for r in rets) / n) if n > 1 else 0
    por_ano = 365 * 86_400_000 / iv
    sharpe = (media / dp * math.sqrt(por_ano)) if dp else 0.0
    ganhos = [t["lucro"] for t in trades if t["lucro"] > 0]
    perdas = [-t["lucro"] for t in trades if t["lucro"] <= 0]
    return {
        "retorno_pct": (final / capital - 1) * 100,
        "max_queda_pct": mdd * 100,
        "sharpe": sharpe,
        "trades": len(trades),
        "acerto_pct": len(ganhos) / len(trades) * 100 if trades else 0.0,
        "fator_lucro": (sum(ganhos) / sum(perdas)) if perdas and sum(perdas) > 0 else (float("inf") if ganhos else 0.0),
        "media_trade_pct": sum(t["lucro_pct"] for t in trades) / len(trades) if trades else 0.0,
        "final": final,
    }


def acerto_agentes(base, ini=None, fim=None, minimo=0.3):
    """Para cada agente: quando votou forte, o preço foi para o lado que ele disse nas próximas horas?"""
    tot = {k: 0 for k in IDS}
    certos = {k: 0 for k in IDS}
    for m, s in base["series"].items():
        vts = base["votos"][m]
        for i in range(len(s) - HORIZONTE_ACERTO):
            t = s.t[i]
            if (ini is not None and t < ini) or (fim is not None and t >= fim) or vts[i] is None:
                continue
            mov = s.c[i + HORIZONTE_ACERTO] - s.c[i]
            for k, v in vts[i].items():
                if abs(v) >= minimo:
                    tot[k] += 1
                    if (v > 0) == (mov > 0):
                        certos[k] += 1
    return {k: {"votos": tot[k], "acerto_pct": certos[k] / tot[k] * 100 if tot[k] else None} for k in IDS}


def _fmt_linha(nome, m):
    fl = m["fator_lucro"]
    fl_txt = "∞" if fl == float("inf") else f"{fl:.2f}"
    return (f"| {nome} | {m['retorno_pct']:+.2f}% | {m['max_queda_pct']:.2f}% | {m['sharpe']:.2f} | "
            f"{m['trades']} | {m['acerto_pct']:.0f}% | {fl_txt} | {m['media_trade_pct']:+.2f}% |")


CABECALHO = ("| Robô | Retorno | Maior queda | Sharpe | Operações | Acerto | Fator de lucro | Média por operação |\n"
             "|---|---|---|---|---|---|---|---|")


def rodar(cfg, dias, avisar=print):
    inicio = time.time()
    base = preparar(cfg, dias, avisar)
    capital = cfg["saldo_inicial_brl"] / usdt_brl()
    perfis = carregar_perfis()
    btc = base["btc"]
    aq = aquecimento(cfg["tempo_grafico"])
    ini = btc.t[aq] if len(btc) > aq else None  # pula o aquecimento dos indicadores
    resultados = {}
    for pid, p in perfis.items():
        avisar(f"Simulando {p['nome']}...")
        r = simular(p, base, cfg, capital, ini=ini)
        resultados[pid] = {"metricas": metricas(r["curva"], r["robo"].cart.trades, base["iv"], capital),
                           "curva": r["curva"], "trades": r["robo"].cart.trades}
    hodl = comprar_e_segurar(base, cfg, capital, ini=ini)
    m_hodl = metricas(hodl, [], base["iv"], capital)
    acertos = acerto_agentes(base, ini=ini)

    periodo = f"{data_hora(ini or btc.t[0])} até {data_hora(btc.t[-1])}"
    linhas = [f"# Backtest da Agência Cripto\n",
              f"Período: {periodo} ({dias} dias, candles de {cfg['tempo_grafico']}), {len(base['series'])} moedas.",
              f"Capital fictício: R$ {cfg['saldo_inicial_brl']:,.0f} (≈ {capital:,.0f} USDT). Taxa {cfg['taxa'] * 100:.2f}% + derrapagem {cfg['derrapagem'] * 100:.2f}% por ordem.\n",
              CABECALHO]
    for pid, res in resultados.items():
        linhas.append(_fmt_linha(perfis[pid]["nome"] + (" (otimizado)" if perfis[pid].get("otimizado") else ""), res["metricas"]))
    linhas.append(_fmt_linha("Comprar e segurar", m_hodl))
    linhas.append("\n## Quem acerta mais (direção nas próximas horas quando vota forte)\n")
    linhas.append("| Agente | Votos fortes | Acerto |\n|---|---|---|")
    for k, v in acertos.items():
        acerto = "-" if v["acerto_pct"] is None else f"{v['acerto_pct']:.1f}%"
        linhas.append(f"| {NOMES[k]} | {v['votos']} | {acerto} |")
    linhas.append("\n## Desempenho por moeda (robô Equilibrado)\n")
    linhas.append("| Moeda | Operações | Lucro total (USDT) | Acerto |\n|---|---|---|---|")
    por_moeda = {}
    for tr in resultados.get("equilibrado", {}).get("trades", []):
        d = por_moeda.setdefault(tr["simbolo"], [0, 0.0, 0])
        d[0] += 1; d[1] += tr["lucro"]; d[2] += tr["lucro"] > 0
    for sim, (n, lucro, ganhos) in sorted(por_moeda.items(), key=lambda x: -x[1][1]):
        linhas.append(f"| {nome_moeda(sim)} | {n} | {lucro:+.2f} | {ganhos / n * 100:.0f}% |")
    linhas.append("\n> Resultado passado não garante resultado futuro. Dinheiro fictício, só para estudo.")
    texto = "\n".join(linhas)
    with open(os.path.join(RELATORIOS, "backtest.md"), "w", encoding="utf-8") as f:
        f.write(texto)

    def reduzir(curva, n=300):
        passo = max(1, len(curva) // n)
        return [[t, round(v, 2)] for t, v in curva[::passo]]

    salvar_json(os.path.join(RELATORIOS, "backtest.json"), {
        "periodo": periodo, "dias": dias, "capital_usdt": capital,
        "robos": {pid: {"nome": perfis[pid]["nome"], "metricas": r["metricas"], "curva": reduzir(r["curva"])} for pid, r in resultados.items()},
        "hodl": {"metricas": m_hodl, "curva": reduzir(hodl)}, "acertos": acertos,
    })
    avisar("\n" + texto)
    avisar(f"\nRelatório salvo em relatorios/backtest.md ({time.time() - inicio:.0f}s)")
    return resultados, m_hodl, acertos


def main():
    cfg = carregar_config()
    ap = argparse.ArgumentParser(description="Backtest dos robôs da Agência Cripto")
    ap.add_argument("--dias", type=int, default=cfg["dias_backtest"])
    ap.add_argument("--tempo", default=cfg["tempo_grafico"], help="tempo gráfico, ex.: 15m, 1h, 4h")
    args = ap.parse_args()
    cfg["tempo_grafico"] = args.tempo
    rodar(cfg, args.dias)


if __name__ == "__main__":
    main()
