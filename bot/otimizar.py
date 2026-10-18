"""Otimização honesta (walk-forward): ajusta os parâmetros num período de TREINO e só
aceita a mudança se ela também for melhor num período de TESTE que o ajuste nunca viu.
Isso evita "decorar o passado". Uso:  python -m bot.otimizar  [--nao-aplicar]
"""
import argparse
import copy
import itertools
import json
import os
import time

from .agentes import aquecimento
from .backtest import metricas, preparar, simular, comprar_e_segurar
from .binance import usdt_brl
from .perfis import ARQ_OTIMIZADOS, PERFIS
from .util import RELATORIOS, carregar_config, data_hora, salvar_json

GRADES = {
    "tartaruga": {"limiar_saida": [-0.3, 0.3], "stop_k": [2.0, 3.0, 4.0], "decide_a_cada": ["1d", "4h"]},
    "equilibrado": {"limiar_entrada": [0.4, 0.5, 0.6], "limiar_saida": [-0.3, -0.1, 0.1], "trail_k": [2.5, 3.5], "stop_k": [2.0, 3.0]},
    "foguete": {"stop_k": [1.5, 2.0, 3.0], "risco_por_trade": [0.015, 0.02, 0.03], "decide_a_cada": ["1d", "4h"]},
}
MIN_TRADES = 15


def nota(m):
    """Sharpe, desde que o robô tenha operado o suficiente para o número significar algo."""
    if not m or m["trades"] < MIN_TRADES:
        return -9.0
    return m["sharpe"]


def resumo(m):
    return f"{m['retorno_pct']:+.1f}% | queda {m['max_queda_pct']:.1f}% | Sharpe {m['sharpe']:.2f} | {m['trades']} op."


def main():
    cfg = carregar_config()
    ap = argparse.ArgumentParser(description="Otimização walk-forward dos robôs")
    ap.add_argument("--dias", type=int, default=cfg["dias_backtest"])
    ap.add_argument("--treino", type=int, default=cfg["dias_treino"], help="dias usados para ajustar")
    ap.add_argument("--nao-aplicar", action="store_true", help="só gera o relatório")
    args = ap.parse_args()

    inicio = time.time()
    base = preparar(cfg, args.dias)
    capital = cfg["saldo_inicial_brl"] / usdt_brl()
    t = base["btc"].t
    aq = aquecimento(cfg["tempo_grafico"])
    ini = t[aq]
    corte = ini + args.treino * 86_400_000
    fim = t[-1] + base["iv"]
    iv = base["iv"]

    def avaliar(perfil, a, b):
        r = simular(perfil, base, cfg, capital, ini=a, fim=b)
        return metricas(r["curva"], r["robo"].cart.trades, iv, capital)

    hodl_tr = metricas(comprar_e_segurar(base, cfg, capital, ini, corte), [], iv, capital)
    hodl_te = metricas(comprar_e_segurar(base, cfg, capital, corte, fim), [], iv, capital)
    linhas = ["# Otimização walk-forward\n",
              f"Treino: {data_hora(ini)} até {data_hora(corte)} · Teste (nunca visto no ajuste): {data_hora(corte)} até {data_hora(fim)}\n",
              f"Comprar e segurar — treino: {resumo(hodl_tr)} · teste: {resumo(hodl_te)}\n"]
    aplicados = {}
    for pid, grade in GRADES.items():
        padrao = dict(PERFIS[pid], id=pid)
        m_tr0, m_te0 = avaliar(padrao, ini, corte), avaliar(padrao, corte, fim)
        chaves = list(grade)
        melhor = (nota(m_tr0), {}, m_tr0)
        testados = 0
        for combo in itertools.product(*(grade[k] for k in chaves)):
            p = copy.deepcopy(padrao)
            mud = dict(zip(chaves, combo))
            p.update(mud)
            m = avaliar(p, ini, corte)
            testados += 1
            if nota(m) > melhor[0]:
                melhor = (nota(m), mud, m)
        _, mud, m_tr1 = melhor
        p1 = dict(copy.deepcopy(padrao), **mud)
        m_te1 = avaliar(p1, corte, fim)
        aceito = bool(mud) and nota(m_te1) > nota(m_te0)
        linhas.append(f"## {padrao['nome']} ({testados} combinações)\n")
        linhas.append(f"- Padrão — treino: {resumo(m_tr0)} · teste: {resumo(m_te0)}")
        if mud:
            linhas.append(f"- Melhor no treino {json.dumps(mud, ensure_ascii=False)} — treino: {resumo(m_tr1)} · teste: {resumo(m_te1)}")
        linhas.append(f"- Decisão: **{'aplicar' if aceito else 'manter o padrão'}**"
                      + ("" if aceito else " (o ajuste não melhorou no período de teste)" if mud else " (o padrão já era o melhor no treino)") + "\n")
        if aceito:
            aplicados[pid] = {"parametros": mud, "teste": m_te1, "teste_padrao": m_te0}
        print(f"{padrao['nome']}: {'aplicar ' + json.dumps(mud, ensure_ascii=False) if aceito else 'manter padrão'}")

    texto = "\n".join(linhas) + "\n> Mesmo validado, resultado passado não garante resultado futuro."
    with open(os.path.join(RELATORIOS, "otimizacao.md"), "w", encoding="utf-8") as f:
        f.write(texto)
    if not args.nao_aplicar:
        if aplicados:
            salvar_json(ARQ_OTIMIZADOS, aplicados)
        elif os.path.exists(ARQ_OTIMIZADOS):
            os.remove(ARQ_OTIMIZADOS)
    print("\n" + texto)
    print(f"\nRelatório em relatorios/otimizacao.md ({time.time() - inicio:.0f}s)")


if __name__ == "__main__":
    main()
