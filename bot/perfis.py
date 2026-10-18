"""Os três robôs da agência. Mesmos agentes, temperamentos diferentes: cada um tem
sua própria carteira fictícia e todos competem entre si (e contra o "comprar e segurar").

Glossário dos parâmetros:
- pesos: quanto a voz de cada agente conta no placar (-1 a +1).
- exige: votos mínimos de agentes específicos para poder comprar.
- decide_a_cada: de quanto em quanto tempo o robô reavalia entradas e saídas por sinal
  (os stops de proteção são checados o tempo todo).
- base_stop: "vol" usa a oscilação diária típica da moeda; "atr" usa a oscilação do candle.
- stop_k / trail_k / empate_k / alvo_k: distâncias em múltiplos dessa base (0 desliga).
- risco_por_trade: quanto da carteira se perde se o stop for atingido.

Parâmetros otimizados pelo backtest ficam em relatorios/perfis_otimizados.json e
substituem estes padrões quando existem.
"""
import copy
import os

from .util import RELATORIOS, ler_json

PERFIS = {
    "tartaruga": {
        "nome": "Tartaruga", "estilo": "Conservador",
        "descricao": "Segue só a tendência longa (50 dias). Decide uma vez por dia, fica em caixa nas quedas.",
        "pesos": {"tendencia_longa": 1.0},
        "exige": {"tendencia_longa": 1.0},
        "decide_a_cada": "1d",
        "limiar_entrada": 0.99, "limiar_saida": -0.3,
        "base_stop": "vol", "risco_por_trade": 0.015, "stop_k": 3.0, "trail_k": 0, "empate_k": 0, "alvo_k": 0,
        "saida_na_media": False, "max_velas": 0,
        "max_por_moeda": 0.125, "max_exposicao": 1.0, "max_posicoes": 8,
        "perda_diaria_max": 0.06, "espera_apos_stop": 72, "fator_macro_ruim": 1.0,
    },
    "equilibrado": {
        "nome": "Equilibrado", "estilo": "Moderado",
        "descricao": "Tendência longa confirmada pelos outros agentes. Decide a cada 4h e protege o lucro com stop móvel.",
        "pesos": {"tendencia_longa": 2.0, "tendencia": 1.0, "momento": 0.5, "rompimento": 0.5, "macro": 1.0, "sentimento": 0.3},
        "exige": {"tendencia_longa": 0.3},
        "decide_a_cada": "4h",
        "limiar_entrada": 0.5, "limiar_saida": -0.1,
        "base_stop": "vol", "risco_por_trade": 0.012, "stop_k": 2.5, "trail_k": 3.0, "empate_k": 1.5, "alvo_k": 0,
        "saida_na_media": False, "max_velas": 0,
        "max_por_moeda": 0.18, "max_exposicao": 0.9, "max_posicoes": 6,
        "perda_diaria_max": 0.05, "espera_apos_stop": 24, "fator_macro_ruim": 0.5,
    },
    "foguete": {
        "nome": "Foguete", "estilo": "Agressivo",
        "descricao": "Regra das Tartarugas: compra quem rompe a máxima de 20 dias, vende quando perde a mínima de 10. Concentra mais e arrisca mais.",
        "pesos": {"rompimento_longo": 1.0},
        "exige": {"rompimento_longo": 1.0},
        "decide_a_cada": "4h",
        "limiar_entrada": 0.99, "limiar_saida": -0.99,
        "base_stop": "vol", "risco_por_trade": 0.02, "stop_k": 2.0, "trail_k": 0, "empate_k": 0, "alvo_k": 0,
        "saida_na_media": False, "max_velas": 0,
        "max_por_moeda": 0.30, "max_exposicao": 1.0, "max_posicoes": 5,
        "perda_diaria_max": 0.08, "espera_apos_stop": 24, "fator_macro_ruim": 1.0,
    },
}

ARQ_OTIMIZADOS = os.path.join(RELATORIOS, "perfis_otimizados.json")


def carregar_perfis(usar_otimizados=True):
    perfis = copy.deepcopy(PERFIS)
    if usar_otimizados:
        ajustes = ler_json(ARQ_OTIMIZADOS, {}) or {}
        for pid, campos in ajustes.items():
            if pid in perfis:
                perfis[pid].update(campos.get("parametros", {}))
                perfis[pid]["otimizado"] = True
    for pid, p in perfis.items():
        p["id"] = pid
    return perfis
