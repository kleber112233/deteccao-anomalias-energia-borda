"""Geradores de consumo: transformam os usos do dia na potência "real" de cada aparelho, segundo a segundo."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .clima import ClimaDia
from .comportamento import Uso
from .dados import Instancia
from .util import N

RESISTIVOS = {"chuveiro", "termostato", "cafeteira"}      # classes cuja potência varia com o quadrado da tensão


@dataclass
class Ctx:
    clima: ClimaDia
    atividade: np.ndarray          # pessoas acordadas em casa, por minuto
    rng: np.random.Generator
    dia: int                       # nº ordinal do dia


def _dep(p: np.ndarray, st: dict, ini: float, perfil: np.ndarray) -> None:
    """Coloca um perfil no dia a partir de `ini`; o que passar da meia-noite fica guardado para o dia seguinte."""
    ini, n = int(ini), len(perfil)
    if n == 0:
        return
    if ini < N:
        a = min(N, ini + n)
        np.maximum(p[ini:a], perfil[:a - ini], out=p[ini:a])
    if ini + n > N:
        s = st.setdefault("sobra", np.zeros(N, dtype=np.float32))
        o = max(0, N - ini)
        d0 = max(0, ini - N)
        k = min(N - d0, n - o)
        np.maximum(s[d0:d0 + k], perfil[o:o + k], out=s[d0:d0 + k])


def _ruido(rng, n: int, amp: float, bloco: int = 30) -> np.ndarray:
    """Ruído lento multiplicativo (1 ± amp), constante em blocos de `bloco` segundos."""
    if amp <= 0 or n <= 0:
        return np.ones(max(n, 0), dtype=np.float32)
    v = rng.normal(0, amp / 2, n // bloco + 2)
    v = np.convolve(v, [0.25, 0.5, 0.25], mode="same")
    return (1 + np.clip(np.repeat(v, bloco)[:n], -amp, amp)).astype(np.float32)


def _ciclos(rng, n: int, periodo: float, fracao, p_on, p_off=0.0, pico: float = 1.0, pico_s: float = 1.5) -> np.ndarray:
    """Liga/desliga com período ± 10% e fração ligada dada (número ou vetor por segundo)."""
    out = np.full(n, p_off, dtype=np.float32) if np.isscalar(p_off) else np.array(p_off[:n], dtype=np.float32)
    t = 0
    while t < n:
        per = max(4.0, periodo * rng.uniform(0.9, 1.1))
        f = float(fracao if np.isscalar(fracao) else fracao[min(t, len(fracao) - 1)])
        on = int(round(per * min(1.0, max(0.0, f))))
        pw = float(p_on if np.isscalar(p_on) else p_on[min(t, len(p_on) - 1)])
        if on > 0:
            out[t:t + on] = pw
            if pico > 1.0:
                out[t:t + max(1, int(pico_s))] = pw * pico
        t += max(1, int(round(per)))
    return out


# ----------------------------------------------------------------------------- classes
def _constante(i: Instancia, usos, ctx, st, p):
    P = i.potencia_w * (i.quantidade if i.tipo == "lampada" else 1)
    if i.tipo == "roteador":
        p[:] = P * _ruido(ctx.rng, N, 0.04, 60)
        return
    for u in usos:
        f = u.params.get("fracao", u.params.get("nivel", 1.0))
        _dep(p, st, u.inicio, np.full(u.duracao, P * f, dtype=np.float32) * _ruido(ctx.rng, u.duracao, 0.01))


def _eletronico(i, usos, ctx, st, p):
    m = i.modelo
    for u in usos:
        base = i.potencia_w
        if u.params.get("modo") == "jogo" and m.get("potencia_jogo_w"):
            base = m["potencia_jogo_w"]
        perfil = base * _ruido(ctx.rng, u.duracao, m.get("variacao", 0.1))
        if u.params.get("recarga") and m.get("potencia_recarga_w"):
            k = min(u.duracao, int(m.get("recarga_min", 45) * 60))
            perfil[:k] = m["potencia_recarga_w"] * _ruido(ctx.rng, k, 0.05)
        _dep(p, st, u.inicio, perfil)


def _refrigeracao(i, usos, ctx, st, p):
    m, Pc = i.modelo, i.potencia_w
    T = ctx.clima.t_int
    e_dia = m["kwh_dia_16c"] + (m["kwh_dia_32c"] - m["kwh_dia_16c"]) * (T - 16.0) / 16.0
    e_dia = np.maximum(e_dia, 0.5 * m["kwh_dia_16c"])
    pmed = e_dia * 1000 / 24 * (1 + 0.04 * np.minimum(ctx.atividade, 3))        # ASSUMIDO: abrir a porta soma até 12%
    deg = m.get("degelo")
    if deg:
        pmed = np.maximum(pmed - deg["potencia_w"] * deg["duracao_min"] / 60 / deg["intervalo_h"], 0.3 * pmed)
    if m.get("inverter"):
        p_on = np.clip(pmed / 0.85, 0.35 * Pc, Pc)
        periodo = 2 * m["periodo_min"] * 60
    else:
        p_on = np.full(1440, Pc)
        periodo = m["periodo_min"] * 60
    frac = np.clip(pmed / p_on, 0.08, 0.97)
    t = int(st.pop("fase", ctx.rng.integers(0, periodo)))                     # continua o ciclo do dia anterior
    comp = np.zeros(N, dtype=np.float32)
    resto = st.pop("resto_on", 0)
    if resto:
        comp[:resto] = st.get("p_on_ant", Pc)
    t = max(t, resto)
    while t < N:
        mi = min(1439, t // 60)
        per = periodo * ctx.rng.uniform(0.9, 1.1)
        on = int(per * frac[mi])
        comp[t:t + on] = p_on[mi]
        if m.get("pico_partida_fator", 1) > 1:
            comp[t:t + 2] = p_on[mi] * m["pico_partida_fator"]
        if t + on > N:
            st["resto_on"], st["p_on_ant"] = t + on - N, float(p_on[mi])
        t += int(per)
    st["fase"] = t - N
    np.maximum(p, comp, out=p)
    if deg:
        prox = st.get("degelo", ctx.dia * N + int(ctx.rng.integers(0, deg["intervalo_h"] * 3600)))
        while prox < (ctx.dia + 1) * N:
            a = prox - ctx.dia * N
            if a >= 0:
                p[a:a + deg["duracao_min"] * 60] = deg["potencia_w"]
            prox += int(deg["intervalo_h"] * 3600 * ctx.rng.uniform(0.9, 1.1))
        st["degelo"] = prox


def _ar(i, usos, ctx, st, p):
    m = i.modelo
    Pt = m["potencia_total_35c_w"]
    for u in usos:
        n = u.duracao
        mi = (u.inicio // 60 + np.arange(n // 60 + 1)) % 1440
        T = ctx.clima.t_ext[mi]
        c = np.clip((T - u.params.get("setpoint", 23) + 4.0) / 15.0, 0.25, 1.0)   # fração da capacidade pedida (ASSUMIDO)
        pd = int(m.get("pulldown_min", 12))
        c[:pd] = 1.0
        if len(c) > pd:
            k = min(10, len(c) - pd)
            c[pd:pd + k] = 1.0 + (c[pd:pd + k] - 1.0) * np.linspace(0.1, 1, k)
        pfull = Pt * (1 + 0.015 * (T - 35.0))
        if m.get("inverter"):
            p29, p35 = m["potencia_parcial_29c_w"], m["potencia_parcial_35c_w"]
            ppart = np.clip(p29 + (p35 - p29) * (T - 29.0) / 6.0, 0.85 * p29, 1.1 * p35)
            pw = np.where(c >= 0.5, ppart + (pfull - ppart) * (c - 0.5) / 0.5, ppart * (0.65 + 0.35 * (c - 0.25) / 0.25))
            perfil = np.repeat(pw, 60)[:n].astype(np.float32) * _ruido(ctx.rng, n, 0.04)
        else:
            perfil = _ciclos(ctx.rng, n, m.get("periodo_min", 12) * 60, np.repeat(c, 60)[:n], np.repeat(pfull, 60)[:n],
                             m.get("ventilador_w", 40), pico=3.0, pico_s=1)
        _dep(p, st, u.inicio, perfil)


def _chuveiro(i, usos, ctx, st, p):
    for u in usos:
        _dep(p, st, u.inicio, np.full(u.duracao, i.potencia_w * u.params.get("nivel", 1.0), dtype=np.float32) * _ruido(ctx.rng, u.duracao, 0.01, 5))


def _termostato(i, usos, ctx, st, p):
    m = i.modelo
    for u in usos:
        n = u.duracao
        pre = min(n, int(m.get("preaquecimento_min", 2) * 60))
        base = float(m.get("base_w", 0))
        perfil = np.full(n, i.potencia_w + base, dtype=np.float32)
        if n > pre:
            perfil[pre:] = _ciclos(ctx.rng, n - pre, m.get("periodo_s", 60), m.get("fracao_ligado", 0.5), i.potencia_w + base, base)
        _dep(p, st, u.inicio, perfil)


def _cafeteira(i, usos, ctx, st, p):
    m = i.modelo
    for u in usos:
        pre = int(m.get("preparo_s", 480))
        if m.get("subtipo") == "capsula":
            perfil = np.full(pre, i.potencia_w, dtype=np.float32)
            perfil[40:45] = 0
        else:
            n = max(u.duracao, pre)
            perfil = np.full(n, i.potencia_w, dtype=np.float32)
            if n > pre:
                perfil[pre:] = _ciclos(ctx.rng, n - pre, 60, m.get("manter_fracao", 0.15), i.potencia_w, 0.0)
        _dep(p, st, u.inicio, perfil)


def _micro_ondas(i, usos, ctx, st, p):
    for u in usos:
        nivel = u.params.get("nivel", 1.0)
        if nivel >= 0.99:
            perfil = np.full(u.duracao, i.potencia_w, dtype=np.float32)
        else:
            perfil = _ciclos(ctx.rng, u.duracao, i.modelo.get("periodo_s", 30), nivel, i.potencia_w, 45.0)
        _dep(p, st, u.inicio, perfil)


def _ventilador(i, usos, ctx, st, p):
    niv = i.modelo["niveis_w"]
    for u in usos:
        v = niv[int(u.params.get("velocidade", 1))]
        _dep(p, st, u.inicio, np.full(u.duracao, v, dtype=np.float32) * _ruido(ctx.rng, u.duracao, 0.02))


def _etapas(rng, etapas, dur_s: int, energia_j: float, p_res: float | None = None) -> np.ndarray:
    partes = []
    for nome, fd, fe in etapas:
        n = max(1, int(fd * dur_s))
        pm = fe * energia_j / n                                   # potência média da etapa
        if nome in ("lavar", "enxaguar"):
            forma = (np.arange(n) % 16 < 12).astype(np.float32)   # agita 12 s, para 4 s
        elif nome == "centrifugar":
            forma = np.linspace(0.4, 1.3, n, dtype=np.float32)
        elif nome in ("aquecimento", "enxague_quente") and p_res:
            forma = np.full(n, 60.0 / p_res, dtype=np.float32)
            forma[:min(n, int(max(0.0, pm * n - 60.0 * n) / (p_res - 60.0)))] = 1.0
        else:
            forma = np.ones(n, dtype=np.float32)
        partes.append(forma * (pm / max(1e-6, float(forma.mean()))))
    return np.concatenate(partes)


def _lavadora(i, usos, ctx, st, p):
    m = i.modelo
    for u in usos:
        perfil = _etapas(ctx.rng, m["etapas"], int(m["duracao_min"] * 60), m["kwh_ciclo"] * 3.6e6)
        sec = m.get("secagem")
        if u.params.get("secar") and sec:
            n = int(sec["duracao_min"] * 60)
            perfil = np.concatenate([perfil, _ciclos(ctx.rng, n, 120, sec["fracao_ligado"], sec["potencia_w"] + 150.0, 150.0)])
        _dep(p, st, u.inicio, perfil * _ruido(ctx.rng, len(perfil), 0.03, 10))


def _lava_loucas(i, usos, ctx, st, p):
    m = i.modelo
    for u in usos:
        perfil = _etapas(ctx.rng, m["etapas"], int(m["duracao_min"] * 60), m["kwh_ciclo"] * 3.6e6, p_res=i.potencia_w)
        _dep(p, st, u.inicio, perfil)


def _motor(i, usos, ctx, st, p):
    m = i.modelo
    P = i.potencia_w * m.get("fator", 1.0)
    for u in usos:
        perfil = P * _ruido(ctx.rng, u.duracao, 0.04, 5)
        perfil[:1] = P * m.get("pico_fator", 2.0)
        _dep(p, st, u.inicio, perfil)


def _carga_ve(i, usos, ctx, st, p):
    m = i.modelo
    for u in usos:
        seg = int(u.params.get("energia_kwh", 6.0) * 3.6e6 / m.get("eficiencia", 0.9) / i.potencia_w)
        rampa = min(seg, int(m.get("rampa_final_min", 15) * 60))
        perfil = np.full(seg + rampa // 2, i.potencia_w, dtype=np.float32)
        perfil[-rampa:] = np.linspace(i.potencia_w, 0.08 * i.potencia_w, rampa) if rampa else perfil[-rampa:]
        _dep(p, st, u.inicio, perfil)


GERADORES = {"constante": _constante, "eletronico": _eletronico, "refrigeracao": _refrigeracao, "ar": _ar, "chuveiro": _chuveiro,
             "termostato": _termostato, "cafeteira": _cafeteira, "micro_ondas": _micro_ondas, "ventilador": _ventilador,
             "lavadora": _lavadora, "lava_loucas": _lava_loucas, "motor_curto": _motor, "motor_demanda": _motor,
             "motor_programado": _motor, "carga_ve": _carga_ve}


def gerar(inst: Instancia, usos: list[Uso], ctx: Ctx, estado: dict) -> np.ndarray:
    """Potência real (W) do aparelho em cada segundo do dia."""
    sobra = estado.pop("sobra", None)
    p = sobra if sobra is not None else np.zeros(N, dtype=np.float32)
    GERADORES[inst.classe](inst, usos, ctx, estado, p)
    sb = float(inst.spec.get("standby_w") or 0) * (inst.quantidade if inst.tipo == "lampada" else 1)
    if sb > 0:
        np.maximum(p, sb, out=p)
    return p
