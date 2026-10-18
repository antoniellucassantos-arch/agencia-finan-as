# Otimização walk-forward

Treino: 10/12 00:00 até 28/05 00:00 · Teste (nunca visto no ajuste): 28/05 00:00 até 18/10 00:00

Comprar e segurar — treino: +357.2% | queda 54.7% | Sharpe 1.25 | 0 op. · teste: -34.2% | queda 67.5% | Sharpe -0.26 | 0 op.

## Tartaruga (12 combinações)

- Padrão — treino: +235.5% | queda 35.0% | Sharpe 1.34 | 184 op. · teste: +2.4% | queda 37.6% | Sharpe 0.21 | 111 op.
- Melhor no treino {"limiar_saida": -0.3, "stop_k": 4.0, "decide_a_cada": "1d"} — treino: +286.5% | queda 32.6% | Sharpe 1.49 | 183 op. · teste: +3.2% | queda 35.1% | Sharpe 0.23 | 110 op.
- Decisão: **aplicar**

## Equilibrado (36 combinações)

- Padrão — treino: +87.0% | queda 23.2% | Sharpe 0.98 | 494 op. · teste: -2.6% | queda 30.5% | Sharpe 0.05 | 239 op.
- Melhor no treino {"limiar_entrada": 0.4, "limiar_saida": -0.3, "trail_k": 3.5, "stop_k": 3.0} — treino: +129.0% | queda 24.5% | Sharpe 1.25 | 412 op. · teste: +6.2% | queda 23.9% | Sharpe 0.30 | 204 op.
- Decisão: **aplicar**

## Foguete (18 combinações)

- Padrão — treino: +352.1% | queda 30.8% | Sharpe 1.58 | 65 op. · teste: -9.1% | queda 46.0% | Sharpe -0.09 | 53 op.
- Melhor no treino {"stop_k": 3.0, "risco_por_trade": 0.015, "decide_a_cada": "4h"} — treino: +323.9% | queda 29.1% | Sharpe 1.60 | 68 op. · teste: +12.8% | queda 32.8% | Sharpe 0.46 | 42 op.
- Decisão: **aplicar**

> Mesmo validado, resultado passado não garante resultado futuro.