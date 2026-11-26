"""Funções pequenas usadas por todo o pacote."""
from __future__ import annotations
import re, unicodedata, zlib
import datetime as dt
import numpy as np

N = 86400                      # segundos por dia (resolução do sinal "real")
FUSO = dt.timezone(dt.timedelta(hours=-3))   # horário de Brasília (sem horário de verão desde 2019)


def slug(texto: str) -> str:
    """'Área externa/piscina' -> 'area_externa_piscina' (seguro para tópico MQTT)."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def hhmm(txt: str | None, madrugada_e_dia_seguinte: bool = False) -> int | None:
    """'06:30' -> segundos desde a meia-noite. Com a opção ligada, horas antes das 04:00 viram >24h."""
    if not txt:
        return None
    h, m = txt.split(":")
    s = int(h) * 3600 + int(m) * 60
    if madrugada_e_dia_seguinte and int(h) < 4:
        s += N
    return s


def rng_de(semente: int, *chaves) -> np.random.Generator:
    """Gerador independente por (semente, chaves): mexer num aparelho não muda o sorteio dos outros."""
    partes = [int(semente) & 0xFFFFFFFF]
    for c in chaves:
        partes.append(zlib.crc32(str(c).encode()) & 0xFFFFFFFF)
    return np.random.default_rng(np.random.SeedSequence(partes))


def epoch_meia_noite(data: dt.date) -> int:
    return int(dt.datetime(data.year, data.month, data.day, tzinfo=FUSO).timestamp())


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, FUSO).isoformat(timespec="seconds")
