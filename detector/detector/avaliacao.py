"""Avaliação por evento. ÚNICO módulo que lê o gabarito.

Definições (DIARIO.md, seção C):
- Evento = uma falha do gabarito com `alerta_de_aparelho = True` e pelo menos um dia `efetiva = True`.
  Intervalo do evento = do primeiro `efeito_inicio` ao último `efeito_fim` efetivos (o sinal mudou de fato).
  Falhas que não mudaram o sinal não entram (não se cobra do detector o que não existiu).
- Canais que podem detectar o evento: o `canal_direto` (medidor próprio do aparelho), se houver, os canais
  do medidor geral (o aparelho sempre aparece no geral) e o canal virtual `residuo` (geral − medidores próprios).
- Alarme no minuto m e canal c: score normalizado > θ por k minutos seguidos (persistência), fora da
  supressão de falta de energia. Minutos de alarme do mesmo canal separados por até `JUNTAR_MIN` viram um
  único ALERTA. θ e k ∈ {1, 3, 5} são escolhidos juntos na calibração.
- Um alerta é verdadeiro (VP) se começa entre `efeito_inicio − FOLGA_ANTES_MIN` e `efeito_fim + TOLERANCIA_MIN`
  de um evento, num canal que pode detectá-lo. Os demais alertas são falsos (FP).
- Evento detectado = tem ao menos um alerta VP. Atraso = início do 1º alerta VP − efeito_inicio (≥ 0).
- Precisão por evento (Hundman et al., 2018): eventos detectados / (eventos detectados + alertas FP).
  Vários alertas sobre o mesmo evento contam uma vez só; cada alerta falso conta. Revocação = eventos
  detectados / eventos; F1 = média harmônica. Também se informa FP por dia (o que o morador sente).
- AUC-PR por evento: área sob a curva precisão × revocação varrendo θ (soma em degraus, como a
  average precision). Também se informa a AUC-PR por minuto (rótulo do minuto), para comparar com a literatura.
- Falta de energia (`alvo = rede`) não é alerta de aparelho: tem avaliação própria (regra do silêncio).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

JUNTAR_MIN = 10
FOLGA_ANTES_MIN = 5
TOLERANCIA_MIN = 30
RECUPERACAO_MIN = 30     # depois de uma falta, os alarmes ficam suprimidos por 30 min (aparelhos religando)
FUSO_S = 3 * 3600        # horário de Brasília → UTC


def _epoch(serie: pd.Series) -> np.ndarray:
    dt = pd.to_datetime(serie)
    return ((dt - pd.Timestamp("1970-01-01")) // pd.Timedelta("1s")).to_numpy(np.int64) + FUSO_S


@dataclass
class Evento:
    falha_id: str
    tipo: str
    alvo: str
    canal_direto: str | None
    ini: int        # segundos (epoch)
    fim: int
    canais: frozenset


def eventos(pasta: str | Path, particao: str, geral: list[str]) -> tuple[list[Evento], pd.DataFrame]:
    """Eventos de aparelho da partição e a tabela de faltas de energia (rede).
    `geral`: canais que enxergam a casa toda (medidor geral e resíduo); valem para qualquer evento."""
    g = pd.read_csv(Path(pasta) / "gabarito_falhas.csv")
    g = g[g["particao"] == particao]
    rede = g[~g["alerta_de_aparelho"].astype(bool)].copy()
    rede["ini"], rede["fim"] = _epoch(rede["efeito_inicio"]), _epoch(rede["efeito_fim"])
    ap = g[g["alerta_de_aparelho"].astype(bool) & g["efetiva"].astype(bool)].copy()
    ap["ini"], ap["fim"] = _epoch(ap["efeito_inicio"]), _epoch(ap["efeito_fim"])
    evs = []
    for fid, gr in ap.groupby("falha_id", sort=True):
        cd = gr["canal_direto"].iloc[0]
        cd = None if pd.isna(cd) else str(cd)
        canais = set(geral) | ({cd} if cd else set())
        evs.append(Evento(fid, gr["tipo"].iloc[0], gr["alvo"].iloc[0], cd, int(gr["ini"].min()),
                          int(gr["fim"].max()), frozenset(canais)))
    return evs, rede[["falha_id", "ini", "fim"]].drop_duplicates("falha_id")


def supressao(sem_sinal: np.ndarray, recuperacao: int = RECUPERACAO_MIN) -> np.ndarray:
    """Minutos sem nenhum canal da casa falando e os `recuperacao` minutos seguintes."""
    s = sem_sinal.astype(bool).copy()
    fins = np.flatnonzero(sem_sinal[:-1] & ~sem_sinal[1:]) + 1
    for f in fins:
        s[f:f + recuperacao] = True
    return s


def _rodadas(mask: np.ndarray, juntar: int) -> list[tuple[int, int]]:
    """Índices [ini, fim] de trechos True, juntando buracos de até `juntar` minutos."""
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return []
    quebra = np.flatnonzero(np.diff(idx) > juntar + 1)
    inis = np.r_[idx[0], idx[quebra + 1]]
    fins = np.r_[idx[quebra], idx[-1]]
    return list(zip(inis.tolist(), fins.tolist()))


PERSISTENCIAS = (1, 3, 5)


def persistente(mask: np.ndarray, k: int) -> np.ndarray:
    """True no minuto m se os k minutos que terminam em m estão todos True (causal)."""
    if k <= 1:
        return mask
    c = np.convolve(mask.astype(np.int32), np.ones(k, dtype=np.int32))[: len(mask)]
    return c >= k


def alertas_de_mascara(A: dict[str, np.ndarray], S: dict[str, np.ndarray], t_fim: np.ndarray, supr: np.ndarray,
                       k: int = 1) -> pd.DataFrame:
    """Alertas a partir de máscaras de alarme por canal (já decididas por quem chama: limiar, cascata...)."""
    linhas = []
    for c, a_ in A.items():
        alarme = persistente(a_ & ~supr, k)
        s = S[c]
        for a, b in _rodadas(alarme, JUNTAR_MIN):
            linhas.append((c, int(t_fim[a]), int(t_fim[b]), float(np.nanmax(s[a:b + 1]))))
    return pd.DataFrame(linhas, columns=["canal", "ini", "fim", "score_max"])


def alertas(S: dict[str, np.ndarray], t_fim: np.ndarray, theta: float, supr: np.ndarray, k: int = 1) -> pd.DataFrame:
    """Alertas (canal, ini, fim, score_max) para um limiar θ e persistência k sobre os scores normalizados."""
    return alertas_de_mascara({c: np.nan_to_num(s, nan=-np.inf) > theta for c, s in S.items()}, S, t_fim, supr, k)


def casar(al: pd.DataFrame, evs: list[Evento]):
    """Marca cada alerta como VP/FP e cada evento como detectado (com atraso e se foi localizado)."""
    vp = np.zeros(len(al), dtype=bool)
    det = []
    if len(al):
        canal, ini = al["canal"].to_numpy(), al["ini"].to_numpy()
    for e in evs:
        if len(al):
            ok = (np.isin(canal, list(e.canais)) & (ini >= e.ini - 60 * FOLGA_ANTES_MIN)
                  & (ini <= e.fim + 60 * TOLERANCIA_MIN))
        else:
            ok = np.zeros(0, dtype=bool)
        vp |= ok
        if ok.any():
            atraso = max(0.0, (ini[ok].min() - e.ini) / 60.0)
            local = bool(e.canal_direto is not None and np.any(canal[ok] == e.canal_direto))
            det.append((True, atraso, local, ",".join(sorted(set(canal[ok])))))
        else:
            det.append((False, np.nan, False, ""))
    return vp, det


def ponto(al: pd.DataFrame, evs: list[Evento], dias: float) -> dict:
    vp, det = casar(al, evs)
    n_al = len(al)
    n_fp = int(n_al - vp.sum())
    n_det = int(sum(d[0] for d in det))
    rev = n_det / len(evs) if evs else np.nan
    prec = n_det / (n_det + n_fp) if n_al else np.nan
    f1 = 2 * prec * rev / (prec + rev) if n_al and (prec + rev) > 0 else 0.0
    return {"precisao": prec, "revocacao": rev, "f1": f1, "alertas": n_al, "alertas_fp": n_fp,
            "fp_por_dia": n_fp / dias, "_det": det, "_vp": vp}


def limiares_candidatos(S: dict[str, np.ndarray], supr: np.ndarray, n: int = 120) -> np.ndarray:
    v = np.concatenate([s[~supr & np.isfinite(s)] for s in S.values()])
    if len(v) == 0:
        return np.array([0.0])
    q = 1 - np.logspace(-6, np.log10(0.5), n)          # do topo 1e-6 até a mediana
    return np.unique(np.quantile(v, q))[::-1]           # do mais alto para o mais baixo


def curva(S, t_fim, supr, evs, dias, limiares=None, persistencias=PERSISTENCIAS) -> pd.DataFrame:
    if limiares is None:
        limiares = limiares_candidatos(S, supr)
    pts = []
    for k in persistencias:
        for th in limiares:
            p = ponto(alertas(S, t_fim, th, supr, k), evs, dias)
            pts.append({"k": k, "theta": float(th), **{a: v for a, v in p.items() if not a.startswith("_")}})
    return pd.DataFrame(pts)


def auc_pr_evento(cv: pd.DataFrame, k: int) -> float:
    """Soma em degraus Σ (R_i − R_{i−1}) · P_i, do limiar mais alto para o mais baixo, com persistência k."""
    c = cv[cv["k"] == k].sort_values("theta", ascending=False)
    r_ant, area = 0.0, 0.0
    for _, l in c.iterrows():
        if l["alertas"] == 0 or np.isnan(l["revocacao"]):
            continue
        if l["revocacao"] > r_ant:
            area += (l["revocacao"] - r_ant) * l["precisao"]
            r_ant = l["revocacao"]
    return float(area)


def escolher_limiar(cv: pd.DataFrame) -> tuple[float, int]:
    """(θ, k) que maximizam o F1 por evento; empate → menos alertas, depois θ mais alto."""
    m = cv[cv["f1"] >= cv["f1"].max() - 1e-12].sort_values(["alertas", "theta"], ascending=[True, False])
    return float(m["theta"].iloc[0]), int(m["k"].iloc[0])


def auc_pr_minuto(S, t_fim, supr, evs) -> float:
    from sklearn.metrics import average_precision_score
    y, s = [], []
    for c, sc in S.items():
        rot = np.zeros(len(t_fim), dtype=bool)
        for e in evs:
            if c in e.canais:
                rot |= (t_fim > e.ini) & (t_fim <= e.fim + 60)
        ok = ~supr & np.isfinite(sc)
        y.append(rot[ok])
        s.append(sc[ok])
    y, s = np.concatenate(y), np.concatenate(s)
    return float(average_precision_score(y, s)) if y.any() else np.nan


def avaliar_rede(sem_sinal: np.ndarray, t_fim: np.ndarray, rede: pd.DataFrame) -> dict:
    """Regra do silêncio: todos os canais mudos ao mesmo tempo = falta de energia (evento da rede)."""
    trechos = _rodadas(sem_sinal, 0)
    det = 0
    usados = np.zeros(len(trechos), dtype=bool)
    for _, f in rede.iterrows():
        hit = [i for i, (a, b) in enumerate(trechos)
               if t_fim[a] - 60 <= f["fim"] + 300 and t_fim[b] >= f["ini"]]
        det += bool(hit)
        usados[hit] = True
    return {"faltas": int(len(rede)), "faltas_reconhecidas": int(det),
            "silencios_sem_falta": int((~usados).sum()) if len(trechos) else 0}
