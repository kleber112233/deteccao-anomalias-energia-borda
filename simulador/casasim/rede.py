"""Rede elétrica: tensão ao longo do dia e faltas de energia."""
from __future__ import annotations
import datetime as dt
import numpy as np
from .util import rng_de, N


class Rede:
    """Tensão em pu (1,0 = nominal) por minuto e lista de faltas do dia.

    ASSUMIDO: 5 faltas por ano com duração média de 45 min (ordem de grandeza dos indicadores
    FEC/DEC de distribuidoras paulistas; conferir os valores da ANEEL para a CPFL Paulista).
    """

    def __init__(self, semente: int = 0, faltas_por_ano: float = 5.0, duracao_media_min: float = 45.0):
        self.semente, self.taxa, self.dur = semente, faltas_por_ano, duracao_media_min

    def dia(self, data: dt.date) -> tuple[np.ndarray, list[tuple[int, int]]]:
        r = rng_de(self.semente, "rede", data.toordinal())
        m = np.arange(1440)
        pico = np.exp(-0.5 * ((m - 19.5 * 60) / 75) ** 2)              # afundamento no horário de ponta
        lento = np.cumsum(r.normal(0, 0.0006, 1440))
        lento -= np.linspace(lento[0], lento[-1], 1440)
        v = 1.0 - 0.02 * pico + lento + r.normal(0, 0.002, 1440)
        v = np.clip(v, 0.92, 1.05)                                      # faixa adequada do PRODIST (117–133 V em 127 V)
        faltas = []
        for _ in range(r.poisson(self.taxa / 365.0)):
            ini = int(r.integers(0, N - 120))
            dur = int(np.clip(r.exponential(self.dur * 60), 60, 6 * 3600))
            faltas.append((ini, min(N, ini + dur)))
        return v, faltas
