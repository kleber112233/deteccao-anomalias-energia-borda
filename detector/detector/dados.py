"""Leitura dos datasets congelados SEM gabarito.

O detector só enxerga o que chegaria pelo MQTT: ts, medidor, canal, potência, energia.
O gabarito é lido apenas em `avaliacao.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROTULOS = ("anomalia", "falha_id", "falha_tipo", "canal_direto")
COLUNAS = ["ts", "medidor_id", "canal", "potencia_w", "energia_wh"]
PARTICOES = ("treino", "calibracao", "teste")
ANTERIOR = {"calibracao": "treino", "teste": "calibracao"}


def _ler(pasta: Path, particao: str) -> pd.DataFrame:
    try:  # caminho oficial: a função do simulador, que recusa colunas de gabarito
        from casasim.datasets import carregar
        df = carregar(pasta, particao, colunas=COLUNAS)
    except ImportError:  # sem casasim instalado (ex.: testes): mesma leitura, mesmas colunas
        df = pd.read_parquet(Path(pasta) / f"{particao}.parquet", columns=COLUNAS)
    assert not set(df.columns) & set(ROTULOS)
    return df


def chaves_dos_canais(df: pd.DataFrame) -> pd.Series:
    """Chave do canal: `t1` em medidor de um canal; `c1_c2` (medidor c1, canal 2) em medidor de vários canais.

    É a mesma convenção do `canal_direto` do gabarito, mas sai só da telemetria.
    """
    multi = df.groupby("medidor_id")["canal"].nunique()
    multi = set(multi[multi > 1].index)
    med = df["medidor_id"].astype(str)
    return pd.Series(np.where(med.isin(multi), med + "_c" + df["canal"].astype(str), med), index=df.index)


@dataclass
class Telemetria:
    """Mensagens de uma casa, já separadas por canal (arrays ordenados no tempo)."""
    canais: list[str]
    geral: list[str]             # canais do medidor geral (`q`, ou uma fase por canal)
    ts: dict[str, np.ndarray]    # segundos (epoch)
    p: dict[str, np.ndarray]     # potencia_w
    e: dict[str, np.ndarray]     # energia_wh (contador acumulado)
    inicio: int                  # 1º segundo da partição pedida (antes disso é só contexto)
    fim: int                     # último segundo + 1


def carregar_telemetria(pasta: str | Path, particao: str, horas_contexto: float = 24.0) -> Telemetria:
    """Lê a partição e, como contexto, as últimas `horas_contexto` horas da partição anterior.

    O contexto serve só para os atributos que olham para trás (janela de 60 min, tempo ligado);
    nenhuma decisão é tomada nele. É o que aconteceria no Pi, que fica ligado o tempo todo.
    """
    pasta = Path(pasta)
    df = _ler(pasta, particao)
    inicio = int(df["ts"].min()) // 60 * 60
    fim = (int(df["ts"].max()) // 60 + 1) * 60
    if particao in ANTERIOR and horas_contexto > 0:
        ant = _ler(pasta, ANTERIOR[particao])
        ant = ant[ant["ts"] >= inicio - horas_contexto * 3600]
        df = pd.concat([ant, df], ignore_index=True)
    df = df.sort_values("ts", kind="stable").reset_index(drop=True)
    df["chave"] = chaves_dos_canais(df)
    canais = sorted(df["chave"].unique(), key=lambda c: (not c.startswith("q"), c))
    geral = [c for c in canais if c == "q" or c.startswith("q_")]
    ts, p, e = {}, {}, {}
    for c, g in df.groupby("chave", sort=False):
        ts[c] = g["ts"].to_numpy(np.int64)
        p[c] = g["potencia_w"].to_numpy(np.float64)
        e[c] = g["energia_wh"].to_numpy(np.float64)
    return Telemetria(canais, geral, ts, p, e, inicio, fim)
