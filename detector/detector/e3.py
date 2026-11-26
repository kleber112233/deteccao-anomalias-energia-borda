"""Análise do E3/E4 (teste de carga no Pi).

    python -m detector e3 <pasta do Pi: e3_AAAAMMDD_HHMM> <pasta do PC: simulador/registros/e3> [--saida pasta]

Junta o registro do detector (`servico.jsonl`, uma linha por janela de 10 s), os CSVs dos geradores (uma linha por
segundo e gerador), o `roteiro.json` (início de cada rodada), o `top` do Mosquitto e a temperatura. Para cada
rodada e degrau da rampa (descartando os 20 s iniciais de cada degrau):
- casas, canais, msg/s enviadas (PC) e processadas (Pi), fração processada;
- atraso acima da linha de base (menor p50 da rodada: absorve a diferença de relógio PC × Pi): p95 típico das
  janelas (mediana), pior p95 de janela e pior atraso (máximo) — o atraso de decisão no pior momento do minuto;
- % de minutos-canal escalados ao LSTM-AE, ms de CPU por minuto de casa (atributos + estágios), CPU do detector
  (média e máxima por janela), CPU do Mosquitto, memória, temperatura, orçamento (E4: trajetória do controlador).
Critério fixado antes de rodar (DIARIO K10): degrau sustentado se TODA janela tem p95 acima da base ≤ 2 s e o Pi
processou ≥ 99 % do que foi enviado. Também se informa a "vazão sustentada" (≥ 99 % processado e o atraso volta à
base dentro de cada minuto), que é o limite de capacidade sem fila crescente.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ACOMODACAO_S = 20.0
LIMITE_S = 2.0


def _rampa(texto: str) -> list[tuple[float, int]]:
    p = sorted((float(m) * 60.0, int(n)) for m, n in (x.split(":") for x in texto.split(",")))
    return p


def _top_mosquitto(arq: Path, dia: str) -> pd.DataFrame:
    linhas, t = [], None
    for l in arq.read_text(errors="ignore").splitlines():
        m = re.match(r"top - (\d\d:\d\d:\d\d)", l)
        if m:
            t = pd.Timestamp(f"{dia} {m.group(1)}").tz_localize("America/Sao_Paulo").timestamp()
        elif t is not None and "mosquit" in l:
            c = l.split()
            try:
                linhas.append((t, float(c[8].replace(",", "."))))
            except (IndexError, ValueError):
                pass
    return pd.DataFrame(linhas, columns=["t", "cpu"])


def _temperatura(arq: Path, dia: str) -> pd.DataFrame:
    linhas = []
    for l in arq.read_text(errors="ignore").splitlines():
        m = re.match(r"(\d\d:\d\d:\d\d) temp=([\d.]+)'C throttled=(\S+)", l)
        if m:
            t = pd.Timestamp(f"{dia} {m.group(1)}").tz_localize("America/Sao_Paulo").timestamp()
            linhas.append((t, float(m.group(2)), m.group(3)))
    return pd.DataFrame(linhas, columns=["t", "temp", "throttled"])


def analisar(pasta_pi: str | Path, pasta_pc: str | Path, saida: str | Path | None = None) -> dict:
    pasta_pi, pasta_pc = Path(pasta_pi), Path(pasta_pc)
    saida = Path(saida) if saida else pasta_pi / "analise"
    saida.mkdir(parents=True, exist_ok=True)
    reg = [json.loads(l) for l in (pasta_pi / "servico.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    jan = pd.DataFrame([{**{k: v for k, v in r.items() if k != "total"}, **{f"tot_{k}": v for k, v in r["total"].items()}}
                        for r in reg if r["tipo"] == "carga"])
    rot = json.loads((pasta_pc / "roteiro.json").read_text(encoding="utf-8"))
    rampa = _rampa(rot["rampa"])
    dia = pd.Timestamp(jan["relogio"].iloc[0], unit="s", tz="UTC").tz_convert("America/Sao_Paulo").strftime("%Y-%m-%d")
    top = _top_mosquitto(pasta_pi / "mosquitto_top.txt", dia) if (pasta_pi / "mosquitto_top.txt").exists() else pd.DataFrame(columns=["t", "cpu"])
    temp = _temperatura(pasta_pi / "temperatura.txt", dia) if (pasta_pi / "temperatura.txt").exists() else pd.DataFrame(columns=["t", "temp", "throttled"])
    degraus, trajetorias = [], []
    for rd in rot["rodadas"]:
        nome, t0, t1 = rd["rodada"], rd["inicio"], rd["fim"]
        g = [pd.read_csv(f) for f in sorted(pasta_pc.glob(f"{nome}_p*.csv"))]
        env = pd.concat(g).groupby("segundo")["enviadas"].sum() if g else pd.Series(dtype=float)
        jr = jan[(jan["relogio"] > t0) & (jan["relogio"] <= t1 + 15)].copy()
        base = float(jr["atraso_p50_s"].dropna().min())
        jr["exc_p95"] = jr["atraso_p95_s"] - base
        jr["exc_max"] = jr["atraso_max_s"] - base
        if rd["comando"].get("controlador"):
            trajetorias.append(jr.assign(rodada=nome, minuto=(jr["relogio"] - t0) / 60.0)[
                ["rodada", "minuto", "casas", "msg_por_s", "exc_p95", "exc_max", "orcamento", "orcamento_proximo",
                 "escalados_pct_janela", "cpu_pct"]])
        lim = [a for a, _ in rampa] + [t1 - t0]
        segmentos = [(a, b_, n, "degrau") for (a, n), b_ in zip(rampa, lim[1:])]
        if lim[-1] - rampa[-1][0] >= 20 * 60:          # degrau final longo (modo fiel): regime = últimos 15 min
            segmentos.append((lim[-1] - 15 * 60 - ACOMODACAO_S, lim[-1], rampa[-1][1], "regime_15min"))
            segmentos.append((lim[-1] - 5 * 60 - ACOMODACAO_S, lim[-1], rampa[-1][1], "regime_5min_final"))
        for a, b, n, tipo in segmentos:
            ja, jb = t0 + a + ACOMODACAO_S, t0 + b
            w = jr[(jr["relogio"] > ja + 10) & (jr["relogio"] <= jb)]          # janelas inteiras dentro do degrau
            if w.empty:
                continue
            ant = jr[jr["relogio"] <= ja + 10].tail(1)
            fim = w.tail(1)
            d = {k: float(fim[f"tot_{k}"].iloc[0]) - (float(ant[f"tot_{k}"].iloc[0]) if len(ant) else 0.0)
                 for k in ("mensagens", "minutos", "decisoes", "escaladas", "seg_atributos", "seg_estagio1", "seg_estagio2")}
            dur = float(fim["relogio"].iloc[0] - (ant["relogio"].iloc[0] if len(ant) else ja))
            seg = env.loc[(env.index >= a + ACOMODACAO_S) & (env.index < b)]
            enviadas_s = float(seg.mean()) if len(seg) else np.nan
            proc_s = d["mensagens"] / dur if dur > 0 else np.nan
            mq = top[(top["t"] > ja) & (top["t"] <= jb)]["cpu"]
            tp = temp[(temp["t"] > ja) & (temp["t"] <= jb)]
            n_can = int(w["canais"].max())
            fila = w["fila"] if "fila" in w else pd.Series(dtype=float)
            degraus.append({
                "rodada": nome, "tipo": tipo, "orcamento_inicial": rd["comando"].get("orcamento"),
                "controlador": bool(rd["comando"].get("controlador")), "minuto_inicio": a / 60, "casas": n,
                "canais": n_can, "msg_s_enviadas": round(enviadas_s, 1), "msg_s_processadas": round(proc_s, 1),
                "fracao_processada": round(proc_s / enviadas_s, 4) if enviadas_s else np.nan,
                "exc_p95_mediana_s": round(float(w["exc_p95"].median()), 3),
                "exc_p95_pior_s": round(float(w["exc_p95"].max()), 3),
                "atraso_pior_s": round(float(w["exc_max"].max()), 3),
                "fila_max": float(fila.max()) if len(fila) else np.nan,
                "fila_fim_menos_inicio": float(fila.iloc[-1] - fila.iloc[0]) if len(fila) else np.nan,
                "escalados_pct": round(100 * d["escaladas"] / d["decisoes"], 2) if d["decisoes"] else np.nan,
                "ms_por_minuto_casa": round(1e3 * (d["seg_atributos"] + d["seg_estagio1"] + d["seg_estagio2"])
                                            / d["minutos"], 3) if d["minutos"] else np.nan,
                "ms_estagio2_por_minuto_casa": round(1e3 * d["seg_estagio2"] / d["minutos"], 3) if d["minutos"] else np.nan,
                "cpu_detector_media": round(float(w["cpu_pct"].mean()), 1),
                "cpu_detector_max": round(float(w["cpu_pct"].max()), 1),
                "cpu_mosquitto_media": round(float(mq.mean()), 1) if len(mq) else np.nan,
                "mem_mb_max": float(w["mem_mb"].max()), "temp_max": float(tp["temp"].max()) if len(tp) else np.nan,
                "throttled": ",".join(sorted(set(tp["throttled"]))) if len(tp) else "",
                "orcamentos_usados": ",".join(str(x) for x in sorted(set(w["orcamento"]))),
                "base_atraso_s": round(base, 3),
            })
    df = pd.DataFrame(degraus)
    df["sustentado_criterio"] = (df["exc_p95_pior_s"] <= LIMITE_S) & (df["fracao_processada"] >= 0.99)
    df["vazao_sustentada"] = df["fracao_processada"] >= 0.99
    df.to_csv(saida / "e3_degraus.csv", index=False)
    resumo = {}
    for nome, g in df.groupby("rodada", sort=False):
        ok = g[g["sustentado_criterio"]]
        vz = g[g["vazao_sustentada"]]
        resumo[nome] = {"maior_degrau_criterio_casas": int(ok["casas"].max()) if len(ok) else 0,
                        "maior_degrau_criterio_canais": int(ok["canais"].max()) if len(ok) else 0,
                        "maior_vazao_sustentada_casas": int(vz["casas"].max()) if len(vz) else 0,
                        "maior_vazao_sustentada_msg_s": float(vz["msg_s_processadas"].max()) if len(vz) else 0.0,
                        "ms_por_minuto_casa_mediana": float(g["ms_por_minuto_casa"].median()),
                        "escalados_pct_mediana": float(g["escalados_pct"].median())}
    (saida / "e3_resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    if trajetorias:
        pd.concat(trajetorias).to_csv(saida / "e4_trajetoria.csv", index=False)
    return {"degraus": df, "resumo": resumo, "saida": str(saida)}
