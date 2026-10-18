"""O robô: junta o placar dos agentes, passa pelo Gerente de Risco e pela Compliance,
e executa na carteira fictícia. O mesmo código roda no backtest e ao vivo."""
from .binance import INTERVALO_MS
from .carteira import Carteira
from .util import dia_utc, nome_moeda, num

MINIMO_ORDEM = 10.0  # a Binance não aceita ordens abaixo de ~10 USDT


def placar_valores(votos, pesos):
    tot = 0.0
    s = 0.0
    for k, w in pesos.items():
        v = votos.get(k)
        if v is None:
            continue
        tot += w
        s += w * v
    return s / tot if tot else 0.0


def valores(votos):
    """Aceita {agente: valor} ou {agente: (valor, motivo)}."""
    return {k: (v[0] if isinstance(v, tuple) else v) for k, v in votos.items()}


class Robo:
    def __init__(self, perfil, carteira, intervalo_ms):
        self.p = perfil
        self.cart = carteira
        self.iv = intervalo_ms
        self.decide_ms = INTERVALO_MS.get(perfil.get("decide_a_cada", ""), intervalo_ms)
        self.dia = None
        self.inicio_dia = carteira.caixa
        self.parado_hoje = False
        self.quarentena = {}
        self.pico = carteira.caixa_inicial
        self.max_dd = 0.0
        self.ultima_decisao = 0

    def unidade(self, it):
        return it["vol"] if self.p["base_stop"] == "vol" else it["atr"]

    # ------------------------------------------------------------ proteção
    def checar_protecoes(self, simbolo, t, abertura, maxima, minima, eventos):
        """Stop e alvo dentro do candle. Se os dois cabem no mesmo candle, assume o stop (conservador)."""
        pos = self.cart.posicoes.get(simbolo)
        if pos is None:
            return
        if minima <= pos.stop:
            px = min(abertura, pos.stop)
            motivo = "stop móvel" if pos.protegida else "stop de perda"
            tr = self.cart.vender(simbolo, px, t, motivo)
            if tr["lucro"] < 0:
                self.quarentena[simbolo] = t + self.p["espera_apos_stop"] * self.iv
            eventos.append(self._ev(t, "stop", simbolo, f"{motivo.capitalize()} em {nome_moeda(simbolo)} a {num(px, 4)}: {tr['lucro_pct']:+.2f}%", tr))
        elif pos.alvo and maxima >= pos.alvo:
            px = max(abertura, pos.alvo)
            tr = self.cart.vender(simbolo, px, t, "alvo atingido")
            eventos.append(self._ev(t, "alvo", simbolo, f"Alvo atingido em {nome_moeda(simbolo)}: {tr['lucro_pct']:+.2f}%", tr))

    # ------------------------------------------------------------ decisão
    def ao_fechar(self, t, itens, precos):
        """itens = {simbolo: {score, votos, atr, vol, c, h, meio, macro}}; t = horário do fechamento."""
        p, cart, ev = self.p, self.cart, []
        eq = cart.patrimonio(precos)
        dia = dia_utc(t)
        if dia != self.dia:
            self.dia, self.inicio_dia, self.parado_hoje = dia, eq, False
        # decide no ritmo do perfil; se o robô ficou desligado e perdeu a hora, decide assim que voltar
        decide = t % self.decide_ms == 0 or t - self.ultima_decisao >= self.decide_ms
        if decide:
            self.ultima_decisao = t

        # 1) stops sobem junto com o lucro
        for sim, pos in list(cart.posicoes.items()):
            it = itens.get(sim)
            if not it:
                continue
            pos.maxima = max(pos.maxima, it["h"])
            u = self.unidade(it)
            if p["empate_k"] and not pos.protegida and it["c"] >= pos.entrada + p["empate_k"] * pos.atr_entrada:
                empate = pos.entrada * (1 + 2 * cart.taxa + cart.derrapagem)
                if empate > pos.stop:
                    pos.stop, pos.protegida = empate, True
                    ev.append(self._ev(t, "protecao", sim, f"Stop de {nome_moeda(sim)} subiu para o empate: essa operação não perde mais"))
            if p["trail_k"] and (pos.protegida or not p["empate_k"]):
                movel = pos.maxima - p["trail_k"] * u
                if movel > pos.stop:
                    pos.stop, pos.protegida = movel, pos.protegida or movel > pos.entrada

        # 2) saídas: volta à média e prazo (a cada candle) e sinal contrário (no ritmo do perfil)
        for sim in list(cart.posicoes):
            it = itens.get(sim)
            if not it:
                continue
            pos = cart.posicoes[sim]
            motivo = None
            if p["saida_na_media"] and it["c"] >= it["meio"]:
                motivo, txt = "voltou à média", f"Vendi {nome_moeda(sim)}: preço voltou à média"
            elif p["max_velas"] and (t - pos.aberta_em) >= p["max_velas"] * self.iv:
                motivo, txt = "prazo esgotado", f"Vendi {nome_moeda(sim)}: prazo da operação acabou"
            elif decide and it["score"] <= p["limiar_saida"]:
                motivo, txt = "sinal virou", f"Vendi {nome_moeda(sim)}: agentes viraram contra (placar {it['score']:+.2f})"
            if motivo:
                tr = cart.vender(sim, it["c"], t, motivo)
                ev.append(self._ev(t, "saida", sim, f"{txt}, {tr['lucro_pct']:+.2f}%", tr))

        # 3) Gerente de Risco: limite de perda no dia
        eq = cart.patrimonio(precos)
        if not self.parado_hoje and eq < self.inicio_dia * (1 - p["perda_diaria_max"]):
            self.parado_hoje = True
            ev.append(self._ev(t, "risco_dia", None, f"Perda do dia passou de {p['perda_diaria_max'] * 100:.0f}%: sem compras novas até amanhã"))

        # 4) entradas, da mais forte para a mais fraca
        if decide and not self.parado_hoje:
            candidatos = sorted(((it["score"], s) for s, it in itens.items()
                                 if s not in cart.posicoes and it["score"] >= p["limiar_entrada"]), reverse=True)
            for score, sim in candidatos:
                it = itens[sim]
                ok, res = self.avaliar_risco(sim, it, t, precos)
                if not ok:
                    if res:
                        ev.append(self._ev(t, "rejeitado", sim, res, {"placar": score}))
                    continue
                u = self.unidade(it)
                stop = it["c"] - p["stop_k"] * u
                alvo = it["c"] + p["alvo_k"] * u if p["alvo_k"] else 0.0
                pos = cart.comprar(sim, res, it["c"], t, stop, alvo, u, score)
                ev.append(self._ev(t, "entrada", sim,
                                   f"Comprei {nome_moeda(sim)}: {num(res)} USDT a {num(pos.entrada, 4)} (placar {score:+.2f}, stop {num(stop, 4)})",
                                   {"valor": res, "placar": score, "stop": stop}))

        self.registrar(cart.patrimonio(precos))
        return ev

    def avaliar_risco(self, sim, it, t, precos):
        """Gerente de Risco + Compliance. Devolve (True, valor_em_usdt) ou (False, motivo).
        Motivo vazio = não vale a pena avisar (só não atende aos requisitos do perfil)."""
        p, cart = self.p, self.cart
        vt = it.get("votos", {})
        for agente, minimo in p.get("exige", {}).items():
            if vt.get(agente, 0.0) < minimo:
                return False, ""
        if t < self.quarentena.get(sim, 0):
            return False, f"{nome_moeda(sim)} em quarentena depois de um stop"
        if len(cart.posicoes) >= p["max_posicoes"]:
            return False, f"Já são {len(cart.posicoes)} posições abertas, o limite deste perfil"
        u = self.unidade(it)
        if u <= 0:
            return False, f"{nome_moeda(sim)}: volatilidade zerada, dado suspeito"
        eq = cart.patrimonio(precos)
        valor = p["risco_por_trade"] * eq / (p["stop_k"] * u) * it["c"]
        if it["macro"] < 0:
            valor *= p.get("fator_macro_ruim", 0.5)
        valor = min(valor, p["max_por_moeda"] * eq,
                    p["max_exposicao"] * eq - cart.exposicao(precos),
                    cart.caixa / (1 + cart.taxa) * 0.999)
        if valor < MINIMO_ORDEM:
            return False, f"{nome_moeda(sim)}: sem espaço na carteira (limite de exposição ou caixa)"
        return True, valor

    # ------------------------------------------------------------ apoio
    def registrar(self, eq):
        if eq > self.pico:
            self.pico = eq
        dd = (self.pico - eq) / self.pico if self.pico else 0.0
        if dd > self.max_dd:
            self.max_dd = dd

    def _ev(self, t, tipo, simbolo, texto, extra=None):
        e = {"t": t, "robo": self.p["id"], "tipo": tipo, "moeda": simbolo, "texto": texto}
        if extra:
            e["extra"] = extra
        return e

    def para_dict(self):
        return {"carteira": self.cart.para_dict(), "dia": self.dia, "inicio_dia": self.inicio_dia,
                "parado_hoje": self.parado_hoje, "quarentena": self.quarentena, "pico": self.pico, "max_dd": self.max_dd,
                "ultima_decisao": self.ultima_decisao}

    @classmethod
    def de_dict(cls, perfil, d, intervalo_ms):
        r = cls(perfil, Carteira.de_dict(d["carteira"]), intervalo_ms)
        r.dia, r.inicio_dia, r.parado_hoje = d.get("dia"), d.get("inicio_dia", r.cart.caixa), d.get("parado_hoje", False)
        r.quarentena = {k: int(v) for k, v in d.get("quarentena", {}).items()}
        r.pico, r.max_dd = d.get("pico", r.cart.caixa_inicial), d.get("max_dd", 0.0)
        r.ultima_decisao = d.get("ultima_decisao", 0)
        return r
