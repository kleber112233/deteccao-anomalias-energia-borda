"""Moradores -> eventos de uso dos aparelhos (um dia por vez)."""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, field
import numpy as np
from .clima import ClimaDia
from .dados import Cenario, Instancia
from .util import N, hhmm, rng_de, slug


@dataclass
class Uso:
    inst: str
    inicio: int                 # segundo do dia em que liga
    duracao: int                # segundos (pode passar da meia-noite)
    params: dict = field(default_factory=dict)
    origem: str = "rotina"      # 'rotina' ou o id de uma falha injetada


@dataclass
class PessoaDia:
    cfg: dict
    acorda: int
    sai: int | None
    volta: int | None
    dorme: int
    home_office: bool

    @property
    def em_casa(self) -> list[tuple[int, int]]:
        return [(self.acorda, self.dorme)] if self.sai is None else [(self.acorda, self.sai), (self.volta, self.dorme)]


def tipo_comodo(nome: str) -> str:
    s = slug(nome)
    for chave, t in (("quarto", "quarto"), ("suite", "quarto"), ("sala", "sala"), ("estar", "sala"), ("gourmet", "cozinha"),
                     ("cozinha", "cozinha"), ("banheiro", "banheiro"), ("servico", "servico"), ("lavanderia", "servico"),
                     ("externa", "externa"), ("garagem", "externa"), ("escritorio", "escritorio")):
        if chave in s:
            return t
    return "sala"


def _trechos(mask: np.ndarray, minimo: int = 1) -> list[tuple[int, int]]:
    """Máscara por minuto -> lista de (início, fim) em minutos."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return [(int(a), int(b)) for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)) if b - a >= minimo]


class Comportamento:
    def __init__(self, cenario: Cenario, semente: int = 0):
        self.c, self.semente = cenario, semente
        self.pessoas = cenario.personas["moradores"]
        self.h = cenario.personas["habitos"]

    # ------------------------------------------------------------------
    def _pessoa(self, p: dict, data: dt.date, r: np.random.Generator) -> PessoaDia:
        util = data.weekday() < 5
        rot = p["util"] if util else p["fds"]
        sd = p.get("variacao_min", 15) * 60
        j = lambda x: int(x + r.normal(0, sd))
        acorda, dorme = j(hhmm(rot["acorda"])), j(hhmm(rot["dorme"], True))
        sai, volta = hhmm(rot.get("sai")), hhmm(rot.get("volta"))
        ho = util and data.weekday() in p.get("home_office", [])
        if sai is not None:
            if ho or (not util and r.random() > rot.get("prob_saida", 0.5)):
                sai = volta = None
            else:
                sai = max(j(sai), acorda + 900)
                volta = max(j(volta), sai + 1800)
        dorme = min(max(dorme, (volta or acorda) + 3600), N + 3 * 3600)
        return PessoaDia(p, acorda, sai, volta, dorme, ho)

    def dia(self, data: dt.date, clima: ClimaDia) -> tuple[list[Uso], dict]:
        r = rng_de(self.semente, "comportamento", data.toordinal())
        h, util = self.h, data.weekday() < 5
        gente = [self._pessoa(p, data, r) for p in self.pessoas]
        M = 1800                                              # minutos representados (30 h) para cobrir a madrugada
        ativ = np.zeros(M, dtype=np.int16)                    # nº de pessoas acordadas em casa
        for g in gente:
            for a, b in g.em_casa:
                ativ[max(0, a // 60):min(M, b // 60)] += 1
        escuro = np.concatenate([clima.escuro(), np.ones(M - 1440, bool)])
        mins = np.arange(M)
        usos: list[Uso] = []
        por_tipo: dict[str, list[Instancia]] = {}
        for i in self.c.instancias.values():
            por_tipo.setdefault(i.tipo, []).append(i)
        do_comodo = lambda tipo, comodo: [i for i in por_tipo.get(tipo, []) if i.comodo == comodo]
        U = lambda inst, ini, dur, **kw: usos.append(Uso(inst.id, int(max(0, min(ini, N - 1))), int(max(1, dur)), kw))
        em_casa_no = lambda g, s: any(a <= s < b for a, b in g.em_casa)
        primeiro = min(g.acorda for g in gente)
        ultimo = max(g.dorme for g in gente)
        t_ext = lambda s: float(clima.t_ext[min(1439, max(0, int(s) // 60))])
        t_int22 = float(clima.t_int[22 * 60])
        clim = h["clima"]

        # ---------------- banhos (chuveiro, bomba, secador, luz do banheiro)
        chuveiros = por_tipo.get("chuveiro_eletrico", [])
        banhos: list[tuple[Instancia, int, int]] = []
        ocupado: dict[str, int] = {}
        for g in gente:
            if not chuveiros:
                break
            ch = next((c for c in chuveiros if c.comodo == g.cfg.get("chuveiro")), chuveiros[0])
            # Horário do banho (ASSUMIDO, ajustado à forma da curva B1 da CPFL Paulista e ao Boa Energia):
            # noite ~ Normal(19h45, 75 min) depois de chegar em casa; manhã logo após acordar; com 15% de chance
            # a pessoa troca de período naquele dia.
            per0 = g.cfg.get("banho", {}).get("periodo", "noite")
            if r.random() < 0.15:
                per0 = {"noite": "manha", "manha": "noite", "tarde": "noite"}[per0]
            periodos = [per0]
            if clima.tmax > 30 and r.random() < h["banho"].get("segundo_banho_prob", 0):
                periodos.append("manha" if periodos[0] != "manha" else "noite")
            for per in periodos:
                if per == "manha":
                    ini = g.acorda + int(r.uniform(5, 25) * 60)
                elif per == "tarde":
                    ini = int(r.normal(16.5 * 3600, 3600))
                else:
                    cedo = (g.volta if g.volta is not None else 0) + int(r.uniform(10, 30) * 60)
                    ini = max(cedo, int(r.normal(19.75 * 3600, 75 * 60)))
                    ini = min(ini, g.dorme - 1500)
                if g.sai is not None and g.sai <= ini < g.volta:      # não toma banho fora de casa
                    ini = g.volta + int(r.uniform(10, 30) * 60)
                ant = ocupado.get(ch.id)
                if ant is not None and ant - 1500 < ini < ant + 120:      # chuveiro ocupado: espera a vez
                    ini = ant + 120
                dur = int(max(180, r.normal(g.cfg.get("banho", {}).get("duracao_min", 9), 1.5) * 60))
                if not (0 <= ini < N - dur):
                    continue
                hb = h["banho"]
                frac = np.clip((hb["temp_potencia_min_c"] - t_ext(ini)) / (hb["temp_potencia_min_c"] - hb["temp_potencia_max_c"]), 0, 1)
                mo = ch.modelo
                nivel = mo.get("minimo", 0.3) + (1 - mo.get("minimo", 0.3)) * float(frac)
                if mo.get("niveis"):
                    nivel = next((n for n in mo["niveis"] if n >= nivel - 0.05), 1.0)
                U(ch, ini, dur, nivel=round(nivel, 2), pessoa=g.cfg["id"])
                ocupado[ch.id] = ini + dur
                banhos.append((ch, ini, dur))
                sec = por_tipo.get("secador_cabelo", [])
                if sec and r.random() < g.cfg.get("usa_secador", 0):
                    U(sec[0], ini + dur + 240, r.uniform(4, 9) * 60, nivel=1.0 if r.random() < 0.7 else 0.5)
        for b in por_tipo.get("bomba_dagua", []):
            for _, ini, dur in banhos:
                U(b, ini, dur)
            casa = np.flatnonzero(ativ[:1440] > 0)
            for _ in range(5 * len(gente) if len(casa) else 0):
                U(b, int(r.choice(casa)) * 60 + int(r.integers(0, 60)), r.uniform(15, 60))

        # ---------------- cozinha
        cz = h["cozinha"]
        for caf in por_tipo.get("cafeteira", []):
            if caf.modelo.get("subtipo") == "capsula":
                n = int(cz.get("cafes_capsula_dia", 2))
                for k in range(n):
                    base = primeiro + 600 if k < (n + 1) // 2 else 15 * 3600
                    U(caf, base + int(r.uniform(0, 5400)), caf.modelo["preparo_s"])
            else:
                U(caf, primeiro + int(r.uniform(5, 12) * 60), caf.modelo["preparo_s"] + caf.modelo["manter_min"] * 60)
        for mo in por_tipo.get("micro_ondas", []):
            if r.random() < 0.7:
                U(mo, primeiro + int(r.uniform(12, 25) * 60), r.uniform(60, 120), nivel=1.0)
            if ativ[12 * 60 + 15] > 0:
                U(mo, 12 * 3600 + int(r.uniform(0, 2700)), r.uniform(180, 300), nivel=1.0)
            if r.random() < 0.85 and ativ[19 * 60 + 30] > 0:
                U(mo, 19 * 3600 + int(r.uniform(0, 4500)), r.uniform(180, 360), nivel=1.0)
            if r.random() < 0.35 and ativ[16 * 60] > 0:
                U(mo, 15 * 3600 + 1800 + int(r.uniform(0, 5400)), r.uniform(60, 120), nivel=1.0)
            if r.random() < 0.15 and ativ[17 * 60 + 45] > 0:
                U(mo, 17 * 3600 + 2700, 480, nivel=0.4)
        for af in por_tipo.get("air_fryer", []):
            if r.random() < cz.get("air_fryer_jantar", 0.3) and ativ[19 * 60] > 0:
                U(af, 18 * 3600 + 2700 + int(r.uniform(0, 3600)), r.uniform(15, 28) * 60)
            if not util and r.random() < 0.35 and ativ[11 * 60 + 45] > 0:
                U(af, 11 * 3600 + 2700 + int(r.uniform(0, 1200)), r.uniform(20, 30) * 60)
        for fo in por_tipo.get("forno_eletrico", []):
            if r.random() < cz.get("forno_semana", 0) / 7 and ativ[19 * 60] > 0:
                U(fo, 18 * 3600 + 1800 + int(r.uniform(0, 3600)), r.uniform(40, 60) * 60)
        for lq in por_tipo.get("liquidificador", []):
            if r.random() < cz.get("liquidificador_manha", 0.3):
                U(lq, primeiro + int(r.uniform(10, 20) * 60), r.uniform(45, 110))
            if not util and r.random() < 0.2:
                U(lq, 11 * 3600 + int(r.uniform(0, 3600)), r.uniform(45, 110))
        for ll in por_tipo.get("lava_loucas", []):
            if r.random() < cz.get("lava_loucas", 0):
                U(ll, 20 * 3600 + 2700 + int(r.normal(0, 1200)), ll.modelo["duracao_min"] * 60)

        # ---------------- lavanderia
        lav, fer = h["lavagem"], h["ferro"]
        t_lav = None
        if data.weekday() in lav["dias"]:
            for ml in por_tipo.get("maquina_lavar", []):
                t_lav = hhmm(lav["hora_util"] if util else lav["hora_fds"]) + int(r.normal(0, 1200))
                secar = bool(ml.modelo.get("lava_e_seca")) and r.random() < lav.get("prob_secagem", 0)
                U(ml, t_lav, ml.modelo["duracao_min"] * 60, secar=secar)
            for sc in por_tipo.get("secadora", []):
                if t_lav is not None and r.random() < 0.5:
                    U(sc, t_lav + 5400, 90 * 60)
        t_fer = None
        if data.weekday() in fer["dias"]:
            for fe in por_tipo.get("ferro_passar", []):
                t_fer = hhmm(fer["hora"]) + int(r.normal(0, 1200))
                U(fe, t_fer, max(600, r.normal(fer["duracao_min"], fer["duracao_min"] / 5) * 60))

        # ---------------- TV, videogame, computadores
        tvh = h["tv"]
        tv_mask: dict[str, np.ndarray] = {}
        def tv_liga(inst, a_min, b_min):
            tv_mask.setdefault(inst.id, np.zeros(M, bool))[max(0, int(a_min)):min(M, int(b_min))] = True
        for tv in por_tipo.get("tv", []):
            tc = tipo_comodo(tv.comodo)
            if tc == "sala":
                if r.random() < tvh.get("sala_noite_prob", 0.9):
                    a, b = 18 * 60 + int(r.normal(15, 20)), min(ultimo // 60, 23 * 60 + int(r.normal(20, 25)))
                    m = np.zeros(M, bool); m[a:b] = True
                    tv_mask[tv.id] = tv_mask.get(tv.id, np.zeros(M, bool)) | (m & (ativ > 0))
                for g in gente:
                    if g.cfg.get("tv_dia") and r.random() < tvh.get("dia_prob", 0.5) + (0 if util else 0.2):
                        ini = (13 * 60 + int(r.uniform(0, 150))) if g.sai is not None or r.random() < 0.5 else (9 * 60 + int(r.uniform(0, 60)))
                        fim = ini + int(r.uniform(60, 150))
                        if em_casa_no(g, ini * 60):
                            tv_liga(tv, ini, fim)
            elif tc == "quarto" and tvh.get("quarto_min", 0) > 0:
                for g in gente:
                    if g.cfg["quarto"] == tv.comodo and r.random() < 0.7:
                        q = max(15, r.normal(tvh["quarto_min"], tvh["quarto_min"] / 3))
                        tv_liga(tv, g.dorme / 60 - q, g.dorme / 60)
                        break
        for vg in por_tipo.get("videogame", []):
            for g in gente:
                if g.cfg.get("joga") and r.random() < (0.6 if util else 0.8):
                    if util:
                        ini = max((g.volta or 13 * 3600) + 3600, 14 * 3600) + int(r.uniform(0, 7200))
                        dur = int(r.uniform(60, 120) * 60)
                    else:
                        ini, dur = int(r.uniform(10, 19) * 3600), int(r.uniform(90, 180) * 60)
                    if em_casa_no(g, ini):
                        U(vg, ini, dur, modo="jogo")
                        for tv in do_comodo("tv", vg.comodo):
                            tv_liga(tv, ini // 60, (ini + dur) // 60)
        for iid, m in tv_mask.items():
            for a, b in _trechos(m, 5):
                usos.append(Uso(iid, a * 60, (b - a) * 60, {}))
        pcs = por_tipo.get("notebook", []) + por_tipo.get("computador_desktop", [])
        blocos: list[tuple[int, int]] = []
        usuarios = [g for g in gente if g.cfg.get("usa_computador")] or [g for g in gente if g.cfg.get("idade", 30) < 25]
        for g in usuarios[:1] if pcs else []:
            if g.home_office:
                blocos += [(8 * 3600 + 1800 + int(r.normal(0, 600)), 12 * 3600 + int(r.normal(0, 600))), (13 * 3600 + int(r.normal(0, 600)), 18 * 3600 + int(r.normal(0, 900)))]
            elif r.random() < 0.55:
                ini = max(20 * 3600 + int(r.normal(0, 1800)), (g.volta or 0) + 1800)
                if ini < g.dorme - 1800:
                    blocos.append((ini, ini + int(r.uniform(40, 100) * 60)))
        for a, b in blocos:
            for pc in pcs:
                U(pc, a, b - a, recarga=True)
                for mon in do_comodo("monitor", pc.comodo):
                    U(mon, a, b - a)

        # ---------------- ventilador, ar-condicionado, aquecedor
        # Decisão probabilística (curva logística): a chance de ligar cresce com a temperatura em torno do
        # limiar de cada morador (limiar do perfil + desvio pessoal fixo). Evita o "liga tudo / nada" de um
        # limite rígido. Inclinação de 1,0 °C (ventilador) e 1,2 °C (ar) e desvio pessoal de 0,8 °C: ASSUMIDOS.
        def p_liga(t, t50, incl):
            return 1.0 / (1.0 + np.exp(-(t - t50) / incl))
        def limiar_de(donos, base):
            if not donos:
                return base
            return base + float(np.mean([rng_de(self.semente, "limiar", g.cfg["id"]).normal(0, 0.8) for g in donos]))
        com_ar: set[str] = set()
        for ac in por_tipo.get("ar_condicionado", []):
            tc = tipo_comodo(ac.comodo)
            if tc == "quarto":
                donos = [g for g in gente if g.cfg["quarto"] == ac.comodo]
                t50 = limiar_de(donos, clim.get("limiar_ar_c", 99))
                if donos and r.random() < p_liga(t_ext(21 * 3600), t50, 1.2):
                    ini = min(g.dorme for g in donos) - int(r.uniform(15, 45) * 60)
                    fim = N + max(g.acorda for g in donos)
                    if r.random() < clim.get("prob_timer_ar", 0.35):          # desliga pelo timer no meio da noite
                        fim = min(fim, ini + int(r.uniform(3, 5) * 3600))
                    U(ac, ini, fim - ini, setpoint=clim.get("setpoint_ar_c", 23))
                    com_ar.add(ac.comodo)
            else:
                lim = clim.get("limiar_ar_estar_c", 99)
                if r.random() < p_liga(clima.tmax, lim, 1.2):
                    m = (ativ[:1440] > 0) & (clima.t_ext > lim - 1) & (mins[:1440] >= 12 * 60) & (mins[:1440] < 23 * 60)
                    for a, b in _trechos(m, 30):
                        U(ac, a * 60, (b - a) * 60, setpoint=clim.get("setpoint_ar_c", 23) + 1)
                        com_ar.add(ac.comodo)
        limv0 = clim.get("limiar_ventilador_c", 25.5)
        for ve in por_tipo.get("ventilador", []):
            if ve.comodo in com_ar:
                continue
            tc = tipo_comodo(ve.comodo)
            if tc == "quarto":
                donos = [g for g in gente if g.cfg["quarto"] == ve.comodo]
                limv = limiar_de(donos, limv0)
                if donos and r.random() < p_liga(t_int22, limv, 1.0):
                    vel = 2 if t_int22 > limv + 2.5 else 1 if t_int22 > limv + 1 else 0
                    ini = min(g.dorme for g in donos) - int(r.uniform(10, 30) * 60)
                    fim = N + max(g.acorda for g in donos)
                    if r.random() < clim.get("prob_timer_ventilador", 0.4):   # timer ou desligado ao esfriar a madrugada
                        fim = min(fim, ini + int(r.uniform(2, 4) * 3600))
                    U(ve, ini, fim - ini, velocidade=vel)
            else:
                limv = limiar_de(gente, limv0)
                if r.random() < p_liga(float(clima.t_int.max()), limv + 1.0, 1.0):
                    vel = 1 if float(clima.t_int.max()) < limv + 3 else 2
                    m = (ativ[:1440] > 0) & (clima.t_int > limv + 0.5) & (((mins[:1440] >= 18 * 60) & (mins[:1440] < 23 * 60)) | ((mins[:1440] >= 12 * 60 + 30) & (clima.t_int > limv + 2)))
                    for a, b in _trechos(m, 20):
                        U(ve, a * 60, (b - a) * 60, velocidade=vel)
        for aq in por_tipo.get("aquecedor", []):
            if t_ext(20 * 3600) < 14 and r.random() < 0.6 and ativ[20 * 60] > 0:
                U(aq, 19 * 3600 + 1800, 2.5 * 3600)

        # ---------------- iluminação
        lamp: dict[str, np.ndarray] = {}
        def acende(inst, a_min, b_min, so_escuro=True):
            m = np.zeros(M, bool); m[max(0, int(a_min)):min(M, int(b_min))] = True
            lamp[inst.id] = lamp.get(inst.id, np.zeros(M, bool)) | (m & escuro if so_escuro else m)
        for lp in por_tipo.get("lampada", []):
            tc = tipo_comodo(lp.comodo)
            if tc == "sala":
                lamp[lp.id] = escuro & (ativ > 0) & (mins >= 16 * 60)
            elif tc == "cozinha":
                if "gourmet" in slug(lp.comodo):
                    if not util and r.random() < 0.35:
                        acende(lp, 19 * 60, 22 * 60 + int(r.uniform(0, 60)))
                else:
                    lamp[lp.id] = escuro & (ativ > 0) & ((mins < 8 * 60) | ((mins >= 17 * 60 + 30) & (mins < 21 * 60 + int(r.uniform(0, 45)))))
            elif tc == "quarto":
                for g in gente:
                    if g.cfg["quarto"] == lp.comodo:
                        acende(lp, g.acorda / 60, g.acorda / 60 + 20)
                        antes = 120 if g.cfg.get("idade", 30) < 25 else 40
                        acende(lp, g.dorme / 60 - antes * r.uniform(0.6, 1.2), g.dorme / 60)
                for _, ini, dur in [b for b in banhos if b[0].comodo == lp.comodo]:
                    acende(lp, ini / 60 - 2, (ini + dur) / 60 + 6, so_escuro=False)
            elif tc == "banheiro":
                for _, ini, dur in [b for b in banhos if b[0].comodo == lp.comodo] or ([] if any(c.comodo == lp.comodo for c in chuveiros) else banhos):
                    acende(lp, ini / 60 - 2, (ini + dur) / 60 + 6, so_escuro=False)
                casa = np.flatnonzero(ativ > 0)
                for _ in range(2 * len(gente) if len(casa) else 0):
                    a = int(r.choice(casa)); acende(lp, a, a + 4, so_escuro=False)
            elif tc == "servico":
                for t0, d in ((t_lav, 15), (t_fer, fer["duracao_min"])):
                    if t0 is not None:
                        acende(lp, t0 / 60, t0 / 60 + d)
            elif tc == "escritorio":
                for a, b in blocos:
                    acende(lp, a / 60, b / 60, so_escuro=r.random() < 0.5)
            elif tc == "externa":
                modo = h.get("luz_externa", "nenhuma")
                if modo == "ate_23h":
                    acende(lp, clima.por_min, 23 * 60 + int(r.normal(0, 20)))
                elif modo == "noite_toda":
                    if "garagem" in slug(lp.comodo):
                        for g in gente:
                            if g.cfg.get("carro") and g.volta:
                                acende(lp, g.volta / 60 - 1, g.volta / 60 + 8)
                            if g.cfg.get("carro") and g.sai:
                                acende(lp, g.sai / 60 - 6, g.sai / 60 + 1)
                    else:
                        acende(lp, clima.por_min, 1440 + clima.nascer_min)
        for iid, m in lamp.items():
            for a, b in _trechos(m):
                usos.append(Uso(iid, a * 60, (b - a) * 60, {"fracao": 1.0}))

        # ---------------- piscina, carro elétrico, portão
        pis = h.get("piscina")
        for bp in por_tipo.get("bomba_piscina", []) if pis else []:
            horas = pis["horas_verao"] if data.month in (10, 11, 12, 1, 2, 3) else pis["horas"]
            U(bp, hhmm(pis["inicio"]) + int(r.normal(0, 300)), horas * 3600)
        ve_cfg = h.get("veiculo_eletrico")
        for g in gente:
            carro = g.cfg.get("carro")
            if not carro or g.sai is None:
                continue
            for pt in por_tipo.get("motor_portao", []):
                for t0 in (g.sai - 60, g.sai - 10, g.volta - 20, g.volta + 40):
                    U(pt, t0, pt.modelo.get("duracao_s", 15))
            if carro == "eletrico" and ve_cfg:
                km = max(5.0, r.normal(ve_cfg["km_dia_medio"], ve_cfg["km_dia_desvio"])) if util else r.uniform(20, 80)
                for wb in por_tipo.get("carregador_veicular", []):
                    U(wb, g.volta + 300, 1, energia_kwh=round(km * ve_cfg["kwh_por_km"], 2))
        usos.sort(key=lambda u: u.inicio)
        return usos, dict(atividade=ativ[:1440].copy(), pessoas=gente)
