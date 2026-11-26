"""Campanha de cenários com DADOS NOVOS (nunca vistos pelos modelos), usando a versão ao vivo e os pacotes oficiais.

Para cada casa (perfil × semente): o simulador gera os dias logo DEPOIS do fim do teste daquela semente (mês
seguinte; os modelos nunca viram), com falhas sorteadas pelo próprio simulador. Cada cenário altera o fluxo de
mensagens antes de entregar ao detector, e o resultado é avaliado contra o gabarito do simulador com as mesmas
regras de `avaliacao.py`.

Cenários:
- `limpo_b{0,1,5,20,100}`: fluxo intacto, com orçamentos de escalada 0%, 1%, 5%, 20% e 100%;
- `perda_{1,5,20}`: 1%, 5% ou 20% das mensagens somem (rede Wi-Fi ruim, broker sobrecarregado);
- `medidor_off`: um medidor próprio fica mudo 6 h por semana (bateria, Wi-Fi) — não é falha de aparelho;
- `fora_de_ordem`: 5% das mensagens chegam trocadas com a seguinte;
- `duplicadas`: 5% das mensagens chegam duas vezes;
- `deriva_todos_5`: todos os medidores passam a ler 5% a mais (recalibração/firmware);
- `deriva_geral_5`: só o medidor geral lê 5% a mais (pesa no canal `residuo`).

    python -m detector campanha --dias 28 --processos 2
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import avaliacao as av
from .aovivo import CasaAoVivo

CENARIOS = ["limpo_b5", "limpo_b0", "limpo_b1", "limpo_b20", "limpo_b100", "perda_1", "perda_5", "perda_20",
            "medidor_off", "fora_de_ordem", "duplicadas", "deriva_todos_5", "deriva_geral_5"]
ORC = {"limpo_b0": 0.0, "limpo_b1": 0.01, "limpo_b5": 0.05, "limpo_b20": 0.2, "limpo_b100": 1.0}


def inicio_novo(semente: int) -> dt.date:
    """Dia seguinte ao fim do teste da semente (início 05/01/2026 + 73·(S−1), 120 dias)."""
    return dt.date(2026, 1, 5) + dt.timedelta(days=73 * (semente - 1) + 120)


def gerar(perfil: str, semente: int, dias: int, pasta: Path, falhas_por_semana: float = 10.0) -> Path:
    """Simula 1 dia de contexto + `dias` avaliados. Guarda telemetria e gabarito (uma vez por casa)."""
    from casasim.motor import Simulador
    pasta = Path(pasta)
    if (pasta / "telemetria.parquet").exists():
        return pasta
    ini = inicio_novo(semente) - dt.timedelta(days=1)
    sim = Simulador(perfil, semente, ini.isoformat(), falhas_por_semana, dias + 1)
    sim.executar(dias + 1, str(pasta), "parquet")
    (pasta / "meta.json").write_text(json.dumps({"perfil": perfil, "semente": semente, "inicio": ini.isoformat(),
                                                  "avaliado_desde": inicio_novo(semente).isoformat(), "dias": dias,
                                                  "falhas_por_semana": falhas_por_semana}))
    return pasta


def _mensagens(pasta: Path, casa: CasaAoVivo) -> pd.DataFrame:
    df = pd.read_parquet(pasta / "telemetria.parquet", columns=["ts", "medidor_id", "canal", "potencia_w", "energia_wh"])
    med = df["medidor_id"].astype(str)
    df["chave"] = np.where(med.isin(casa.multi), med + "_c" + df["canal"].astype(str), med)
    return df.sort_values("ts", kind="stable").reset_index(drop=True)[["ts", "chave", "potencia_w", "energia_wh"]]


def perturbar(df: pd.DataFrame, cenario: str, geral: list[str], rng: np.random.Generator) -> pd.DataFrame:
    df = df.copy()
    if cenario.startswith("perda_"):
        p = int(cenario.split("_")[1]) / 100
        return df[rng.random(len(df)) >= p].reset_index(drop=True)
    if cenario == "medidor_off":
        proprios = sorted(set(df["chave"]) - set(geral))
        t0, t1 = int(df["ts"].min()), int(df["ts"].max())
        mudo = np.zeros(len(df), dtype=bool)
        semana = 7 * 86400
        for k, ini in enumerate(range(t0 + 86400, t1, semana)):
            c = proprios[k % len(proprios)]
            a = ini + int(rng.integers(0, semana - 6 * 3600))
            mudo |= (df["chave"].to_numpy() == c) & (df["ts"].to_numpy() >= a) & (df["ts"].to_numpy() < a + 6 * 3600)
        return df[~mudo].reset_index(drop=True)
    if cenario == "fora_de_ordem":
        idx = np.arange(len(df))
        trocar = np.flatnonzero(rng.random(len(df) - 1) < 0.05)
        trocar = trocar[np.diff(np.r_[-2, trocar]) > 1]                     # sem trocas sobrepostas
        idx[trocar], idx[trocar + 1] = idx[trocar + 1], idx[trocar].copy()
        return df.iloc[idx].reset_index(drop=True)
    if cenario == "duplicadas":
        dup = df[rng.random(len(df)) < 0.05]
        return pd.concat([df, dup]).sort_index(kind="stable").reset_index(drop=True)
    if cenario == "deriva_todos_5":
        df[["potencia_w", "energia_wh"]] *= 1.05
        return df
    if cenario == "deriva_geral_5":
        m = df["chave"].isin(geral)
        df.loc[m, ["potencia_w", "energia_wh"]] *= 1.05
        return df
    return df


def _eventos(pasta: Path, geral: list[str], desde: int) -> tuple[list, pd.DataFrame]:
    g = pd.read_csv(pasta / "gabarito_falhas.csv")
    rede = g[~g["alerta_de_aparelho"].astype(bool)].copy()
    ap = g[g["alerta_de_aparelho"].astype(bool) & g["efetiva"].astype(bool)].copy()
    ap["ini"], ap["fim"] = av._epoch(ap["efeito_inicio"]), av._epoch(ap["efeito_fim"])
    rede["ini"], rede["fim"] = av._epoch(rede["efeito_inicio"]), av._epoch(rede["efeito_fim"])
    evs = []
    for fid, gr in ap.groupby("falha_id", sort=True):
        if gr["ini"].min() < desde:
            continue
        cd = gr["canal_direto"].iloc[0]
        cd = None if pd.isna(cd) else str(cd)
        evs.append(av.Evento(fid, gr["tipo"].iloc[0], gr["alvo"].iloc[0], cd, int(gr["ini"].min()), int(gr["fim"].max()),
                             frozenset(set(geral) | {"residuo"} | ({cd} if cd else set()))))
    return evs, rede[rede["ini"] >= desde]


def _chave_alerta(a: dict, casa: CasaAoVivo) -> str:
    if a["medidor_id"] == "residuo":
        return "residuo"
    return casa.chave(a["medidor_id"], a["canal"] or 1)


def rodar_cenario(pacote: Path, pasta: Path, cenario: str, semente_perturbacao: int = 0) -> dict:
    casa = CasaAoVivo(pacote, ORC.get(cenario, None))
    meta = json.loads((pasta / "meta.json").read_text())
    desde = int(dt.datetime.fromisoformat(meta["avaliado_desde"]).timestamp()) + 3 * 3600
    df = perturbar(_mensagens(pasta, casa), cenario, casa.geral, np.random.default_rng(semente_perturbacao))
    ts, ch = df["ts"].to_numpy(np.int64), df["chave"].to_numpy()
    p, e = df["potencia_w"].to_numpy(np.float64), df["energia_wh"].to_numpy(np.float64)
    alertas = []
    t0 = time.perf_counter()
    for i in range(len(df)):
        alertas += casa.recebe_chave(ch[i], int(ts[i]), float(p[i]), float(e[i]))
    alertas += casa.finalizar(int(ts[-1]) + 60)
    seg = time.perf_counter() - t0
    evs, rede = _eventos(pasta, casa.geral, desde)
    al = pd.DataFrame([{"canal": _chave_alerta(a, casa), "ini": int(dt.datetime.fromisoformat(a["ts"]).timestamp()),
                        "estagio": a["estagio"], "score": a["score"]} for a in alertas])
    if len(al):
        al = al[al["ini"] >= desde].reset_index(drop=True)
        al["fim"] = al["ini"]
    else:
        al = pd.DataFrame(columns=["canal", "ini", "fim", "estagio", "score"])
    dias = (int(ts[-1]) - desde) / 86400
    r = av.ponto(al, evs, dias)
    sil = [(a, b) for a, b in casa.silencios if b >= desde]
    faltas_ok = int(sum(any(a <= f.fim + 300 and b >= f.ini for a, b in sil) for f in rede.itertuples()))
    sem_falta = int(sum(not any(a <= f.fim + 300 and b >= f.ini for f in rede.itertuples()) for a, b in sil))
    durante_falta = int(sum(((al["ini"] >= f.ini) & (al["ini"] <= f.fim + 60 * av.RECUPERACAO_MIN)).sum()
                            for f in rede.itertuples())) if len(al) else 0
    det = r["_det"]
    eventos = [{"falha_id": ev.falha_id, "tipo": ev.tipo, "alvo": ev.alvo, "canal_direto": ev.canal_direto,
                "detectado": d[0], "atraso_min": d[1], "localizado": d[2], "canais_alerta": d[3]}
               for ev, d in zip(evs, det)]
    s = casa.stats
    n = max(s["minutos"], 1)
    estagios = al["estagio"].value_counts().to_dict() if len(al) else {}
    atrasos = [d[1] for d in det if d[0]]
    return {"perfil": meta["perfil"], "semente": meta["semente"], "cenario": cenario, "orcamento": casa.params.orcamento,
            "mensagens": int(len(df)), "fora_de_ordem": s["fora_de_ordem"], "dias": round(dias, 2),
            "eventos": len(evs), "detectados": int(sum(d[0] for d in det)), "alertas": int(len(al)),
            "alertas_fp": r["alertas_fp"], "precisao": r["precisao"], "revocacao": r["revocacao"], "f1": r["f1"],
            "fp_por_dia": r["fp_por_dia"], "atraso_mediana_min": float(np.median(atrasos)) if atrasos else None,
            "localizados": int(sum(d[2] for d in det)), "com_medidor_proprio": int(sum(ev.canal_direto is not None for ev in evs)),
            "faltas": int(len(rede)), "faltas_reconhecidas": faltas_ok, "silencios_sem_falta": sem_falta, "alertas_em_falta": durante_falta,
            "escalados_pct": 100 * s["escaladas"] / max(s["decisoes"], 1), "ms_por_minuto": 1e3 * seg / n,
            "alertas_por_estagio": estagios, "_eventos": eventos}


def rodar_casa(pacotes: Path, perfil: str, semente: int, dias: int, saida: Path, cenarios=CENARIOS, log=print):
    pasta = gerar(perfil, semente, dias, Path(saida) / "dados" / f"{perfil}_s{semente}")
    out = Path(saida) / "resultados"
    out.mkdir(parents=True, exist_ok=True)
    for c in cenarios:
        f = out / f"{perfil}_s{semente}__{c}.json"
        if f.exists():
            continue
        r = rodar_cenario(Path(pacotes) / f"{perfil}_s{semente}", pasta, c, semente_perturbacao=semente)
        f.write_text(json.dumps(r, ensure_ascii=False, default=lambda x: None if x != x else float(x)))
        log(f"[{perfil} s{semente}] {c:15s} eventos={r['eventos']:3d} detectados={r['detectados']:3d} "
            f"F1={r['f1']:.3f} FP/dia={r['fp_por_dia']:.2f} escalados={r['escalados_pct']:.1f}% "
            f"ms/min={r['ms_por_minuto']:.2f}")


def rodar_casa_isolada(args) -> str:
    import os
    os.environ["OMP_NUM_THREADS"] = "1"
    t = time.perf_counter()
    rodar_casa(*args, log=lambda m: print(m, flush=True))
    return f"{args[1]} s{args[2]} concluída em {(time.perf_counter() - t) / 60:.1f} min"


def consolidar(saida: Path) -> dict[str, pd.DataFrame]:
    saida = Path(saida)
    linhas, evs = [], []
    for f in sorted((saida / "resultados").glob("*.json")):
        r = json.loads(f.read_text())
        for e in r.pop("_eventos"):
            evs.append({**e, "perfil": r["perfil"], "semente": r["semente"], "cenario": r["cenario"]})
        r["alertas_por_estagio"] = json.dumps(r["alertas_por_estagio"])
        linhas.append(r)
    df = pd.DataFrame(linhas)
    ev = pd.DataFrame(evs)
    soma = df.groupby("cenario")[["eventos", "detectados", "alertas", "alertas_fp", "dias", "faltas",
                                  "faltas_reconhecidas", "silencios_sem_falta", "alertas_em_falta", "localizados", "com_medidor_proprio"]].sum()
    soma["revocacao"] = soma["detectados"] / soma["eventos"]
    soma["precisao"] = soma["detectados"] / (soma["detectados"] + soma["alertas_fp"])
    soma["f1"] = 2 * soma["precisao"] * soma["revocacao"] / (soma["precisao"] + soma["revocacao"])
    soma["fp_por_dia"] = soma["alertas_fp"] / soma["dias"]
    soma = soma.join(df.groupby("cenario")[["f1", "escalados_pct", "ms_por_minuto", "atraso_mediana_min"]]
                     .mean().add_suffix("_media_casas"))
    por_perfil = df.groupby(["cenario", "perfil"])[["eventos", "detectados", "alertas_fp", "dias"]].sum()
    por_perfil["revocacao"] = por_perfil["detectados"] / por_perfil["eventos"]
    por_perfil["fp_por_dia"] = por_perfil["alertas_fp"] / por_perfil["dias"]
    tipo = ev.groupby(["cenario", "tipo"]).agg(eventos=("detectado", "size"), detectados=("detectado", "sum"),
                                               atraso_mediana_min=("atraso_min", "median")).reset_index()
    tipo["revocacao"] = tipo["detectados"] / tipo["eventos"]
    alvo = ev[ev["cenario"] == "limpo_b5"].groupby(["perfil", "alvo", "tipo"]).agg(
        eventos=("detectado", "size"), detectados=("detectado", "sum")).reset_index()
    df.to_csv(saida / "tabela_campanha_por_casa.csv", index=False)
    soma.reset_index().to_csv(saida / "tabela_campanha.csv", index=False)
    por_perfil.reset_index().to_csv(saida / "tabela_campanha_perfil.csv", index=False)
    tipo.to_csv(saida / "tabela_campanha_tipo.csv", index=False)
    alvo.to_csv(saida / "tabela_campanha_aparelho.csv", index=False)
    return {"cenario": soma, "perfil": por_perfil, "tipo": tipo, "aparelho": alvo, "por_casa": df}
