"""Treino, calibração e teste dos baselines numa casa (perfil × semente) e consolidação das tabelas.

Fluxo por casa:
1. Atributos das três partições (o extrator só aprende o limiar de "ligado" no treino).
2. Para cada modelo e cada canal: ajusta nos primeiros 62 dias do treino (os 10 últimos servem de
   validação para a parada antecipada das redes); normaliza o score pela mediana e pelo máximo do treino
   inteiro do canal (fora das faltas de energia), para que um único θ valha para todos os canais da casa:
   s = 1 é "tão anômalo quanto o minuto mais estranho do treino".
3. Calibração: varre θ, escolhe o de maior F1 por evento. Teste: usado uma vez, com esse θ.
4. Exporta cada modelo para ONNX e refaz o teste com os scores do ONNX Runtime (confere que dá o mesmo).
"""
from __future__ import annotations

import json
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import avaliacao as av
from .atributos import RESIDUO, Extrator, nomes_seq, nomes_tab
from .dados import carregar_telemetria
from .modelos import criar

DIAS_VAL = 10
Q_ESCALA = 1.0          # escala = máximo do treino do canal (DIARIO.md, D4)


def janelas(seq: np.ndarray, L: int, idx: np.ndarray) -> np.ndarray:
    """Sequências [n, L, d] que terminam nos minutos `idx` (todos >= L−1)."""
    sv = np.lib.stride_tricks.sliding_window_view(seq, L, axis=0)      # [M−L+1, d, L]
    return np.ascontiguousarray(sv[idx - (L - 1)].transpose(0, 2, 1))


class Entrada:
    """Monta a entrada de um modelo para um canal: linhas tabulares ou janelas de L minutos."""

    def __init__(self, modelo, A, c):
        self.seq = modelo.entrada == "seq"
        self.L = getattr(modelo, "L", 1)
        self.X = A.seq[c] if self.seq else A.tab[c]
        self.dec = A.decidivel[c].copy()
        if self.seq:
            self.dec[: self.L - 1] = False

    def linhas(self, idx):
        return janelas(self.X, self.L, idx) if self.seq else self.X[idx]


def _pontuar_em_lotes(f, ent: Entrada, idx: np.ndarray, lote: int = 8192) -> np.ndarray:
    out = np.empty(len(idx))
    for i in range(0, len(idx), lote):
        out[i:i + lote] = f(ent.linhas(idx[i:i + lote]))
    return out


def _escala(raw: np.ndarray) -> tuple[float, float]:
    med = float(np.median(raw))
    esc = float(np.quantile(raw, Q_ESCALA) - med)
    if esc <= 1e-9:
        esc = float(raw.max() - med)
    if esc <= 1e-9:
        esc = 1.0
    return med, esc


def _versoes() -> dict:
    import onnxruntime
    import sklearn
    v = {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
         "scikit-learn": sklearn.__version__, "onnxruntime": onnxruntime.__version__,
         "sistema": platform.platform(), "processador": platform.processor() or platform.machine()}
    try:
        import torch
        v["torch"] = torch.__version__
    except ImportError:
        pass
    try:
        import skl2onnx
        v["skl2onnx"] = skl2onnx.__version__
    except ImportError:
        pass
    return v


def _limpo(d: dict) -> dict:
    return {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in d.items() if not k.startswith("_")}


def rodar_casa(pasta_dados: Path, perfil: str, semente: int, modelos: list[str], saida: Path,
               onnx: bool = True, opcoes: dict | None = None, log=print, avaliar_teste: bool = True) -> list[dict]:
    """`avaliar_teste=False` (modo desenvolvimento): o teste nem é lido; as métricas saem da calibração.
    Toda escolha de projeto foi feita nesse modo, para o teste ser usado uma vez só."""
    opcoes = opcoes or {}
    parts = ("calibracao", "teste") if avaliar_teste else ("calibracao",)
    ultima = parts[-1]
    pasta = Path(pasta_dados) / perfil / f"semente_{semente}"
    t0 = time.perf_counter()
    tel_tr = carregar_telemetria(pasta, "treino")
    ext = Extrator().ajustar(tel_tr)
    A = {"treino": ext.transformar(tel_tr)}
    for p in parts:
        A[p] = ext.transformar(carregar_telemetria(pasta, p))
    del tel_tr
    log(f"[{perfil} s{semente}] atributos prontos em {time.perf_counter() - t0:.1f} s; canais: {len(A['treino'].canais)}")

    canais, geral = A["treino"].canais, A["treino"].geral
    At = A["treino"]
    corte = At.t_fim[0] - 60 + (int(round((At.t_fim[-1] - At.t_fim[0]) / 86400)) + 1 - DIAS_VAL) * 86400
    eh_fit = At.t_fim < corte
    sup_tr = av.supressao(At.sem_sinal)

    parte = {}
    for p in parts:
        a = A[p]
        sl = slice(a.m0, a.M)
        sup = av.supressao(a.sem_sinal)[sl]
        evs, rede = av.eventos(pasta, p, geral + [RESIDUO])
        dias = (a.M - a.m0) / 1440.0
        parte[p] = {"sl": sl, "t": a.t_fim[sl], "sup": sup, "evs": evs, "rede": rede, "dias": dias}
        rede_res = av.avaliar_rede(a.sem_sinal[sl], a.t_fim[sl], rede)
        parte[p]["rede_res"] = rede_res

    casa_dir = Path(saida) / perfil / f"semente_{semente}"
    casa_dir.mkdir(parents=True, exist_ok=True)
    (casa_dir / "casa.json").write_text(json.dumps({
        "perfil": perfil, "semente": semente, "canais": canais, "geral": geral,
        "limiar_ligado_w": ext.limiar_on, "p_ligado_por_hora": ext.p_on_hora, "dias_val": DIAS_VAL,
        "eventos": {p: len(parte[p]["evs"]) for p in parte},
        "rede": {p: parte[p]["rede_res"] for p in parte}, "versoes": _versoes()}, indent=1, ensure_ascii=False))

    linhas = []
    for nome in modelos:
        t_mod = time.perf_counter()
        S = {p: {} for p in parts}
        S_onnx = {}
        cfg_canais, paridade = {}, []
        seg_treino, seg_inf, n_inf, seg_inf_onnx = 0.0, 0.0, 0, 0.0
        mdir = casa_dir / nome
        mdir.mkdir(exist_ok=True)
        for c in canais:
            m = criar(nome, semente=semente, **opcoes.get(nome, {}))
            ent = Entrada(m, At, c)
            idx_fit = np.flatnonzero(ent.dec & eh_fit)
            idx_val = np.flatnonzero(ent.dec & ~eh_fit)
            passo = getattr(m, "passo_treino", 1)
            m.ajustar(ent.linhas(idx_fit[::passo]), ent.linhas(idx_val[::passo]))
            seg_treino += m.segundos_treino
            raw_tr = _pontuar_em_lotes(m.pontuar, ent, np.flatnonzero(ent.dec & ~sup_tr))
            med, esc = _escala(raw_tr)
            for p in parts:
                ep = Entrada(m, A[p], c)
                idx = np.flatnonzero(ep.dec[parte[p]["sl"]]) + A[p].m0
                t = time.perf_counter()
                raw = _pontuar_em_lotes(m.pontuar, ep, idx)
                if p == ultima:
                    seg_inf += time.perf_counter() - t
                    n_inf += len(idx)
                s = np.full(A[p].M - A[p].m0, np.nan)
                s[idx - A[p].m0] = (raw - med) / esc
                S[p][c] = s
                if onnx and p == ultima:
                    import onnxruntime as ort
                    mo = m.para_onnx()
                    (mdir / f"{c}.onnx").write_bytes(mo.SerializeToString())
                    so = ort.SessionOptions()
                    so.intra_op_num_threads = 1
                    sess = ort.InferenceSession(mo.SerializeToString(), so, providers=["CPUExecutionProvider"])
                    t = time.perf_counter()
                    raw_o = _pontuar_em_lotes(
                        lambda x: sess.run(["score"], {"x": np.asarray(x, np.float32)})[0].astype(np.float64),
                        ep, idx)
                    seg_inf_onnx += time.perf_counter() - t
                    so_ = np.full_like(s, np.nan)
                    so_[idx - A[p].m0] = (raw_o - med) / esc
                    S_onnx[c] = so_
                    dif = np.abs(raw_o - raw)
                    paridade.append({"canal": c, "max_abs": float(dif.max()) if len(dif) else 0.0,
                                     "max_rel": float((dif / (np.abs(raw) + 1e-6)).max()) if len(dif) else 0.0})
            cfg_canais[c] = {"mediana": med, "escala": esc, "limiar_ligado_w": ext.limiar_on[c],
                             "p_ligado_por_hora": ext.p_on_hora[c],
                             "atributos": nomes_seq(c in geral) if m.entrada == "seq" else nomes_tab(c in geral),
                             "hiperparametros": m.hiperparametros()}
            del m

        # calibração: escolhe (θ, k)
        pc = parte["calibracao"]
        cv_cal = av.curva(S["calibracao"], pc["t"], pc["sup"], pc["evs"], pc["dias"])
        theta, k = av.escolher_limiar(cv_cal)
        cv_cal.to_csv(mdir / "curva_calibracao.csv", index=False)
        # teste: usado uma vez com (θ, k); a curva só serve para a AUC-PR. Em desenvolvimento, avalia a própria calibração.
        pt = parte[ultima]
        cv_te = av.curva(S[ultima], pt["t"], pt["sup"], pt["evs"], pt["dias"], persistencias=(k,))
        al = av.alertas(S[ultima], pt["t"], theta, pt["sup"], k)
        res = av.ponto(al, pt["evs"], pt["dias"])
        det = res["_det"]
        ev_df = pd.DataFrame([{"falha_id": e.falha_id, "tipo": e.tipo, "alvo": e.alvo, "canal_direto": e.canal_direto,
                               "ini": e.ini, "fim": e.fim, "detectado": d[0], "atraso_min": d[1],
                               "localizado": d[2], "canais_alerta": d[3]} for e, d in zip(pt["evs"], det)])
        al = al.assign(verdadeiro=res["_vp"])
        ev_df.to_csv(mdir / f"eventos_{ultima}.csv", index=False)
        al.to_csv(mdir / f"alertas_{ultima}.csv", index=False)
        if avaliar_teste:
            cv_te.to_csv(mdir / "curva_teste.csv", index=False)

        atrasos = ev_df.loc[ev_df["detectado"], "atraso_min"]
        com_direto = ev_df[ev_df["canal_direto"].notna()]
        linha = {
            "perfil": perfil, "semente": semente, "modelo": nome, "canais": len(canais), "avaliado_em": ultima,
            "theta": theta, "persistencia_k": k, "f1_calibracao": float(cv_cal["f1"].max()),
            "auc_pr_evento_calibracao": av.auc_pr_evento(cv_cal, k),
            "auc_pr_evento": av.auc_pr_evento(cv_te, k),
            "auc_pr_minuto": av.auc_pr_minuto(S[ultima], pt["t"], pt["sup"], pt["evs"]),
            **_limpo(res),
            "eventos": len(pt["evs"]), "detectados": int(ev_df["detectado"].sum()),
            "atraso_mediana_min": float(atrasos.median()) if len(atrasos) else np.nan,
            "atraso_media_min": float(atrasos.mean()) if len(atrasos) else np.nan,
            "revocacao_localizada": float(com_direto["localizado"].mean()) if len(com_direto) else np.nan,
            "segundos_treino": seg_treino, "segundos_total": time.perf_counter() - t_mod,
            "us_por_janela": 1e6 * seg_inf / max(n_inf, 1),
        }
        if onnx:
            al_o = av.alertas(S_onnx, pt["t"], theta, pt["sup"], k)
            res_o = av.ponto(al_o, pt["evs"], pt["dias"])
            dec = np.concatenate([np.nan_to_num(S[ultima][c], nan=-np.inf) > theta for c in canais])
            dec_o = np.concatenate([np.nan_to_num(S_onnx[c], nan=-np.inf) > theta for c in canais])
            linha.update({
                "onnx_max_abs": max(p["max_abs"] for p in paridade),
                "onnx_max_rel": max(p["max_rel"] for p in paridade),
                "onnx_decisoes_iguais": float(np.mean(dec == dec_o)),
                "onnx_f1": res_o["f1"], "onnx_alertas": res_o["alertas"],
                "onnx_us_por_janela": 1e6 * seg_inf_onnx / max(n_inf, 1),
            })
        (mdir / "config.json").write_text(json.dumps({
            "modelo": nome, "perfil": perfil, "semente": semente, "theta": theta, "persistencia_k": k,
            "normalizacao": "s = (score - mediana) / escala; alarme se s > theta por k minutos seguidos",
            "entrada": "seq" if nome == "lstm_ae" else "tab", "canais": cfg_canais,
            "paridade_onnx": paridade}, indent=1, ensure_ascii=False))
        (mdir / ("metricas.json" if avaliar_teste else "metricas_dev.json")).write_text(json.dumps(_limpo(linha), indent=1, ensure_ascii=False))
        por_tipo = (ev_df.groupby("tipo").agg(eventos=("detectado", "size"), detectados=("detectado", "sum"),
                                              atraso_mediana_min=("atraso_min", "median")).reset_index())
        por_tipo.assign(perfil=perfil, semente=semente, modelo=nome).to_csv(
            mdir / ("por_tipo.csv" if avaliar_teste else "por_tipo_dev.csv"), index=False)
        log(f"[{perfil} s{semente}] {nome:8s} [{ultima}] θ={theta:6.2f} k={k}  F1={_f(linha['f1'])}  P={_f(linha['precisao'])}"
            f"  R={_f(linha['revocacao'])}  AUC-PR(ev)={_f(linha['auc_pr_evento'])}  FP/dia={_f(linha['fp_por_dia'], 2)}"
            f"  atraso={_f(linha['atraso_mediana_min'], 0)} min  ({linha['segundos_total']:.0f} s)"
            + (f"  ONNX: Δmax={linha['onnx_max_abs']:.1e}, decisões iguais={100 * linha['onnx_decisoes_iguais']:.3f}%" if onnx else ""))
        linhas.append(linha)
    return linhas


def rodar_casa_isolada(args: tuple) -> str:
    """Para rodar várias casas em paralelo: cada processo usa 1 thread (sem disputa entre processos)."""
    pasta_dados, perfil, semente, modelos, saida, onnx, opcoes, avaliar_teste = args
    import os
    os.environ["OMP_NUM_THREADS"] = "1"
    try:
        import torch
        torch.set_num_threads(1)
    except ImportError:
        pass
    t = time.perf_counter()
    rodar_casa(pasta_dados, perfil, semente, modelos, saida, onnx=onnx, opcoes=opcoes,
               log=lambda m: print(m, flush=True), avaliar_teste=avaliar_teste)
    return f"{perfil} s{semente} concluída em {(time.perf_counter() - t) / 60:.1f} min"


def _f(x, casas: int = 3) -> str:
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{casas}f}"


def consolidar(saida: Path) -> dict[str, pd.DataFrame]:
    """Junta os resultados de todas as casas em tabelas (média ± desvio-padrão entre sementes)."""
    saida = Path(saida)
    met = pd.DataFrame([json.loads(f.read_text()) for f in sorted(saida.glob("perfil*/semente_*/*/metricas.json"))])
    tipos = pd.concat([pd.read_csv(f) for f in sorted(saida.glob("perfil*/semente_*/*/por_tipo.csv"))], ignore_index=True)
    cols = ["auc_pr_evento", "auc_pr_minuto", "precisao", "revocacao", "f1", "fp_por_dia",
            "atraso_mediana_min", "revocacao_localizada", "us_por_janela"]
    cols = [c for c in cols if c in met]
    agg = met.groupby(["perfil", "modelo"])[cols].agg(["mean", "std"])
    agg.columns = [f"{a}_{b}" for a, b in agg.columns]
    agg = agg.reset_index()
    agg.insert(2, "sementes", met.groupby(["perfil", "modelo"]).size().to_numpy())
    pt = (tipos.groupby(["perfil", "modelo", "tipo"])
          .agg(eventos=("eventos", "sum"), detectados=("detectados", "sum"),
               atraso_mediana_min=("atraso_mediana_min", "median")).reset_index())
    pt["revocacao"] = pt["detectados"] / pt["eventos"]
    met.to_csv(saida / "tabela_por_semente.csv", index=False)
    agg.to_csv(saida / "tabela_perfil_modelo.csv", index=False)
    pt.to_csv(saida / "tabela_por_tipo.csv", index=False)
    return {"por_semente": met, "perfil_modelo": agg, "por_tipo": pt}
