"""Engenharia de atributos a partir da telemetria irregular.

Tudo é CAUSAL: o atributo do minuto m só usa mensagens com ts < fim do minuto m, porque no Pi a
decisão daquele minuto é tomada nesse instante. Há teste para isso (`test_atributos_sao_causais`).

Etapas, por canal:
1. Grade de 1 minuto. Em cada minuto:
   - `p_med`: média no tempo da potência informada (valor mantido até a próxima mensagem, amostrado
     a cada 5 s). Serve para 10 s, 30 s, 60 s e para o Shelly, que manda por evento.
   - `e_pot`: potência média pela energia (Δenergia_wh / Δt). Pega o que acontece ENTRE leituras.
   - `exc`: maior excesso, num intervalo entre duas mensagens, da potência pela energia sobre a média
     das duas leituras (trapézio). É o rastro dos picos de 1–3 s que `potencia_w` não mostra.
   - `vivo`: houve mensagem nos últimos 150 s.
2. Estado ligado (`on`), tempo ligado (`run_on`), tempo desde a última vez ligado (`desde_on`) e
   número de partidas na última hora (`trans60`). O limiar de "ligado" sai do treino de cada canal.
3. Estatísticas de janela (15 e 60 min), contexto de calendário (hora em seno/cosseno, fim de semana),
   raridade de horário (−log10 da chance, vista no treino, de o canal estar ligado naquela hora) e,
   nos canais do medidor geral, o resíduo geral − soma dos medidores próprios.
4. Canal virtual `residuo` = geral − soma dos medidores próprios, tratado como mais um canal (tem modelo
   próprio). É por ele que aparecem o consumo não explicado e os aparelhos sem medidor.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .dados import Telemetria

SUB_S = 5             # amostragem do valor mantido dentro do minuto
VELHO_S = 150         # sem mensagem há mais de 150 s = canal mudo
TOLERANCIA_OFF = 3    # desligado por até 3 min não encerra um período "ligado" (termostato, ciclo)
TETO_MIN = 1440.0     # tempos são limitados a 24 h
FUSO_S = -3 * 3600    # Brasília, sem horário de verão desde 2019

TAB_BASE = ["p_med15", "p_max15", "p_std15", "p_min15", "p_med60", "p_mediana60", "e_pot15", "exc_max15",
            "frac_on15", "trans60", "run_on", "desde_on", "raridade15", "hora_sin", "hora_cos", "fds"]
TAB_GERAL = ["res_mediana60", "res_med15"]
SEQ_BASE = ["p_med", "e_pot", "exc", "on", "run_on", "desde_on", "raridade", "hora_sin", "hora_cos", "fds"]
SEQ_GERAL = ["res"]


def nomes_tab(geral: bool) -> list[str]:
    return TAB_BASE + (TAB_GERAL if geral else [])


def nomes_seq(geral: bool) -> list[str]:
    return SEQ_BASE + (SEQ_GERAL if geral else [])


def _slog(x):
    """log1p com sinal (comprime watts; o fator de uma falha de magnitude vira soma)."""
    return np.sign(x) * np.log1p(np.abs(x))


def sinais_por_minuto(ts: np.ndarray, p: np.ndarray, e: np.ndarray, g0: int, M: int):
    """Sinais de 1 minuto de um canal. Devolve dict com p_med, p_max, e_pot, exc, vivo (arrays de M)."""
    n_sub = 60 // SUB_S
    ticks = g0 + SUB_S * np.arange(M * n_sub, dtype=np.int64)          # instantes dentro de cada minuto
    idx = np.searchsorted(ts, ticks, side="right") - 1                  # última mensagem com ts <= tick
    ok = idx >= 0
    idx_c = np.where(ok, idx, 0)
    ok &= (ticks - ts[idx_c]) <= VELHO_S
    v = np.where(ok, p[idx_c], np.nan).reshape(M, n_sub)
    cont = np.sum(~np.isnan(v), axis=1)
    soma = np.nansum(v, axis=1)
    p_med = np.where(cont > 0, soma / np.maximum(cont, 1), np.nan)
    p_max = np.where(cont > 0, np.nanmax(np.where(np.isnan(v), -np.inf, v), axis=1), np.nan)

    fim_min = g0 + 60 * (np.arange(M, dtype=np.int64) + 1)              # decisão no fim do minuto
    j = np.searchsorted(ts, fim_min, side="left") - 1                   # última mensagem com ts < fim
    jc = np.where(j >= 0, j, 0)
    vivo = (j >= 0) & ((fim_min - ts[jc]) <= VELHO_S)

    # intervalos entre mensagens consecutivas, atribuídos ao minuto em que terminam (causal)
    dt = np.diff(ts).astype(np.float64)
    de = np.diff(e)
    bom = (dt > 0) & (dt <= VELHO_S)
    mi = (ts[1:] - g0) // 60
    bom &= (mi >= 0) & (mi < M)
    dt, de, mi = dt[bom], de[bom], mi[bom].astype(np.int64)
    pe = de * 3600.0 / dt                                               # W médios no intervalo
    trap = 0.5 * (p[1:][bom] + p[:-1][bom])
    soma_e = np.bincount(mi, weights=de, minlength=M)
    soma_t = np.bincount(mi, weights=dt, minlength=M)
    e_pot = np.where(soma_t > 0, soma_e * 3600.0 / np.maximum(soma_t, 1e-9), np.nan)
    exc = np.full(M, -np.inf)
    np.maximum.at(exc, mi, pe - trap)
    exc = np.where(np.isfinite(exc), exc, np.nan)
    return {"p_med": p_med, "p_max": p_max, "e_pot": e_pot, "exc": exc, "vivo": vivo}


def estados_ligado(on: np.ndarray):
    """run_on, desde_on (min) e partidas, causais. `on` = bool por minuto."""
    M = len(on)
    i = np.arange(M)
    ult_on = np.maximum.accumulate(np.where(on, i, -1))                 # último minuto ligado <= m
    pos = np.flatnonzero(on)
    gap = np.diff(pos, prepend=-10**9)                                  # distância ao "ligado" anterior
    inicio_ep = pos[gap > TOLERANCIA_OFF + 1]                           # minutos que começam um período
    marca = np.full(M, -1)
    marca[inicio_ep] = inicio_ep
    ini_atual = np.maximum.accumulate(marca)                            # início do período mais recente
    desde = np.where(ult_on >= 0, i - ult_on, TETO_MIN).astype(np.float64)
    ativo = (ult_on >= 0) & (desde <= TOLERANCIA_OFF)
    run = np.where(ativo, i - ini_atual + 1, 0).astype(np.float64)
    partidas = np.zeros(M)
    partidas[inicio_ep] = 1.0
    return np.minimum(run, TETO_MIN), np.minimum(desde, TETO_MIN), partidas


@dataclass
class Atributos:
    """Atributos de uma casa numa partição (grade de 1 min). Linhas antes de `m0` são só contexto."""
    canais: list[str]
    geral: list[str]
    t_fim: np.ndarray                         # segundo em que cada minuto termina (instante da decisão)
    m0: int
    tab: dict[str, np.ndarray] = field(default_factory=dict)     # (M, n_tab) float32
    seq: dict[str, np.ndarray] = field(default_factory=dict)     # (M, n_seq) float32, entrada do LSTM-AE
    decidivel: dict[str, np.ndarray] = field(default_factory=dict)
    sem_sinal: np.ndarray | None = None       # nenhum canal da casa com mensagem: falta de energia (regra)

    @property
    def M(self) -> int:
        return len(self.t_fim)


RESIDUO = "residuo"


def _residuo(sinais: dict, geral: list[str]) -> dict:
    """Canal virtual: medidor geral (soma das fases) − soma dos medidores próprios = consumo não explicado
    pelos aparelhos medidos (aparelhos sem medidor, carga de base, carga desconhecida ou irregular)."""
    M = len(next(iter(sinais.values()))["p_med"])
    vivo_g = np.zeros(M, dtype=bool)
    g_p, g_e, pr_p, pr_e = (np.zeros(M) for _ in range(4))
    for c, s in sinais.items():
        if c in geral:
            vivo_g |= s["vivo"]
            g_p += np.nan_to_num(s["p_med"])
            g_e += np.nan_to_num(s["e_pot"])
        else:
            pr_p += np.nan_to_num(s["p_med"])
            pr_e += np.nan_to_num(s["e_pot"])
    p = np.where(vivo_g, g_p - pr_p, np.nan)
    return {"p_med": p, "p_max": p, "e_pot": np.where(vivo_g, g_e - pr_e, np.nan),
            "exc": np.zeros(M), "vivo": vivo_g}


def _hora(t_fim: np.ndarray):
    loc = t_fim + FUSO_S
    hora = (loc % 86400) / 3600.0
    fds = (((loc // 86400) + 3) % 7 >= 5).astype(np.float64)           # 01/01/1970 foi quinta
    return hora, fds


class Extrator:
    """Aprende no treino, por canal, só duas coisas simples (tabelas de consulta que vão para o Pi):
    - o limiar de "ligado": 20% do percentil 90 da potência nos minutos com mais de 1 W (mínimo 2 W);
    - a chance de o canal estar ligado em cada hora do dia, P(ligado | hora), com suavização de Laplace.
    Daí sai a "raridade de horário" = −log10 P(ligado | hora) enquanto o canal está ligado."""

    def __init__(self):
        self.limiar_on: dict[str, float] = {}
        self.p_on_hora: dict[str, list[float]] = {}

    @staticmethod
    def _grade(tel: Telemetria):
        g0 = min(int(v[0]) for v in tel.ts.values()) // 60 * 60
        M = (tel.fim - g0) // 60
        return g0, int(M)

    @staticmethod
    def _sinais(tel: Telemetria, g0: int, M: int) -> dict:
        sinais = {c: sinais_por_minuto(tel.ts[c], tel.p[c], tel.e[c], g0, M) for c in tel.canais}
        sinais[RESIDUO] = _residuo(sinais, tel.geral)
        return sinais

    def ajustar(self, tel: Telemetria) -> "Extrator":
        g0, M = self._grade(tel)
        t_fim = g0 + 60 * (np.arange(M, dtype=np.int64) + 1)
        h = _hora(t_fim)[0].astype(int)
        for c, s in self._sinais(tel, g0, M).items():
            pm = s["p_med"]
            ok = ~np.isnan(pm)
            ativos = pm[ok & (pm > 1.0)]
            thr = float(max(2.0, 0.2 * np.percentile(ativos, 90))) if len(ativos) else 2.0
            self.limiar_on[c] = thr
            on = np.nan_to_num(pm) > thr
            liga = np.bincount(h[ok], weights=on[ok].astype(float), minlength=24)
            tot = np.bincount(h[ok], minlength=24)
            self.p_on_hora[c] = ((liga + 1.0) / (tot + 2.0)).tolist()
        return self

    def transformar(self, tel: Telemetria) -> Atributos:
        g0, M = self._grade(tel)
        t_fim = g0 + 60 * (np.arange(M, dtype=np.int64) + 1)
        m0 = (tel.inicio - g0) // 60
        canais = list(tel.canais) + [RESIDUO]
        A = Atributos(canais, list(tel.geral), t_fim, int(m0))
        sinais = self._sinais(tel, g0, M)
        hora, fds = _hora(t_fim)
        h_int = hora.astype(int)
        h_sin, h_cos = np.sin(2 * np.pi * hora / 24), np.cos(2 * np.pi * hora / 24)
        res = pd.Series(sinais[RESIDUO]["p_med"])

        vivos = np.zeros(M, dtype=int)
        for c in canais:
            s = sinais[c]
            if c != RESIDUO:
                vivos += s["vivo"]
            on = np.nan_to_num(s["p_med"]) > self.limiar_on.get(c, 2.0)
            run, desde, partidas = estados_ligado(on)
            rar = -np.log10(np.asarray(self.p_on_hora.get(c, [0.5] * 24)))[h_int] * on
            pm = pd.Series(s["p_med"])
            ep = pd.Series(s["e_pot"])
            ex = pd.Series(np.maximum(np.nan_to_num(s["exc"], nan=0.0), 0.0))
            r15, r60 = pm.rolling(15, min_periods=1), pm.rolling(60, min_periods=1)
            cols = {
                "p_med15": r15.mean(), "p_max15": r15.max(), "p_std15": pm.rolling(15, min_periods=2).std(),
                "p_min15": r15.min(), "p_med60": r60.mean(), "p_mediana60": r60.median(),
                "e_pot15": ep.rolling(15, min_periods=1).mean(),
                "exc_max15": ex.rolling(15, min_periods=1).max(),
            }
            tab = [_slog(np.nan_to_num(cols[k].to_numpy(), nan=0.0)) for k in
                   ["p_med15", "p_max15", "p_std15", "p_min15", "p_med60", "p_mediana60", "e_pot15", "exc_max15"]]
            tab += [pd.Series(on.astype(float)).rolling(15, min_periods=1).mean().to_numpy(),
                    pd.Series(partidas).rolling(60, min_periods=1).sum().to_numpy(),
                    np.log1p(run), np.log1p(desde),
                    pd.Series(rar).rolling(15, min_periods=1).max().to_numpy(), h_sin, h_cos, fds]
            seq = [_slog(np.nan_to_num(s["p_med"])), _slog(np.nan_to_num(s["e_pot"])),
                   _slog(ex.to_numpy()), on.astype(float), np.log1p(run), np.log1p(desde), rar, h_sin, h_cos, fds]
            if c in tel.geral:
                tab += [_slog(np.nan_to_num(res.rolling(60, min_periods=1).median().to_numpy())),
                        _slog(np.nan_to_num(res.rolling(15, min_periods=1).mean().to_numpy()))]
                seq += [_slog(np.nan_to_num(res.to_numpy()))]
            A.tab[c] = np.column_stack(tab).astype(np.float32)
            A.seq[c] = np.column_stack(seq).astype(np.float32)
            A.decidivel[c] = s["vivo"].copy()
        A.sem_sinal = vivos == 0
        return A
