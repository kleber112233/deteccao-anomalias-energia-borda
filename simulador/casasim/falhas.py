"""Injetor de falhas com gabarito. O gabarito só vai para arquivo: nunca é publicado no MQTT."""
from __future__ import annotations
import datetime as dt
import json
from dataclasses import dataclass, field, asdict
import numpy as np
from .aparelhos import Ctx, gerar
from .comportamento import Uso
from .dados import Cenario
from .util import N, rng_de

TIPOS = ["magnitude", "fora_de_horario", "duracao_excessiva", "pico", "queda", "consumo_nao_explicado", "falta_energia"]
DESCRICAO = {
    "magnitude": "Aparelho consumindo mais que o normal enquanto funciona (desgaste, vedação ruim, sujeira).",
    "fora_de_horario": "Aparelho ligado num horário em que nunca é usado (madrugada).",
    "duracao_excessiva": "Aparelho esquecido ligado ou que não desliga (ferro, ar-condicionado, compressor travado).",
    "pico": "Picos rápidos de 1 a 3 s (mau contato, partida difícil de motor).",
    "queda": "Consumo cai para perto de zero quando deveria existir (compressor parado, resistência queimada).",
    "consumo_nao_explicado": "O medidor geral registra mais do que a soma dos aparelhos (fuga, ligação indevida).",
    "falta_energia": "Falta de energia da rede. É evento da rede: não deve virar alerta de aparelho.",
}
# duração típica (min) do uso indevido, por tipo de aparelho
USO_FORA = {"ferro_passar": 40, "air_fryer": 25, "tv": 90, "chuveiro_eletrico": 12, "ar_condicionado": 120, "forno_eletrico": 45,
            "bomba_dagua": 30, "micro_ondas": 6, "secador_cabelo": 10, "maquina_lavar": 60, "ventilador": 120, "videogame": 120}
USO_LONGO = {"ferro_passar": 180, "ar_condicionado": 420, "forno_eletrico": 150, "chuveiro_eletrico": 35, "geladeira": 360,
             "freezer": 360, "bomba_dagua": 120, "tv": 420, "air_fryer": 90, "bomba_piscina": 600}
PARAMS_USO = {"ar_condicionado": {"setpoint": 20}, "chuveiro_eletrico": {"nivel": 1.0}, "ventilador": {"velocidade": 2},
              "micro_ondas": {"nivel": 1.0}, "videogame": {"modo": "jogo"}}


@dataclass
class Falha:
    id: str
    tipo: str
    alvo: str                  # id da instância, 'geral' ou 'rede'
    inicio: dt.datetime        # hora local, sem fuso
    duracao_s: int
    params: dict = field(default_factory=dict)
    origem: str = "plano"

    @property
    def fim(self) -> dt.datetime:
        return self.inicio + dt.timedelta(seconds=self.duracao_s)


class InjetorFalhas:
    def __init__(self, cenario: Cenario, semente: int = 0):
        self.c, self.semente = cenario, semente
        self.falhas: list[Falha] = []
        self._n = 0

    # ------------------------------------------------------------------ criação
    def alvos(self, tipo: str) -> list[str]:
        ins = self.c.instancias.values()
        if tipo == "consumo_nao_explicado":
            return ["geral"]
        if tipo == "falta_energia":
            return ["rede"]
        if tipo == "fora_de_horario":
            return [i.id for i in ins if i.tipo in USO_FORA]
        if tipo == "duracao_excessiva":
            return [i.id for i in ins if i.tipo in USO_LONGO]
        if tipo == "pico":
            return [i.id for i in ins if i.classe in ("refrigeracao", "ar", "lavadora", "motor_demanda", "motor_programado", "termostato", "chuveiro")]
        if tipo == "queda":
            return [i.id for i in ins if i.classe in ("refrigeracao", "ar", "chuveiro", "motor_programado")]
        return [i.id for i in ins if i.tipo not in ("lampada", "roteador", "motor_portao", "liquidificador")]

    def nova(self, tipo: str, alvo: str, inicio: dt.datetime, duracao_s: int | None = None, params: dict | None = None,
             origem: str = "plano", rng: np.random.Generator | None = None) -> Falha:
        if tipo not in TIPOS:
            raise ValueError(f"tipo de falha desconhecido: {tipo}")
        r = rng or rng_de(self.semente, "falha", self._n)
        inst = self.c.instancias.get(alvo)
        p = dict(params or {})
        if tipo == "magnitude":
            p.setdefault("fator", round(float(r.uniform(1.4, 2.2)), 2)); d = int(r.uniform(6, 24) * 3600)
        elif tipo == "fora_de_horario":
            d = USO_FORA.get(inst.tipo, 30) * 60 if inst else 1800
        elif tipo == "duracao_excessiva":
            d = USO_LONGO.get(inst.tipo, 120) * 60 if inst else 7200
        elif tipo == "pico":
            p.setdefault("n_picos", int(r.integers(3, 9))); p.setdefault("fator", round(float(r.uniform(3, 6)), 1))
            p.setdefault("largura_s", int(r.integers(1, 4))); d = 3600
        elif tipo == "queda":
            p.setdefault("fator", 0.0 if inst and inst.classe == "refrigeracao" else 0.4); d = int(r.uniform(2, 6) * 3600)
        elif tipo == "consumo_nao_explicado":
            p.setdefault("potencia_w", int(r.uniform(150, 900))); d = int(r.uniform(2, 12) * 3600)
        else:
            d = int(r.uniform(5, 90) * 60)
        self._n += 1
        f = Falha(f"F{self._n:04d}", tipo, alvo, inicio.replace(microsecond=0), int(duracao_s or d), p, origem)
        self.falhas.append(f)
        return f

    def plano_aleatorio(self, inicio: dt.date, dias: int, por_semana: float) -> list[Falha]:
        """Sorteia falhas ao longo do período (reprodutível pela semente)."""
        r = rng_de(self.semente, "plano")
        for _ in range(int(round(dias / 7 * por_semana))):
            tipo = TIPOS[int(r.integers(0, len(TIPOS)))]
            alvos = self.alvos(tipo)
            if not alvos:
                continue
            alvo = alvos[int(r.integers(0, len(alvos)))]
            dia = inicio + dt.timedelta(days=int(r.integers(0, dias)))
            hora = float(r.uniform(1, 4.5)) if tipo == "fora_de_horario" else float(r.uniform(0, 20))
            self.nova(tipo, alvo, dt.datetime.combine(dia, dt.time()) + dt.timedelta(hours=hora), rng=r)
        return self.falhas

    def plano_balanceado(self, inicio: dt.date, dias: int, por_semana: float, prob_medido: float = 0.6,
                         tipos: list[str] | None = None, chave: str = "balanceado") -> list[Falha]:
        """Plano com os tipos em proporções iguais (embaralhados) e preferência por aparelhos que têm medidor
        próprio (com probabilidade `prob_medido`), para haver eventos suficientes nos canais diretos."""
        r = rng_de(self.semente, "plano", chave, inicio.toordinal())
        tipos = list(tipos or TIPOS)
        n = int(round(dias / 7 * por_semana))
        sequencia = [tipos[i % len(tipos)] for i in range(n)]
        r.shuffle(sequencia)
        dias_sorteados = np.sort(r.choice(dias, size=n, replace=n > dias))
        criadas = []
        for tipo, d in zip(sequencia, dias_sorteados):
            alvos = self.alvos(tipo)
            if not alvos:
                continue
            medidos = [a for a in alvos if a in self.c.instancias and self.c.instancias[a].canal]
            pool = medidos if medidos and r.random() < prob_medido else alvos
            alvo = pool[int(r.integers(0, len(pool)))]
            dia = inicio + dt.timedelta(days=int(d))
            hora = float(r.uniform(1, 4.5)) if tipo == "fora_de_horario" else float(r.uniform(0, 20))
            criadas.append(self.nova(tipo, alvo, dt.datetime.combine(dia, dt.time()) + dt.timedelta(hours=hora), rng=r))
        return criadas

    # ------------------------------------------------------------------ aplicação
    def aplicar(self, data: dt.date, pot_base: dict[str, np.ndarray], usos: list[Uso], clima, atividade) -> tuple[dict, np.ndarray, list, list[dict]]:
        """Aplica as falhas que tocam o dia. Devolve (potências, extra no medidor geral, faltas, linhas do gabarito)."""
        t00 = dt.datetime.combine(data, dt.time())
        pot = dict(pot_base)
        extra = np.zeros(N, dtype=np.float32)
        faltas, linhas = [], []
        for f in self.falhas:
            a = int((f.inicio - t00).total_seconds())
            b = a + f.duracao_s
            if b <= 0 or a >= N:
                continue
            a0, b0 = max(0, a), min(N, b)
            inst = self.c.instancias.get(f.alvo)
            ef = None
            if f.tipo == "falta_energia":
                faltas.append((a0, b0)); ef = (a0, b0)
            elif f.tipo == "consumo_nao_explicado":
                extra[a0:b0] += f.params["potencia_w"]; ef = (a0, b0)
            elif inst is not None:
                base = pot[inst.id]
                novo = base.copy()
                r = rng_de(self.semente, "aplicar", f.id, data.toordinal())
                if f.tipo == "magnitude":
                    lig = novo[a0:b0] > max(2.0, 2 * float(inst.spec.get("standby_w") or 0))
                    novo[a0:b0] = np.where(lig, novo[a0:b0] * f.params["fator"], novo[a0:b0])
                elif f.tipo == "queda":
                    novo[a0:b0] *= f.params["fator"]
                elif f.tipo == "pico":
                    for t in np.sort(r.integers(a0, max(a0 + 1, b0 - 3), f.params["n_picos"])):
                        novo[t:t + f.params["largura_s"]] += inst.potencia_w * f.params["fator"]
                else:                                             # fora_de_horario / duracao_excessiva
                    ini = a0
                    if f.tipo == "duracao_excessiva" and f.origem == "plano":
                        prox = [u for u in usos if u.inst == inst.id and u.inicio + u.duracao >= a0 and u.inicio + u.duracao < N - 600]
                        if prox:
                            ini = prox[0].inicio + prox[0].duracao           # prolonga o primeiro uso normal depois do horário sorteado
                    dur = min(f.duracao_s - max(0, -a), N - ini)
                    if inst.classe == "refrigeracao":
                        novo[ini:ini + dur] = np.maximum(novo[ini:ini + dur], inst.potencia_w)
                    else:
                        u = Uso(inst.id, ini, dur, dict(PARAMS_USO.get(inst.tipo, {}), **f.params), f.id)
                        ctx = Ctx(clima, atividade, r, data.toordinal())
                        perfil = gerar(inst, [u], ctx, {})
                        np.maximum(novo, perfil, out=novo)
                dif = np.flatnonzero(np.abs(novo - base) > max(1.0, 0.02 * inst.potencia_w))
                if len(dif):
                    ef = (int(dif[0]), int(dif[-1]) + 1)
                pot[inst.id] = novo
            ts = lambda s: (t00 + dt.timedelta(seconds=int(s))).isoformat(sep=" ")
            linhas.append(dict(falha_id=f.id, tipo=f.tipo, alvo=f.alvo, comodo=inst.comodo if inst else "",
                               canal_direto=(inst.canal or "") if inst else (self.c.canal_geral.chave if f.alvo == "geral" and self.c.canal_geral else ""),
                               inicio=f.inicio.isoformat(sep=" "), fim=f.fim.isoformat(sep=" "),
                               efeito_inicio=ts(ef[0]) if ef else "", efeito_fim=ts(ef[1]) if ef else "", efetiva=ef is not None,
                               alerta_de_aparelho=f.tipo != "falta_energia", origem=f.origem,
                               params=json.dumps(f.params, ensure_ascii=False), dia=data.isoformat(),
                               _ef=ef))
        return pot, extra, faltas, linhas

    def como_dicts(self) -> list[dict]:
        return [dict(asdict(f), inicio=f.inicio.isoformat(sep=" ")) for f in self.falhas]
