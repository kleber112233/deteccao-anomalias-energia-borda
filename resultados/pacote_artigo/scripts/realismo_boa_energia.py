"""Realismo do simulador × casa brasileira real medida (Boa Energia, Poli-USP; 29 dias de fev/mar de 2020, por hora).

    python realismo_boa_energia.py <TCC> <saida>

Compara, com a partição de TREINO (sem falha injetada) das 5 sementes de cada perfil, o medidor geral por hora:
consumo diário, forma média do dia (24 h normalizadas pela média), pico/média e variabilidade entre dias.
Ressalvas: Boa Energia é UMA casa (São Paulo, verão), valores em kVAh estimados por corrente; as casas simuladas são
3 perfis de renda em Marília, sementes começando em meses diferentes. Serve para conferir ordem de grandeza e forma,
não para "acertar" uma casa.
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

tcc, saida = Path(sys.argv[1]), Path(sys.argv[2]); saida.mkdir(parents=True, exist_ok=True)
be = pd.read_csv(tcc / "dados_reais/boa_energia/BoaEnergia.csv")
be["dia"] = pd.to_datetime(be["data"], format="%m/%d/%Y")   # o README diz DD/MM, mas o arquivo está em M/D/AAAA ("2/13/2020")
real = be.pivot_table(index="dia", columns="horario", values="kwh_total").dropna()
partes = {"total": "kwh_total", "chuveiro": "chuveiro", "ar-condicionado": "arcond"}
real_partes = {k: be[v].sum() / be["kwh_total"].sum() for k, v in partes.items() if v != "kwh_total"}

def horario_sim(pasta):
    df = pd.read_parquet(pasta / "treino.parquet", columns=["ts", "medidor_id", "canal", "energia_wh"])
    g = df[df["medidor_id"] == "q"].sort_values("ts")
    out = []
    for c, gc in g.groupby("canal"):
        e = gc.set_index(pd.to_datetime(gc["ts"], unit="s", utc=True).dt.tz_convert("America/Sao_Paulo"))["energia_wh"]
        h = e.resample("1h").last().ffill().diff().clip(lower=0) / 1000.0
        out.append(h)
    h = pd.concat(out, axis=1).sum(axis=1).iloc[1:]
    t = h.to_frame("kwh"); t["dia"] = t.index.normalize().tz_localize(None); t["hora"] = t.index.hour
    p = t.pivot_table(index="dia", columns="hora", values="kwh")
    return p[p.notna().all(axis=1)].iloc[1:-1]

def metricas(p):
    diario = p.sum(axis=1)
    forma = p.mean() / p.mean().mean()
    return {"dias": int(len(p)), "kwh_dia_media": float(diario.mean()), "kwh_mes_30d": float(diario.mean() * 30),
            "cv_diario": float(diario.std() / diario.mean()), "pico_sobre_media_hora": float(p.mean().max() / p.mean().mean()),
            "hora_do_pico": int(p.mean().idxmax()), "fracao_noite_18_23h": float(p.loc[:, 18:23].values.sum() / p.values.sum())}, forma

res, formas = {}, {}
res["Boa Energia (real)"], formas["Boa Energia (real)"] = metricas(real)
for perfil in ("perfil1", "perfil2", "perfil3"):
    ps = [horario_sim(tcc / "datasets/v1" / perfil / f"semente_{s}") for s in range(1, 6)]
    p = pd.concat(ps)
    res[perfil], formas[perfil] = metricas(p)
    res[perfil]["correlacao_forma_com_real"] = float(np.corrcoef(formas[perfil].values, formas["Boa Energia (real)"].values)[0, 1])
tab = pd.DataFrame(res).T
tab.to_csv(saida / "realismo_boa_energia.csv")
pd.DataFrame(formas).to_csv(saida / "realismo_forma_do_dia.csv")
(saida / "realismo_boa_energia.json").write_text(json.dumps({"metricas": res, "boa_energia_partes": real_partes}, indent=1, ensure_ascii=False))
print(tab.round(3).to_string()); print("partes do consumo real:", {k: round(v, 3) for k, v in real_partes.items()})
