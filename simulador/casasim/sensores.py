"""Modelo de sensor/firmware: o que o medidor escolhido realmente envia ao Raspberry Pi."""
from __future__ import annotations
import numpy as np
from .dados import Canal
from .util import N, rng_de


class Sensor:
    """Um canal de medição. Aplica erro de ganho fixo, ruído, resolução, potência mínima e a
    política de envio do firmware (periódico ou por evento). O contador de energia é cumulativo."""

    def __init__(self, canal: Canal, semente: int, tensao_nominal: float = 127.0, fator_potencia: float = 0.9,
                 intervalo_s: int | None = None):
        s = canal.sensor
        r = rng_de(semente, "sensor", canal.chave)
        sig = s.get("erro_ganho_pct", 1.0) / 100
        self.canal, self.s, self.semente = canal, s, semente
        self.ganho = 1.0 + float(np.clip(r.normal(0, sig), -3 * sig, 3 * sig))
        self.intervalo = int(intervalo_s or s.get("intervalo_s", 60))
        self.fase = int(r.integers(0, self.intervalo))
        self.v_nom, self.fp = tensao_nominal, fator_potencia
        self.e0 = 0.0                 # Wh acumulados até o início do dia corrente
        self.e_fim = 0.0

    def medir(self, p_real: np.ndarray, v_pu: np.ndarray, faltas: list[tuple[int, int]], ordinal: int,
              desligado: list[tuple[int, int]] | None = None) -> dict:
        """Devolve as mensagens do dia: vetores t (segundo do dia), potencia_w, energia_wh, tensao_v, corrente_a, ligado."""
        s = self.s
        r = rng_de(self.semente, "leitura", self.canal.chave, ordinal)
        z = r.normal(0, 1, N).astype(np.float32)                 # sorteado inteiro: refazer o dia não muda o passado
        zv = r.normal(0, 1, N).astype(np.float32)
        pm = p_real.astype(np.float64) * self.ganho
        energia = self.e0 + np.cumsum(pm) / 3600.0
        self.e_fim = float(energia[-1])
        periodicos = np.arange(self.fase, N, self.intervalo)
        if s.get("modo") == "evento":
            lw, lp = s.get("limiar_w", 1), s.get("limiar_pct", 5) / 100
            cand = np.flatnonzero(np.abs(np.diff(pm)) > 0.5 * lw) + 1
            idx, ult = [], pm[0]
            for t in cand:
                v = pm[t]
                if abs(v - ult) >= max(lw, lp * abs(ult)):
                    idx.append(t)
                    ult = v
            idx = np.union1d(np.array(idx, dtype=np.int64), periodicos)
        else:
            idx = periodicos
        if faltas:                                               # sem energia o medidor some da rede (e demora 20 s para voltar)
            ok = np.ones(len(idx), bool)
            for a, b in faltas:
                ok &= ~((idx >= a) & (idx < b + 20))
            idx = idx[ok]
        leit = pm[idx] * (1 + s.get("ruido_pct", 0.3) / 100 * z[idx])
        res = s.get("resolucao_w", 0.1)
        leit = np.round(leit / res) * res
        leit[leit < s.get("potencia_min_w", 0.5)] = 0.0
        v = self.v_nom * v_pu[np.minimum(1439, idx // 60)] * (1 + 0.002 * zv[idx])
        ligado = np.ones(len(idx), bool)
        for a, b in desligado or []:
            ligado &= ~((idx >= a) & (idx < b))
        return dict(t=idx.astype(np.int64), potencia_w=np.round(leit, 2), energia_wh=np.round(energia[idx], 2),
                    tensao_v=np.round(v, 1), corrente_a=np.round(leit / (v * self.fp), 3), ligado=ligado)
