# Agência Cripto

Uma agência de trading de mentira: agentes analisam o mercado de verdade, três robôs
operam carteiras **fictícias** de R$ 10.000 com **preços reais da Binance**, e um
escritório 3D mostra todo mundo trabalhando.

> É um simulador para aprender. Não opera dinheiro de verdade, não se conecta à sua
> conta em corretora nenhuma e nada aqui é recomendação de investimento.

## Como usar

1. Tenha o Python instalado (3.10 ou mais novo). Não precisa instalar mais nada.
2. Dê dois cliques em **`iniciar.bat`**. O escritório abre no navegador em
   <http://localhost:8787>.
3. Deixe a janela preta aberta. Os robôs só operam enquanto ela está rodando.
   Pode fechar quando quiser: tudo fica salvo em `estado/` e continua de onde parou.

Outros atalhos:

| Arquivo | O que faz |
|---|---|
| `backtest.bat` | Testa os robôs em ~4 anos de preços passados e compara com "comprar e segurar". |
| `otimizar.bat` | Ajusta os robôs no passado e só aceita o ajuste se ele também funcionar num período que ele não viu. |
| `recomecar_do_zero.bat` | Zera as carteiras e recomeça com o saldo inicial. |

## Quem trabalha na agência

**Agentes** (cada um vota de −1 a +1 em cada moeda, com o motivo escrito):

| Agente | O que olha |
|---|---|
| Tendência longa | Preço contra a média de 50 dias e a força dos últimos 30 dias. A voz mais importante. |
| Tendência curta | Médias de 20 e 50 velas e a força da tendência (ADX). |
| Momento | MACD e RSI: se a subida está ganhando ou perdendo força. |
| Reversão | Bandas de Bollinger e RSI: quedas ou altas exageradas. |
| Rompimento curto | Preço saindo do canal das últimas 20 velas. |
| Rompimento 20 dias | A regra das Tartarugas: rompeu a máxima de 20 dias ou perdeu a mínima de 10. |
| Macro | O humor do mercado pelo Bitcoin num tempo gráfico maior. |
| Sentimento | Índice de Medo e Ganância. |

**Gerente de Risco e Compliance:** aprovam cada compra. Definem o tamanho da posição
(quanto se perde se der errado), o stop, o limite de perda do dia, a quarentena depois de
um stop e as regras (sem alavancagem, sem vender a descoberto, ordem mínima de 10 USDT).

**Os três robôs** (mesmos agentes, temperamentos diferentes, carteiras separadas):

| Robô | Estilo | Como decide |
|---|---|---|
| Tartaruga | Conservador | Só a tendência longa. Reavalia uma vez por dia (21h) e fica em caixa nas quedas. |
| Equilibrado | Moderado | Tendência longa confirmada pelos outros agentes, a cada 4h, com stop móvel. |
| Foguete | Agressivo | Regra das Tartarugas: compra rompimentos de 20 dias, vende quando perde a mínima de 10. |

## O que os testes mostraram

Backtest de ~4 anos (dez/2022 a out/2026), 8 moedas, velas de 1h, com taxa de 0,10% e
derrapagem de 0,05% em cada ordem:

| Robô | Retorno | Maior queda |
|---|---|---|
| Foguete | +360% | 32% |
| Tartaruga | +301% | 35% |
| Equilibrado | +147% | 26% |
| Comprar e segurar | +193% | 69% |

No último ano e meio, que o otimizador **não usou** para ajustar nada, o mercado caiu 34%
(com queda máxima de 68%) e os três robôs terminaram positivos: Foguete +12,8%,
Equilibrado +6,2%, Tartaruga +3,2%. Os detalhes estão em `relatorios/`.

O que **não** funcionou, e por isso ficou de fora: estratégias rápidas (velas de 15 min,
compra de quedas de curto prazo). Elas acertam a direção com frequência, mas ganham pouco
por operação e as taxas comem tudo.

Resultado passado não garante resultado futuro. Robôs de tendência acertam só 25 a 40%
das operações: perdem pouco muitas vezes e ganham muito poucas vezes.

## Pedir uma análise ao Claude

A cada vela o robô escreve `estado/resumo_para_claude.md`, com patrimônio, posições,
últimas operações e os votos de cada agente. No Claude Code, abra esta pasta e peça
"analisa o bot". Isso usa o seu plano do Claude, sem API paga.

## Ajustes

Em `config.json`: moedas, tempo gráfico, saldo inicial, taxas, porta do escritório e
período do backtest. Os parâmetros de cada robô ficam em `bot/perfis.py`; os ajustes
aprovados pelo otimizador ficam em `relatorios/perfis_otimizados.json`. Apague esse
arquivo para voltar aos padrões.

## Arquivos

```
bot/          o robô (Python puro, sem dependências)
  binance.py    dados públicos da Binance, com cache em dados/
  agentes.py    os agentes e seus votos
  robo.py       decisão, Gerente de Risco e Compliance
  carteira.py   carteira fictícia com taxas e derrapagem
  perfis.py     os três robôs
  backtest.py   teste no passado
  otimizar.py   ajuste com validação em período separado
  aovivo.py     modo ao vivo e servidor do escritório
escritorio/   a página 3D (Three.js)
estado/       carteiras, histórico e eventos do modo ao vivo
relatorios/   resultados do backtest e da otimização
```

Quando o robô fica desligado, ele não vê o mercado. Ao voltar, se o preço tiver passado
de um stop, ele vende pelo preço atual, e decide na primeira vela que fechar.
