"""Cascata (versão offline, no notebook): estágio 1 = OCSVM + regra; estágio 2 = LSTM-AE.

Usa EXATAMENTE os modelos .onnx da rodada oficial dos baselines (`resultados/baselines_v1`), com a normalização
de cada canal guardada no `config.json`. Nada é treinado aqui.

Por canal e minuto m (DIARIO.md, seção I):
- regra(m): a regra de limiar fixo com o limite e a persistência que ela recebeu na calibração dos baselines.
  É um "if": quando dispara, alerta direto (pega magnitude, que os modelos não pegam) e também escala o canal.
- vigilância(m) = s_ocsvm passou de τ ou a regra disparou, em algum dos últimos V minutos → só então o LSTM-AE é
  calculado (minuto escalado).
- alarme(m) = regra(m) ou persistência k de [s_ocsvm(m) > θ_saída (saída antecipada: o estágio 1 tem certeza)
              ou (vigilância(m) e s_lstm(m) > θ2) (o estágio 2 confirma)];
  depois, a mesma junção de alertas e supressão de falta de energia dos baselines.

τ não é escolhido pela qualidade: é fixado por um ORÇAMENTO b = fração de minutos-canal escalados, medida na
calibração sem olhar rótulo (é o que o Pi poderá pagar; no Pi, o controlador de carga mexe em b). Para cada b,
θ_saída, θ2 e k saem da calibração (maior F1 por evento). O teste é usado uma vez.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from . import avaliacao as av
from .atributos import RESIDUO, Extrator
from .dados import carregar_telemetria
from .experimento import Entrada, _pontuar_em_lotes

VIGILANCIA_MIN = 30
ORCAMENTOS = (1.0, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 0.0)     # 0 = só o estágio 1 (OCSVM + regra), sem LSTM-AE
ESTAGIO1 = ("ocsvm", "regra")
ESTAGIO2 = "lstm_ae"
NIVEIS_SAIDA = tuple(np.logspace(-5, -1.5, 15))   # topo 0,001% … 3% dos minutos


def vigilancia(mask: np.ndarray, V: int = VIGILANCIA_MIN) -> np.ndarray:
    """True em m se `mask` foi True em algum dos minutos m−V+1 … m (causal)."""
    c = np.convolve(mask.astype(np.int32), np.ones(V, dtype=np.int32))[: len(mask)]
    return c > 0


def _sessao(caminho: Path):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = 1
    return ort.InferenceSession(str(caminho), so, providers=["CPUExecutionProvider"])


def scores_oficiais(dir_casa: Path, modelo: str, A, particoes: list[str], cache: Path | None = None) -> dict:
    """Scores normalizados s[particao][canal] (só as linhas da partição) com o .onnx e o config.json oficiais.
    `cache`: arquivo .npz onde guardar/ler os scores (para as variantes exploratórias não recalcularem)."""
    cfg = json.loads((dir_casa / modelo / "config.json").read_text(encoding="utf-8"))
    if cache is not None and Path(cache).exists():
        z = np.load(cache)
        out = {p: {} for p in particoes}
        for k in z.files:
            p, c = k.split("|", 1)
            if p in out:
                out[p][c] = z[k]
        if all(len(out[p]) == len(cfg["canais"]) for p in particoes):
            return out, cfg
    seq = cfg["entrada"] == "seq"
    out = {p: {} for p in particoes}
    for c, cc in cfg["canais"].items():
        L = cc["hiperparametros"].get("L_minutos", 1) if seq else 1
        shim = SimpleNamespace(entrada="seq" if seq else "tab", L=L)
        sess = _sessao(dir_casa / modelo / f"{c}.onnx")
        f = lambda x: sess.run(["score"], {"x": np.asarray(x, np.float32)})[0].astype(np.float64)
        for p in particoes:
            a = A[p]
            ent = Entrada(shim, a, c)
            idx = np.flatnonzero(ent.dec[a.m0:]) + a.m0
            s = np.full(a.M - a.m0, np.nan)
            s[idx - a.m0] = (_pontuar_em_lotes(f, ent, idx) - cc["mediana"]) / cc["escala"]
            out[p][c] = s
    if cache is not None:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache, **{f"{p}|{c}": v for p in out for c, v in out[p].items()})
    return out, cfg


def _vig(so, r, tau, V):
    """Vigilância: o OCSVM passou de τ ou a regra disparou em algum dos últimos V minutos."""
    if tau == -np.inf:
        return {c: np.ones(len(x), dtype=bool) for c, x in so.items()}
    out = {}
    for c, x in so.items():
        gatilho = r[c] | ((np.nan_to_num(x, nan=-np.inf) > tau) if tau != np.inf else False)
        out[c] = vigilancia(gatilho, V) if tau != np.inf else np.zeros(len(x), dtype=bool)
    return out


def _decidir(so, r, s2, supr, tau, th_saida, th2, k, V, vig=None):
    """Alarme = regra (limite oficial) OU persistência k de [OCSVM > θ_saída OU (vigilância E LSTM-AE > θ2)]."""
    vig = vig if vig is not None else _vig(so, r, tau, V)
    alarme = {}
    for c in so:
        m = (np.nan_to_num(so[c], nan=-np.inf) > th_saida) | (vig[c] & (np.nan_to_num(s2[c], nan=-np.inf) > th2))
        alarme[c] = r[c] | av.persistente(m & ~supr, k)
    return alarme, vig


def _fracao(vig, so, supr) -> float:
    num = den = 0
    for c in vig:
        ok = ~supr & np.isfinite(so[c])
        num += int((vig[c] & ok).sum())
        den += int(ok.sum())
    return num / max(den, 1)


def tau_do_orcamento(so, r, supr, b: float, V: int = VIGILANCIA_MIN) -> tuple[float, float]:
    """Menor τ cuja fração de minutos escalados não passa de b (busca binária em quantis do OCSVM).
    b = 1: LSTM-AE sempre; b = 0: nunca (só o estágio 1). Os disparos da regra também escalam."""
    if b >= 1.0:
        return -np.inf, 1.0
    if b <= 0.0:
        return np.inf, 0.0
    v = np.concatenate([x[~supr & np.isfinite(x)] for x in so.values()])
    cand = np.unique(np.quantile(v, 1 - np.logspace(-6, np.log10(0.9), 400)))       # crescente
    lo, hi = 0, len(cand) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if _fracao(_vig(so, r, cand[mid], V), so, supr) <= b:
            hi = mid
        else:
            lo = mid + 1
    tau = float(cand[lo])
    return tau, _fracao(_vig(so, r, tau, V), so, supr)


def _score_alerta(so, s2, vig):
    return {c: np.where(vig[c], np.fmax(so[c], s2[c]), so[c]) for c in so}


def avaliar(so, r, s2, t, supr, evs, dias, tau, th_saida, th2, k, V=VIGILANCIA_MIN, vig=None):
    alarme, vig = _decidir(so, r, s2, supr, tau, th_saida, th2, k, V, vig)
    al = av.alertas_de_mascara(alarme, _score_alerta(so, s2, vig), t, supr, 1)
    return av.ponto(al, evs, dias), al, vig


def recall_estagio1(vig, t, evs) -> list[bool]:
    """O evento foi escalado (vigilância ligada em algum minuto do evento, num canal que o enxerga)?"""
    out = []
    for e in evs:
        w = (t >= e.ini) & (t <= e.fim + 60 * av.TOLERANCIA_MIN)
        out.append(any(vig[c][w].any() for c in e.canais if c in vig))
    return out


def escolher(so, r, s2, t, supr, evs, dias, tau, V=VIGILANCIA_MIN, extras_saida=(), extras_th2=()):
    """(θ_saída, θ2, k) de maior F1 por evento na calibração; empate → menos alertas.
    Candidatos: quantis do topo + os limiares oficiais de cada modelo sozinho (`extras_*`)."""
    v1 = np.concatenate([x[~supr & np.isfinite(x)] for x in so.values()])
    saidas = [np.inf] + list(np.unique(np.quantile(v1, [1 - n for n in NIVEIS_SAIDA]))) + list(extras_saida)
    vig = _vig(so, r, tau, V)
    v2 = np.concatenate([s2[c][vig[c] & ~supr & np.isfinite(s2[c])] for c in s2])
    th2s = (list(np.unique(np.quantile(v2, 1 - np.logspace(-5, np.log10(0.5), 30)))) if len(v2) else []) + [np.inf]
    th2s += list(extras_th2)
    melhor = None
    for k in av.PERSISTENCIAS:
        for ts in saidas:
            for t2 in th2s:
                p, _, _ = avaliar(so, r, s2, t, supr, evs, dias, tau, ts, t2, k, V, vig)
                chave = (p["f1"], -p["alertas"], t2, ts)
                if melhor is None or chave > melhor[0]:
                    melhor = (chave, ts, t2, k)
    return melhor[1], melhor[2], melhor[3]


def curva_th2(so, r, s2, t, supr, evs, dias, tau, th_saida, k, V=VIGILANCIA_MIN) -> pd.DataFrame:
    vig = _vig(so, r, tau, V)
    v2 = np.concatenate([s2[c][vig[c] & ~supr & np.isfinite(s2[c])] for c in s2])
    lim = list(np.unique(np.quantile(v2, 1 - np.logspace(-6, np.log10(0.5), 120)))[::-1]) if len(v2) else []
    pts = []
    for t2 in lim + [np.inf]:
        p, _, _ = avaliar(so, r, s2, t, supr, evs, dias, tau, th_saida, t2, k, V, vig)
        pts.append({"k": k, "theta": float(t2) if np.isfinite(t2) else 1e300,
                    **{a: b for a, b in p.items() if not a.startswith("_")}})
    return pd.DataFrame(pts)


def _custos(dir_casa: Path, modelos=(*ESTAGIO1, ESTAGIO2)) -> dict:
    c = {}
    for m in modelos:
        f = dir_casa / m / "metricas.json"
        c[m] = json.loads(f.read_text())["onnx_us_por_janela"] if f.exists() else np.nan
    return c


def rodar_casa_cascata(pasta_dados: Path, dir_baselines: Path, perfil: str, semente: int, saida: Path,
                       avaliar_teste: bool = True, orcamentos=ORCAMENTOS, log=print, filtro: str = "ocsvm",
                       com_regra: bool = True, confirmador: str = ESTAGIO2, cache: Path | None = None) -> pd.DataFrame:
    """Padrão = a cascata oficial (OCSVM + regra → LSTM-AE). `filtro`, `com_regra` e `confirmador` existem só para as
    variantes exploratórias (ex.: o plano original, IF → LSTM-AE), avaliadas depois do teste e relatadas à parte."""
    t0 = time.perf_counter()
    pasta = Path(pasta_dados) / perfil / f"semente_{semente}"
    dir_casa = Path(dir_baselines) / perfil / f"semente_{semente}"
    parts = ["calibracao", "teste"] if avaliar_teste else ["calibracao"]
    ultima = parts[-1]
    tel = carregar_telemetria(pasta, "treino")
    ext = Extrator().ajustar(tel)
    casa = json.loads((dir_casa / "casa.json").read_text(encoding="utf-8"))
    for c, v in casa["limiar_ligado_w"].items():           # os atributos têm de ser os mesmos da rodada oficial
        assert abs(ext.limiar_on[c] - v) < 1e-9, f"limiar de ligado diferente no canal {c}"
    A = {p: ext.transformar(carregar_telemetria(pasta, p)) for p in parts}
    geral = A["calibracao"].geral

    S, cfgs = {}, {}
    usados = [filtro] + (["regra"] if com_regra else []) + [confirmador]
    for m in usados:
        cm = Path(cache) / f"{perfil}_s{semente}_{m}_{'_'.join(parts)}.npz" if cache else None
        S[m], cfgs[m] = scores_oficiais(dir_casa, m, A, parts, cm)
    info = {}
    for p in parts:
        a = A[p]
        evs, _ = av.eventos(pasta, p, geral + [RESIDUO])
        info[p] = {"t": a.t_fim[a.m0:], "sup": av.supressao(a.sem_sinal)[a.m0:], "evs": evs,
                   "dias": (a.M - a.m0) / 1440.0}
    log(f"[{perfil} s{semente}] scores dos modelos oficiais prontos em {time.perf_counter() - t0:.0f} s")

    # conferência: cada modelo sozinho, com o θ e o k oficiais, reproduz o resultado da rodada oficial?
    conf = {}
    pu = info[ultima]
    for m in usados:
        al = av.alertas(S[m][ultima], pu["t"], cfgs[m]["theta"], pu["sup"], cfgs[m]["persistencia_k"])
        conf[m] = {"f1": av.ponto(al, pu["evs"], pu["dias"])["f1"]}
        f = dir_casa / m / ("metricas.json" if avaliar_teste else "nao_existe")
        if f.exists():
            conf[m]["f1_oficial"] = json.loads(f.read_text())["f1"]

    so = {p: S[filtro][p] for p in parts}
    if com_regra:
        th_r, k_r = cfgs["regra"]["theta"], cfgs["regra"]["persistencia_k"]
        r = {p: {c: av.persistente((np.nan_to_num(x, nan=-np.inf) > th_r) & ~info[p]["sup"], k_r)
                 for c, x in S["regra"][p].items()} for p in parts}
    else:
        r = {p: {c: np.zeros(len(x), dtype=bool) for c, x in so[p].items()} for p in parts}
    s2 = {p: S[confirmador][p] for p in parts}
    custo = _custos(dir_casa, usados)
    c1 = custo[filtro] + (custo["regra"] if com_regra else 0.0)
    pc = info["calibracao"]
    linhas, ev_linhas = [], []
    dir_out = Path(saida) / perfil / f"semente_{semente}"
    dir_out.mkdir(parents=True, exist_ok=True)
    for b in orcamentos:
        cal = (so["calibracao"], r["calibracao"], s2["calibracao"], pc["t"], pc["sup"], pc["evs"], pc["dias"])
        tau, frac_cal = tau_do_orcamento(so["calibracao"], r["calibracao"], pc["sup"], b)
        ts, t2, k = escolher(*cal, tau, extras_saida=(cfgs[filtro]["theta"],), extras_th2=(cfgs[confirmador]["theta"],))
        p_cal, _, _ = avaliar(*cal, tau, ts, t2, k)
        pu = info[ultima]
        tst = (so[ultima], r[ultima], s2[ultima], pu["t"], pu["sup"], pu["evs"], pu["dias"])
        res, al, vig = avaliar(*tst, tau, ts, t2, k)
        frac = _fracao(vig, so[ultima], pu["sup"])
        esc = recall_estagio1(vig, pu["t"], pu["evs"])
        cv = curva_th2(*tst, tau, ts, k)
        atrasos = [d[1] for d in res["_det"] if d[0]]
        custo_rel = (c1 + frac * custo[confirmador]) / custo[confirmador]
        linhas.append({
            "perfil": perfil, "semente": semente, "avaliado_em": ultima, "orcamento": b,
            "tau": tau if np.isfinite(tau) else None, "theta_saida": ts if np.isfinite(ts) else None, "theta2": t2 if np.isfinite(t2) else None,
            "k": k, "escalados_calibracao": frac_cal, "escalados": frac, "f1_calibracao": p_cal["f1"],
            "precisao": res["precisao"], "revocacao": res["revocacao"], "f1": res["f1"],
            "fp_por_dia": res["fp_por_dia"], "alertas": res["alertas"],
            "auc_pr_evento": av.auc_pr_evento(cv, k),
            "atraso_mediana_min": float(np.median(atrasos)) if atrasos else None,
            "revocacao_estagio1": float(np.mean(esc)) if esc else None,
            "custo_relativo_ao_lstm": custo_rel, "eventos": len(pu["evs"]),
        })
        for e, d, x in zip(pu["evs"], res["_det"], esc):
            ev_linhas.append({"orcamento": b, "falha_id": e.falha_id, "tipo": e.tipo, "escalado": x,
                              "detectado": d[0], "atraso_min": d[1], "localizado": d[2], "canais_alerta": d[3]})
        l = linhas[-1]
        log(f"[{perfil} s{semente}] b={b:<5} τ={tau:7.2f} escalados={100 * frac:5.1f}%  F1={l['f1']:.3f}"
            f"  R={l['revocacao']:.3f}  rev.estágio1={l['revocacao_estagio1']:.3f}  custo={custo_rel:.2f}×LSTM")
    df = pd.DataFrame(linhas)
    suf = "" if avaliar_teste else "_dev"
    df.to_csv(dir_out / f"orcamentos{suf}.csv", index=False)
    pd.DataFrame(ev_linhas).to_csv(dir_out / f"eventos{suf}.csv", index=False)
    (dir_out / f"conferencia{suf}.json").write_text(json.dumps(
        {"modelos_sozinhos": conf, "custos_us_por_janela_x86": custo, "vigilancia_min": VIGILANCIA_MIN},
        indent=1, ensure_ascii=False, default=float))
    log(f"[{perfil} s{semente}] cascata pronta em {(time.perf_counter() - t0) / 60:.1f} min; "
        f"conferência (F1 sozinho × oficial): " + ", ".join(
            f"{m} {v['f1']:.3f}×{v.get('f1_oficial', float('nan')):.3f}" for m, v in conf.items()))
    return df


def rodar_casa_cascata_isolada(args, **kw) -> str:
    import os
    os.environ["OMP_NUM_THREADS"] = "1"
    t = time.perf_counter()
    rodar_casa_cascata(*args, log=lambda m: print(m, flush=True), **kw)
    return f"{args[2]} s{args[3]} concluída em {(time.perf_counter() - t) / 60:.1f} min"


def consolidar_cascata(saida: Path) -> dict[str, pd.DataFrame]:
    saida = Path(saida)
    df = pd.concat([pd.read_csv(f) for f in sorted(saida.glob("perfil*/semente_*/orcamentos.csv"))], ignore_index=True)
    ev = pd.concat([pd.read_csv(f).assign(perfil=f.parts[-3]) for f in
                    sorted(saida.glob("perfil*/semente_*/eventos.csv"))], ignore_index=True)
    cols = ["escalados", "f1", "precisao", "revocacao", "fp_por_dia", "auc_pr_evento", "atraso_mediana_min",
            "revocacao_estagio1", "custo_relativo_ao_lstm"]
    g = []
    for chave, grupo in [("todos", df)] + list(df.groupby("perfil")):
        a = grupo.groupby("orcamento")[cols].agg(["mean", "std"])
        a.columns = [f"{x}_{y}" for x, y in a.columns]
        g.append(a.reset_index().assign(perfil=chave))
    tab = pd.concat(g, ignore_index=True)
    tipo = (ev.groupby(["orcamento", "tipo"]).agg(eventos=("detectado", "size"), detectados=("detectado", "sum"),
                                                   escalados=("escalado", "sum")).reset_index())
    tipo["revocacao"] = tipo["detectados"] / tipo["eventos"]
    tipo["revocacao_estagio1"] = tipo["escalados"] / tipo["eventos"]
    tab.to_csv(saida / "tabela_cascata.csv", index=False)
    tipo.to_csv(saida / "tabela_cascata_tipo.csv", index=False)
    df.to_csv(saida / "tabela_cascata_por_semente.csv", index=False)
    return {"cascata": tab, "tipo": tipo, "por_semente": df}
