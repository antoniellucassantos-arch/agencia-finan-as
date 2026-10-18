"""Modo ao vivo: os três robôs operam carteiras fictícias com preços reais da Binance.

- Preços a cada poucos segundos: atualiza o patrimônio e checa stops.
- No fechamento de cada candle: os agentes votam e os robôs decidem.
- Servidor local em http://localhost:8787 com o escritório 3D e /api/estado.
- Tudo fica salvo em estado/, então dá para fechar e abrir de novo sem perder nada.

Uso:  python -m bot.aovivo           (continua de onde parou)
      python -m bot.aovivo --zerar   (recomeça as carteiras do zero)
"""
import argparse
import json
import os
import threading
import time
import traceback
import webbrowser
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import binance, sentimento
from .agentes import AGENTES, Analise, aquecimento, regime_macro, velas_por_dia, votar
from .binance import INTERVALO_MS
from .carteira import Carteira
from .perfis import carregar_perfis
from .robo import Robo, placar_valores, valores
from .util import ESCRITORIO, ESTADO, RELATORIOS, agora_ms, brl, carregar_config, data_hora, ler_json, nome_moeda, salvar_json

ARQ_ROBOS = os.path.join(ESTADO, "robos.json")
ARQ_HODL = os.path.join(ESTADO, "comprar_e_segurar.json")
ARQ_CURVAS = os.path.join(ESTADO, "curvas.json")
ARQ_EVENTOS = os.path.join(ESTADO, "eventos.jsonl")
ARQ_RESUMO = os.path.join(ESTADO, "resumo_para_claude.md")
MAX_VELAS = 2200
PONTO_CURVA_MS = 5 * 60_000
MAX_PONTOS = 2016  # 7 dias de pontos a cada 5 minutos


class AoVivo:
    def __init__(self, cfg, zerar=False):
        self.cfg = cfg
        self.moedas = list(cfg["moedas"])
        if "BTCUSDT" not in self.moedas:
            self.moedas.insert(0, "BTCUSDT")
        self.tg = cfg["tempo_grafico"]
        self.iv = INTERVALO_MS[self.tg]
        self.perfis = carregar_perfis()
        self.series = {}
        self.analises = {}
        self.votos = {}
        self.provisorio = {}
        self.precos = {}
        self.var24 = {}
        self.usdt_brl = 5.0
        self.eventos = deque(maxlen=200)
        self.curvas = {}
        self.status, self.msg = "iniciando", "Baixando histórico da Binance..."
        self.iniciado_em = agora_ms()
        self.ultima_vela = 0
        self.snapshot = b"{}"
        self._vistos = {}
        if zerar:
            for arq in (ARQ_ROBOS, ARQ_HODL, ARQ_CURVAS, ARQ_EVENTOS):
                if os.path.exists(arq):
                    os.remove(arq)

    # ------------------------------------------------------------ preparação
    def preparar(self):
        dias = int(aquecimento(self.tg) / velas_por_dia(self.tg)) + 20
        print(f"Carregando {dias} dias de candles de {self.tg} para aquecer os indicadores...")
        for m in self.moedas:
            self.series[m] = binance.historico(m, self.tg, dias, lambda *a: None)
        self.usdt_brl = binance.usdt_brl()
        self.precos = binance.precos(self.moedas)
        self.ultima_vela = self.series["BTCUSDT"].t[-1]
        self._recalcular()
        capital = self.cfg["saldo_inicial_brl"] / self.usdt_brl
        salvo = ler_json(ARQ_ROBOS, {}) or {}
        self.robos = {}
        for pid, p in self.perfis.items():
            if pid in salvo:
                self.robos[pid] = Robo.de_dict(p, salvo[pid], self.iv)
            else:
                self.robos[pid] = Robo(p, Carteira(capital, self.cfg["taxa"], self.cfg["derrapagem"]), self.iv)
        self.hodl = ler_json(ARQ_HODL)
        if not self.hodl:
            fatia = capital / len(self.moedas) * (1 - self.cfg["taxa"] - self.cfg["derrapagem"])
            self.hodl = {"capital": capital, "inicio": agora_ms(), "qtd": {m: fatia / self.precos[m] for m in self.moedas}}
            salvar_json(ARQ_HODL, self.hodl)
        self.curvas = ler_json(ARQ_CURVAS, {}) or {}
        for linha in self._ler_eventos(80):
            self.eventos.append(linha)
        if not salvo:
            self._evento({"t": agora_ms(), "robo": None, "tipo": "inicio", "moeda": None,
                          "texto": f"Agência aberta: cada robô começa com {brl(self.cfg['saldo_inicial_brl'])} fictícios"})
        self.salvar()
        self.status, self.msg = "ok", "Conectado à Binance"
        print(f"Pronto. {len(self.moedas)} moedas, 3 robôs, USDT/BRL {self.usdt_brl:.2f}.")

    def _ler_eventos(self, n):
        try:
            with open(ARQ_EVENTOS, encoding="utf-8") as f:
                return [json.loads(x) for x in f.readlines()[-n:]]
        except (OSError, ValueError):
            return []

    def _recalcular(self):
        macro = regime_macro(self.series["BTCUSDT"])
        fng = sentimento.tabela()
        for m, s in self.series.items():
            a = Analise(s, macro, fng)
            self.analises[m] = a
            i = len(s) - 1
            self.votos[m] = votar(a, i) if a.pronto(i) else {}

    def _recalcular_provisorio(self):
        """Votos com o candle que ainda está se formando: só para mostrar, não decide nada."""
        fng = sentimento.tabela()
        series = {}
        for m, s in self.series.items():
            try:
                aberto = binance.recentes(m, self.tg, limite=2, incluir_aberto=True)
            except binance.ErroBinance:
                return
            if not len(aberto) or aberto.t[-1] <= s.t[-1]:
                series[m] = s
                continue
            c = s.fatia(-1400)
            c.adicionar(aberto.t[-1], aberto.o[-1], aberto.h[-1], aberto.l[-1], aberto.c[-1], aberto.v[-1])
            series[m] = c
        macro = regime_macro(series["BTCUSDT"])
        for m, s in series.items():
            a = Analise(s, macro, fng)
            i = len(s) - 1
            if a.pronto(i):
                self.provisorio[m] = votar(a, i)

    # ------------------------------------------------------------ ciclo
    def atualizar_precos(self):
        self.precos = binance.precos(self.moedas)
        agora = agora_ms()
        for robo in self.robos.values():
            ev = []
            for m in list(robo.cart.posicoes):
                p = self.precos.get(m)
                if p:
                    robo.checar_protecoes(m, agora, p, p, p, ev)
            for e in ev:
                self._evento(e)
            if ev:
                self.salvar()
        self._ponto_curva(agora)

    def checar_vela_nova(self):
        novas = 0
        for m, s in self.series.items():
            r = binance.recentes(m, self.tg, limite=5)
            for k in range(len(r)):
                if r.t[k] > s.t[-1]:
                    s.adicionar(r.t[k], r.o[k], r.h[k], r.l[k], r.c[k], r.v[k])
                    novas += m == "BTCUSDT"
            if len(s) > MAX_VELAS:
                self.series[m] = s.fatia(-MAX_VELAS)
        btc_t = self.series["BTCUSDT"].t[-1]
        if btc_t <= self.ultima_vela:
            return False
        self.ultima_vela = btc_t
        self._recalcular()
        fecho = btc_t + self.iv
        precos_fecho = {m: s.c[-1] for m, s in self.series.items()}
        for pid, robo in self.robos.items():
            itens = {}
            for m, a in self.analises.items():
                i = len(a.s) - 1
                if a.s.t[i] != btc_t or not self.votos.get(m):
                    continue
                vt = valores(self.votos[m])
                it = a.item(i, placar_valores(vt, robo.p["pesos"]))
                it["votos"] = vt
                itens[m] = it
            for e in robo.ao_fechar(fecho, itens, precos_fecho):
                self._evento(e)
        self.salvar()
        self.escrever_resumo()
        print(f"[{data_hora(fecho)}] candle fechado, robôs decidiram. " +
              " | ".join(f"{r.p['nome']}: {brl(r.cart.patrimonio(self.precos) * self.usdt_brl)}" for r in self.robos.values()))
        return True

    def _evento(self, e):
        if e["tipo"] == "rejeitado":  # não repete o mesmo aviso de risco toda hora
            chave = (e.get("robo"), e["texto"])
            if agora_ms() - self._vistos.get(chave, 0) < 6 * 3_600_000:
                return
            self._vistos[chave] = agora_ms()
        self.eventos.append(e)
        with open(ARQ_EVENTOS, "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        if e["tipo"] in ("entrada", "saida", "stop", "alvo", "risco_dia"):
            nome = self.perfis.get(e.get("robo"), {}).get("nome", "")
            print(f"  [{nome}] {e['texto']}")

    def _ponto_curva(self, agora):
        for pid, robo in self.robos.items():
            pts = self.curvas.setdefault(pid, [])
            if not pts or agora - pts[-1][0] >= PONTO_CURVA_MS:
                pts.append([agora, round(robo.cart.patrimonio(self.precos), 4)])
                del pts[:-MAX_PONTOS]
        pts = self.curvas.setdefault("hodl", [])
        if not pts or agora - pts[-1][0] >= PONTO_CURVA_MS:
            pts.append([agora, round(self._hodl_valor(), 4)])
            del pts[:-MAX_PONTOS]

    def _hodl_valor(self):
        return sum(q * self.precos.get(m, 0) for m, q in self.hodl["qtd"].items())

    def salvar(self):
        salvar_json(ARQ_ROBOS, {pid: r.para_dict() for pid, r in self.robos.items()})
        salvar_json(ARQ_CURVAS, self.curvas)

    # ------------------------------------------------------------ saída para o escritório
    def montar_snapshot(self):
        if not hasattr(self, "robos"):
            self.snapshot = json.dumps({"status": self.status, "msg": self.msg}, ensure_ascii=False).encode("utf-8")
            return
        fx = self.usdt_brl
        moedas = []
        for m in self.moedas:
            s = self.series[m]
            vt = self.provisorio.get(m) or self.votos.get(m) or {}
            vals = valores(vt)
            moedas.append({
                "simbolo": m, "nome": nome_moeda(m), "preco": self.precos.get(m, s.c[-1]), "var24h": self.var24.get(m),
                "votos": {k: {"v": round(v[0], 3), "txt": v[1]} for k, v in vt.items()},
                "placar": {pid: round(placar_valores(vals, p["pesos"]), 3) for pid, p in self.perfis.items()} if vals else {},
                "faisca": [round(x, 6) for x in s.c[-48:]],
            })
        robos = []
        for pid, r in self.robos.items():
            eq = r.cart.patrimonio(self.precos)
            trades = r.cart.trades
            ganhos = sum(1 for t in trades if t["lucro"] > 0)
            robos.append({
                "id": pid, "nome": r.p["nome"], "estilo": r.p["estilo"], "descricao": r.p["descricao"],
                "otimizado": bool(r.p.get("otimizado")), "decide_a_cada": r.p.get("decide_a_cada"),
                "patrimonio_brl": eq * fx, "caixa_brl": r.cart.caixa * fx, "retorno_pct": (eq / r.cart.caixa_inicial - 1) * 100,
                "max_queda_pct": r.max_dd * 100, "parado_hoje": r.parado_hoje, "taxas_brl": r.cart.taxas_pagas * fx,
                "n_trades": len(trades), "acerto_pct": ganhos / len(trades) * 100 if trades else None,
                "posicoes": [{
                    "simbolo": p.simbolo, "nome": nome_moeda(p.simbolo), "qtd": p.qtd, "entrada": p.entrada,
                    "preco": self.precos.get(p.simbolo, p.entrada), "stop": p.stop, "protegida": p.protegida,
                    "valor_brl": p.qtd * self.precos.get(p.simbolo, p.entrada) * fx,
                    "lucro_pct": (p.qtd * self.precos.get(p.simbolo, p.entrada) * (1 - r.cart.taxa) / p.custo - 1) * 100,
                    "aberta_em": p.aberta_em,
                } for p in r.cart.posicoes.values()],
                "trades": [dict(t, nome=nome_moeda(t["simbolo"])) for t in trades[-25:]][::-1],
                "curva": [[t, round(v * fx, 2)] for t, v in self.curvas.get(pid, [])[-600:]],
            })
        hv = self._hodl_valor()
        btc = self.analises.get("BTCUSDT")
        macro = btc.macro.get(btc.s.t[-1], (0, "")) if btc else (0, "")
        fng_v = sentimento.valor_em(agora_ms())
        bt = ler_json(os.path.join(RELATORIOS, "backtest.json"), {}) or {}
        snap = {
            "status": self.status, "msg": self.msg, "agora": agora_ms(), "iniciado_em": self.iniciado_em,
            "usdt_brl": fx, "tempo_grafico": self.tg, "proximo_fechamento": self.ultima_vela + 2 * self.iv,
            "saldo_inicial_brl": self.cfg["saldo_inicial_brl"],
            "agentes": [{"id": a["id"], "nome": a["nome"]} for a in AGENTES],
            "moedas": moedas, "robos": robos,
            "macro": {"v": macro[0], "txt": macro[1]},
            "sentimento": {"valor": fng_v, "rotulo": sentimento.rotulo(fng_v)},
            "hodl": {"patrimonio_brl": hv * fx, "retorno_pct": (hv / self.hodl["capital"] - 1) * 100,
                     "curva": [[t, round(v * fx, 2)] for t, v in self.curvas.get("hodl", [])[-600:]]},
            "eventos": [dict(e, robo_nome=self.perfis.get(e.get("robo"), {}).get("nome")) for e in list(self.eventos)[-80:]][::-1],
            "backtest": {"periodo": bt.get("periodo"), "robos": {k: v.get("metricas") for k, v in bt.get("robos", {}).items()},
                         "hodl": (bt.get("hodl") or {}).get("metricas")} if bt else None,
        }
        self.snapshot = json.dumps(snap, ensure_ascii=False, default=float).encode("utf-8")

    def escrever_resumo(self):
        """Resumo em texto para pedir uma análise ao Claude Code ("analisa o bot")."""
        fx = self.usdt_brl
        linhas = [f"# Situação da Agência Cripto — {data_hora(agora_ms())}\n",
                  f"Dinheiro fictício. Início: {data_hora(self.hodl['inicio'])}. USDT/BRL {fx:.2f}.\n"]
        hv = self._hodl_valor()
        linhas.append(f"Comprar e segurar: {brl(hv * fx)} ({(hv / self.hodl['capital'] - 1) * 100:+.2f}%)\n")
        for r in self.robos.values():
            eq = r.cart.patrimonio(self.precos)
            linhas.append(f"## {r.p['nome']} — {brl(eq * fx)} ({(eq / r.cart.caixa_inicial - 1) * 100:+.2f}%), maior queda {r.max_dd * 100:.1f}%")
            for p in r.cart.posicoes.values():
                px = self.precos.get(p.simbolo, p.entrada)
                linhas.append(f"- aberta: {nome_moeda(p.simbolo)} entrada {p.entrada:.4f}, agora {px:.4f}, stop {p.stop:.4f}")
            for t in r.cart.trades[-10:]:
                linhas.append(f"- fechada: {nome_moeda(t['simbolo'])} {t['lucro_pct']:+.2f}% ({t['motivo']}) em {data_hora(t['fechada_em'])}")
            linhas.append("")
        linhas.append("## Votos atuais dos agentes")
        for m in self.moedas:
            vt = self.votos.get(m) or {}
            linhas.append(f"- {nome_moeda(m)}: " + "; ".join(f"{k} {v[0]:+.1f} ({v[1]})" for k, v in vt.items()))
        with open(ARQ_RESUMO, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas))

    # ------------------------------------------------------------ servidor
    def servir(self):
        app = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=ESCRITORIO, **k)

            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/api/estado"):
                    corpo = app.snapshot
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(corpo)))
                    self.end_headers()
                    self.wfile.write(corpo)
                    return
                super().do_GET()

        srv = ThreadingHTTPServer(("127.0.0.1", self.cfg["porta"]), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    def rodar(self, abrir=True):
        srv = self.servir()
        url = f"http://localhost:{self.cfg['porta']}/"
        print(f"Escritório em {url}  (Ctrl+C para sair)")
        self.montar_snapshot()
        self.preparar()
        self._recalcular_provisorio()
        self.montar_snapshot()
        self.escrever_resumo()
        if abrir:
            webbrowser.open(url)
        prox_preco = prox_analise = prox_var = 0.0
        falhas = 0
        try:
            while True:
                agora = time.time()
                try:
                    if agora >= prox_preco:
                        self.atualizar_precos()
                        prox_preco = agora + self.cfg["intervalo_precos_seg"]
                    if agora >= prox_var:
                        self.var24 = binance.variacao_24h(self.moedas)
                        self.usdt_brl = binance.usdt_brl()
                        prox_var = agora + 60
                    if agora >= prox_analise:
                        self.checar_vela_nova()
                        self._recalcular_provisorio()
                        prox_analise = agora + self.cfg["intervalo_analise_seg"]
                    if falhas:
                        print("Conexão com a Binance de volta.")
                    falhas = 0
                    self.status, self.msg = "ok", "Conectado à Binance"
                except binance.ErroBinance as e:
                    falhas += 1
                    self.status, self.msg = "erro", "Sem conexão com a Binance, tentando de novo..."
                    if falhas == 1:
                        print(f"Aviso: {e}")
                    prox_preco = agora + min(60, 5 * falhas)
                except Exception:
                    traceback.print_exc()
                    self.status, self.msg = "erro", "Erro inesperado no robô (veja o terminal)"
                self.montar_snapshot()
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nSalvando e saindo...")
        finally:
            self.salvar()
            srv.shutdown()


def main():
    cfg = carregar_config()
    ap = argparse.ArgumentParser(description="Agência Cripto ao vivo (dinheiro fictício)")
    ap.add_argument("--zerar", action="store_true", help="recomeça as carteiras do zero")
    ap.add_argument("--sem-navegador", action="store_true", help="não abre o navegador")
    args = ap.parse_args()
    AoVivo(cfg, zerar=args.zerar).rodar(abrir=not args.sem_navegador)


if __name__ == "__main__":
    main()
