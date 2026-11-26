"""Clima de Marília-SP: climatologia horária do INMET (A763) + anomalia diária AR(1)."""
from __future__ import annotations
import datetime as dt
import math
from dataclasses import dataclass
import numpy as np
from .dados import clima_dados
from .util import rng_de


@dataclass
class ClimaDia:
    data: dt.date
    t_ext: np.ndarray      # °C por minuto (1440)
    t_int: np.ndarray      # temperatura dentro de casa, °C por minuto (1440)
    nascer_min: int        # minuto do nascer do sol (hora local)
    por_min: int           # minuto do pôr do sol
    anomalia: float

    @property
    def tmax(self) -> float:
        return float(self.t_ext.max())

    def escuro(self) -> np.ndarray:
        m = np.arange(1440)
        return (m < self.nascer_min + 15) | (m > self.por_min - 15)


class Clima:
    def __init__(self, semente: int = 0, dados: dict | None = None):
        self.d = dados or clima_dados()
        self.semente = semente
        self.rho = float(self.d["autocorrelacao_dia"])
        self._z: dict[int, float] = {}

    def _z_dia(self, ordinal: int) -> float:
        """Anomalia padronizada do dia; AR(1) reconstruído com 25 dias de aquecimento (independe da ordem de chamada)."""
        if ordinal in self._z:
            return self._z[ordinal]
        z = 0.0
        for o in range(ordinal - 25, ordinal + 1):
            e = float(rng_de(self.semente, "clima", o).normal())
            z = self.rho * z + math.sqrt(1 - self.rho ** 2) * e
        self._z[ordinal] = z
        return z

    def _horas(self, data: dt.date) -> np.ndarray:
        mes = self.d["meses"][data.month - 1]
        return np.array(mes["hora"], dtype=float) + self._z_dia(data.toordinal()) * mes["sd_dia"]

    def sol(self, data: dt.date) -> tuple[int, int]:
        lat = math.radians(self.d["estacao"]["lat"])
        n = data.timetuple().tm_yday
        decl = math.radians(23.44) * math.sin(2 * math.pi * (284 + n) / 365)
        w0 = math.degrees(math.acos(-math.tan(lat) * math.tan(decl)))
        desloc = 4 * (-45 - self.d["estacao"]["lon"])          # minutos: Marília fica a oeste do meridiano do fuso
        return int(720 - 4 * w0 + desloc), int(720 + 4 * w0 + desloc)

    def dia(self, data: dt.date) -> ClimaDia:
        um = dt.timedelta(days=1)
        serie = np.concatenate([self._horas(data - um), self._horas(data), self._horas(data + um)])
        x = (np.arange(72) + 0.5) * 60 - 1440                   # centro de cada hora, em minutos do dia
        t_ext = np.interp(np.arange(1440), x, serie)
        t_ext = np.clip(t_ext, self.d["tmin_absoluta"] - 2, self.d["tmax_absoluta"] + 2)
        t_int = 0.5 * t_ext + 0.5 * t_ext.mean() + 1.0           # ASSUMIDO: casa amortece metade da variação e fica 1 °C acima
        nas, por = self.sol(data)
        mes = self.d["meses"][data.month - 1]
        return ClimaDia(data, t_ext, t_int, nas, por, self._z_dia(data.toordinal()) * mes["sd_dia"])
