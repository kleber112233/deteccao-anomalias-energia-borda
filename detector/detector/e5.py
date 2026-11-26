"""E5 — análise de uma sessão ao vivo (simulador → MQTT → Pi → alerta de volta ao simulador).

Lê o registro do simulador (`simulador/registros/aovivo_*.jsonl`): falhas injetadas, alertas recebidos (com o relógio
simulado e o real do recebimento) e o gabarito de cada dia concluído (janela em que o sinal mudou de fato).
Casa alertas e falhas com as mesmas regras de `avaliacao.py`.

    python -m detector e5 ..\\simulador\\registros\\aovivo_casa_perfil1_20261123_020605.jsonl
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import avaliacao as av

GERAL = ("q", "residuo")


def _t(s: str) -> int:
    """'2026-01-06 05:17:15' ou ISO com fuso → segundos (horário de Brasília)."""
    return int(pd.Timestamp(s.replace("T", " ")[:19]).timestamp()) + av.FUSO_S


def ler(caminho: str | Path) -> dict:
    ev = [json.loads(l) for l in Path(caminho).read_text(encoding="utf-8").splitlines() if l.strip()]
    ini = next(e for e in ev if e["evento"] == "sessao_iniciada")
    gab = {}
    for e in ev:
        if e["evento"] == "dia_concluido":
            for g in e["gabarito"]:
                gab.setdefault(g["falha_id"], []).append(g)
    inj = {e["falha_id"]: e for e in ev if e["evento"] == "falha_injetada"}
    alertas = [e for e in ev if e["evento"] == "alerta_recebido"]
    vel = [(e["relogio_sim"], e["velocidade"]) for e in ev if e["evento"] in ("sessao_iniciada", "velocidade")]
    # o gabarito de um dia só existe depois que o dia termina: a análise vai até o fim do último dia concluído
    fim = max((_t(e["relogio_sim"]) for e in ev if e["evento"] == "dia_concluido"), default=None)
    return {"inicio": ini, "gabarito": gab, "injecoes": inj, "alertas": alertas, "fim_sim": fim, "velocidades": vel}


def analisar(caminho: str | Path, aquecimento_min: int = 60, desde: str | None = None) -> dict:
    """`desde`: relógio simulado a partir do qual o detector estava ligado (padrão: início da sessão)."""
    s = ler(caminho)
    t_ini = _t(desde or s["inicio"]["relogio_sim"]) + 60 * aquecimento_min
    canais_medidor = {k: v for k, v in s["inicio"]["canais"].items()}
    # eventos: só falhas de aparelho com efeito real, depois do aquecimento, de dias já concluídos
    evs, rede = [], []
    for fid, linhas in s["gabarito"].items():
        efet = [g for g in linhas if g["efetiva"]]
        if not efet:
            continue
        a, b = min(_t(g["efeito_inicio"]) for g in efet), max(_t(g["efeito_fim"]) for g in efet)
        g0 = efet[0]
        if not g0["alerta_de_aparelho"]:
            rede.append((fid, a, b))
            continue
        if a < t_ini:
            continue
        cd = g0.get("canal_direto") or None
        evs.append(av.Evento(fid, g0["tipo"], g0["alvo"], cd, a, b, frozenset(set(GERAL) | ({cd} if cd else set()))))
    lim = s["fim_sim"] - 60 * av.TOLERANCIA_MIN if s["fim_sim"] else None
    evs = [e for e in evs if lim is None or e.fim <= lim]
    linhas = []
    for e in s["alertas"]:
        a = e["alerta"]
        canal = "residuo" if a["medidor_id"] == "residuo" else (
            a["medidor_id"] if (a.get("canal") or 1) == 1 else f"{a['medidor_id']}_c{a['canal']}")
        linhas.append({"canal": canal, "ini": _t(a["ts"]), "fim": _t(a["ts"]), "estagio": a.get("estagio"),
                       "score": a.get("score"), "recebido_sim": _t(e["relogio_sim"]),
                       "recebido_real": pd.Timestamp(e["relogio_real"]).timestamp()})
    al = pd.DataFrame(linhas, columns=["canal", "ini", "fim", "estagio", "score", "recebido_sim", "recebido_real"])
    al = al[al["ini"] >= t_ini].reset_index(drop=True)
    if lim is not None:
        al = al[al["ini"] <= lim].reset_index(drop=True)
    em_falta = np.zeros(len(al), dtype=bool)
    for _, a, b in rede:
        em_falta |= (al["ini"] >= a).to_numpy() & (al["ini"] <= b + 60 * av.RECUPERACAO_MIN).to_numpy()
    dias = ((lim or al["ini"].max()) - t_ini) / 86400 if len(al) or lim else 0
    r = av.ponto(al, evs, max(dias, 1e-9))
    vel = s["velocidades"][-1][1] if s["velocidades"] else 60.0
    tab = []
    for e, d in zip(evs, r["_det"]):
        inj = s["injecoes"].get(e.falha_id)
        lat_real = None
        if d[0] and inj:
            alv = al[(al["canal"].isin(e.canais)) & (al["ini"] >= e.ini - 300) & (al["ini"] <= e.fim + 60 * av.TOLERANCIA_MIN)]
            if len(alv):
                lat_real = float(alv["recebido_real"].min() - pd.Timestamp(inj["relogio_real"]).timestamp())
        estagio = None
        if d[0]:
            alv = al[(al["canal"].isin(e.canais)) & (al["ini"] >= e.ini - 300) & (al["ini"] <= e.fim + 60 * av.TOLERANCIA_MIN)]
            estagio = alv.sort_values("ini")["estagio"].iloc[0] if len(alv) else None
        tab.append({"falha_id": e.falha_id, "tipo": e.tipo, "alvo": e.alvo, "canal_direto": e.canal_direto,
                    "efeito_inicio": pd.Timestamp(e.ini - av.FUSO_S, unit="s"), "duracao_min": (e.fim - e.ini) / 60,
                    "detectado": d[0], "atraso_sim_min": d[1], "localizado": d[2], "canais_alerta": d[3],
                    "estagio": estagio, "latencia_real_s": lat_real})
    eventos = pd.DataFrame(tab)
    al["verdadeiro"] = r["_vp"]
    al["durante_falta"] = em_falta
    sistema = (al["recebido_sim"] - al["ini"]) / max(vel, 1e-9)
    resumo = {"eventos": len(evs), "detectados": int(eventos["detectado"].sum()) if len(eventos) else 0,
              "revocacao": r["revocacao"], "precisao": r["precisao"], "f1": r["f1"], "alertas": int(len(al)),
              "alertas_falsos": int(r["alertas_fp"]), "falsos_durante_falta": int((~al["verdadeiro"] & al["durante_falta"]).sum()),
              "dias_simulados": round(dias, 2), "fp_por_dia": r["fp_por_dia"],
              "atraso_sim_mediana_min": float(eventos.loc[eventos["detectado"], "atraso_sim_min"].median()) if len(eventos) else None,
              "latencia_sistema_mediana_s": float(sistema.median()) if len(al) else None,
              "velocidade": vel, "faltas_de_energia": len(rede)}
    por_tipo = (eventos.groupby("tipo").agg(eventos=("detectado", "size"), detectados=("detectado", "sum"),
                                            atraso_sim_mediana_min=("atraso_sim_min", "median")).reset_index()
                if len(eventos) else pd.DataFrame())
    return {"resumo": resumo, "eventos": eventos, "alertas": al, "por_tipo": por_tipo}
