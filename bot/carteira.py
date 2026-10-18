"""Carteira de papel: caixa em USDT fictício, posições compradas (só spot, sem alavancagem),
taxas e derrapagem simuladas como numa corretora de verdade."""


class Posicao:
    __slots__ = ("simbolo", "qtd", "entrada", "custo", "stop", "alvo", "maxima", "aberta_em", "atr_entrada", "protegida", "placar")

    def __init__(self, simbolo, qtd, entrada, custo, stop, alvo, aberta_em, atr_entrada, placar=0.0):
        self.simbolo, self.qtd, self.entrada, self.custo = simbolo, qtd, entrada, custo
        self.stop, self.alvo, self.maxima = stop, alvo, entrada
        self.aberta_em, self.atr_entrada = aberta_em, atr_entrada
        self.protegida = False  # stop já subiu para o empate
        self.placar = placar

    def para_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def de_dict(cls, d):
        p = cls(d["simbolo"], d["qtd"], d["entrada"], d["custo"], d["stop"], d["alvo"], d["aberta_em"], d["atr_entrada"], d.get("placar", 0.0))
        p.maxima, p.protegida = d.get("maxima", p.entrada), d.get("protegida", False)
        return p


class Carteira:
    def __init__(self, caixa, taxa=0.001, derrapagem=0.0005):
        self.caixa_inicial = caixa
        self.caixa = caixa
        self.taxa, self.derrapagem = taxa, derrapagem
        self.posicoes = {}
        self.trades = []
        self.taxas_pagas = 0.0

    def exposicao(self, precos):
        return sum(p.qtd * precos.get(s, p.entrada) for s, p in self.posicoes.items())

    def patrimonio(self, precos):
        return self.caixa + self.exposicao(precos)

    def comprar(self, simbolo, valor, preco, t, stop, alvo, atr_, placar=0.0):
        px = preco * (1 + self.derrapagem)
        qtd = valor / px
        taxa = valor * self.taxa
        self.caixa -= valor + taxa
        self.taxas_pagas += taxa
        pos = Posicao(simbolo, qtd, px, valor + taxa, stop, alvo, t, atr_, placar)
        self.posicoes[simbolo] = pos
        return pos

    def vender(self, simbolo, preco, t, motivo):
        pos = self.posicoes.pop(simbolo)
        px = preco * (1 - self.derrapagem)
        receita = pos.qtd * px
        taxa = receita * self.taxa
        self.caixa += receita - taxa
        self.taxas_pagas += taxa
        lucro = receita - taxa - pos.custo
        trade = {
            "simbolo": simbolo, "qtd": pos.qtd, "entrada": pos.entrada, "saida": px,
            "lucro": lucro, "lucro_pct": lucro / pos.custo * 100, "motivo": motivo,
            "aberta_em": pos.aberta_em, "fechada_em": t, "placar": pos.placar,
        }
        self.trades.append(trade)
        return trade

    def para_dict(self):
        return {
            "caixa_inicial": self.caixa_inicial, "caixa": self.caixa, "taxa": self.taxa, "derrapagem": self.derrapagem,
            "taxas_pagas": self.taxas_pagas, "posicoes": [p.para_dict() for p in self.posicoes.values()],
            "trades": self.trades[-500:],
        }

    @classmethod
    def de_dict(cls, d):
        c = cls(d["caixa_inicial"], d.get("taxa", 0.001), d.get("derrapagem", 0.0005))
        c.caixa, c.taxas_pagas = d["caixa"], d.get("taxas_pagas", 0.0)
        c.posicoes = {p["simbolo"]: Posicao.de_dict(p) for p in d.get("posicoes", [])}
        c.trades = d.get("trades", [])
        return c
