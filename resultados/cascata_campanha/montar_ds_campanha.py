"""Monta datasets_campanha/v1/perfilN/semente_S: treino e calibração = os oficiais (links), teste = os 28 dias novos
da campanha (telemetria.parquet), gabarito = linhas oficiais de treino/calibração + falhas da campanha como 'teste'."""
import json, os, datetime as dt
import pandas as pd
from pathlib import Path
OF = Path("datasets/v1"); CP = Path("resultados/campanha_v1/dados"); OUT = Path("datasets_campanha/v1")
for p in ("perfil1", "perfil2", "perfil3"):
    for s in range(1, 6):
        o, c, d = OF / p / f"semente_{s}", CP / f"{p}_s{s}", OUT / p / f"semente_{s}"
        d.mkdir(parents=True, exist_ok=True)
        for f in ("treino.parquet", "calibracao.parquet", "resumo.json"):
            if not (d / f).exists():
                os.symlink((o / f).resolve(), d / f)
        t = pd.read_parquet(c / "telemetria.parquet")
        t.insert(0, "particao", "teste")
        t.to_parquet(d / "teste.parquet", index=False)
        go = pd.read_csv(o / "gabarito_falhas.csv"); go = go[go.particao != "teste"]
        gc = pd.read_csv(c / "gabarito_falhas.csv"); gc["particao"] = "teste"
        gc["falha_id"] = "N" + gc["falha_id"].astype(str)
        pd.concat([go, gc[go.columns]], ignore_index=True).to_csv(d / "gabarito_falhas.csv", index=False)
        print(p, s, len(t), "mensagens;", len(gc), "falhas novas")
