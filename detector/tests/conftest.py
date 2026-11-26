"""Casa sintética pequena para os testes (não usa os datasets congelados)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

T0 = 1767582000          # 05/01/2026 00:00 em Brasília (03:00 UTC)


def _canal(ts: np.ndarray, p_real_1s: np.ndarray, t_ini: int, intervalo: int, fase: int):
    """Simula um medidor periódico: lê a potência instantânea a cada `intervalo` s e integra a energia real."""
    e_acum = np.cumsum(p_real_1s) / 3600.0                        # Wh a cada segundo
    leituras = np.arange(fase, len(p_real_1s), intervalo)
    return ts[leituras], p_real_1s[leituras], e_acum[leituras]


def geladeira(n_s: int, rng, desligada: tuple[int, int] | None = None):
    """Compressor 100 W, 15 min ligado / 30 min desligado, com variação; opcionalmente parado num trecho."""
    p = np.zeros(n_s)
    t = int(rng.integers(0, 600))
    while t < n_s:
        on = int(rng.normal(900, 60))
        p[t:t + on] = 100 + rng.normal(0, 2)
        t += on + int(rng.normal(1800, 120))
    p += 1.0
    if desligada:
        p[desligada[0]:desligada[1]] = 0.0
    return p


def gerar_casa(pasta: Path, dias=(12, 3, 3), semente=0, queda_horas=4.0):
    """treino/calibração/teste em Parquet + gabarito, no formato dos datasets v1 (2 canais: q e t1)."""
    rng = np.random.default_rng(semente)
    pasta.mkdir(parents=True, exist_ok=True)
    nomes = ("treino", "calibracao", "teste")
    inicio = T0
    linhas_gab = []
    for nome, d in zip(nomes, dias):
        n_s = d * 86400
        ts = inicio + np.arange(n_s)
        queda = None
        if nome != "treino":
            a = int(1.3 * 86400)
            queda = (a, a + int(queda_horas * 3600))
        gel = geladeira(n_s, rng, queda)
        base = 50 + 30 * (((ts - 3 * 3600) % 86400) / 3600 > 18)          # mais consumo à noite
        q = gel + base
        partes = []
        for med, sinal, iv, fase in (("q", q, 30, 3), ("t1", gel, 30, 17)):
            t_l, p_l, e_l = _canal(ts, sinal, inicio, iv, fase)
            partes.append(pd.DataFrame({
                "particao": nome, "ts": t_l, "data_hora": pd.to_datetime(t_l - 3 * 3600, unit="s").astype(str),
                "casa": "sintetica", "comodo": "quadro" if med == "q" else "cozinha", "medidor_id": med, "canal": 1,
                "potencia_w": np.round(p_l, 1), "energia_wh": np.round(e_l + 1000, 2), "tensao_v": 127.0,
                "corrente_a": np.round(p_l / 127, 3), "estado": "ligado", "anomalia": 0, "falha_id": "",
                "falha_tipo": "", "canal_direto": 0}))
        pd.concat(partes).sort_values("ts").to_parquet(pasta / f"{nome}.parquet", index=False)
        if queda:
            ini = pd.Timestamp(inicio + queda[0] - 3 * 3600, unit="s")
            fim = pd.Timestamp(inicio + queda[1] - 3 * 3600, unit="s")
            linhas_gab.append({"falha_id": f"F{len(linhas_gab) + 1:04d}", "tipo": "queda", "alvo": "cozinha.geladeira",
                               "comodo": "Cozinha", "canal_direto": "t1", "inicio": ini, "fim": fim,
                               "efeito_inicio": ini, "efeito_fim": fim, "efetiva": True, "alerta_de_aparelho": True,
                               "origem": "plano", "params": "{}", "dia": ini.date(), "particao": nome})
        inicio += n_s
    pd.DataFrame(linhas_gab).to_csv(pasta / "gabarito_falhas.csv", index=False)
    return pasta


@pytest.fixture(scope="session")
def casa(tmp_path_factory):
    return gerar_casa(tmp_path_factory.mktemp("casa") / "perfilX" / "semente_1")
