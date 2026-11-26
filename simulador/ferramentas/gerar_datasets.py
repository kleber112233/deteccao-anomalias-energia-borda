"""Gera e congela os datasets do simulador para a parte 2 (Raspberry Pi).

Uso:
    python ferramentas/gerar_datasets.py                      # versão v1 completa (3 perfis × 5 sementes)
    python ferramentas/gerar_datasets.py --perfis perfil1 --sementes 1 --dias 14 --saida /tmp/teste

Estrutura de saída (padrão: TCC/datasets/v1/):
    manifesto.json                      versão, parâmetros, hashes do código e dos dados, contagens
    perfilN/semente_S/
        treino.parquet                  só consumo normal (nenhuma falha injetada; faltas de energia naturais podem ocorrer)
        calibracao.parquet              com falhas (para escolher limiares)
        teste.parquet                   com falhas (para medir o resultado final; não usar para ajustar nada)
        verdade_1min.parquet            potência real por minuto de cada aparelho (gabarito físico)
        gabarito_falhas.csv             uma linha por falha e por dia
        resumo.json                     kWh por aparelho e por dia, contagens

As colunas `anomalia`, `falha_id`, `falha_tipo` e `canal_direto` são o gabarito: o detector no Pi NÃO pode
usá-las como entrada. Use `casasim.datasets.carregar(..., com_rotulos=False)` para lê-las sem o gabarito.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from casasim import Simulador, __version__  # noqa: E402

VERSAO = "v1"
PADRAO = dict(perfis=["perfil1", "perfil2", "perfil3"], sementes=[1, 2, 3, 4, 5], dias=120,
              fracoes=(0.6, 0.2, 0.2), falhas_por_semana=5.0, prob_medido=0.6, inicio_base="2026-01-05", passo_inicio_dias=73)


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def hash_codigo() -> str:
    h = hashlib.sha256()
    for f in sorted((BASE / "casasim").rglob("*.py")) + [BASE / "catalogos" / "catalogo_simulador.json",
                                                         BASE / "dados" / "personas.json", BASE / "dados" / "clima_marilia_inmet.json"]:
        h.update(f.relative_to(BASE).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def gerar(perfil: str, semente: int, dias: int, inicio: dt.date, fracoes, por_semana: float, prob_medido: float, pasta: Path) -> dict:
    pasta.mkdir(parents=True, exist_ok=True)
    n_tr = int(round(dias * fracoes[0])); n_ca = int(round(dias * fracoes[1])); n_te = dias - n_tr - n_ca
    lim = {"treino": (0, n_tr), "calibracao": (n_tr, n_tr + n_ca), "teste": (n_tr + n_ca, dias)}
    sim = Simulador(perfil, semente, inicio)
    for nome in ("calibracao", "teste"):
        a, b = lim[nome]
        sim.injetor.plano_balanceado(inicio + dt.timedelta(days=a), b - a, por_semana, prob_medido, chave=nome)
    escritores: dict[str, pq.ParquetWriter] = {}
    linhas = {k: 0 for k in lim}
    verdade, gab, por_dia = None, [], []
    energia: dict[str, float] = {}
    t0 = time.time()
    for k in range(dias):
        part = "treino" if k < n_tr else "calibracao" if k < n_tr + n_ca else "teste"
        dia = sim.simular_dia()
        df = sim.telemetria(dia, rotulos=True)
        df.insert(0, "particao", part)
        df["falha_id"] = df["falha_id"].astype(str).replace("nan", ""); df["falha_tipo"] = df["falha_tipo"].astype(str).replace("nan", "")
        tab = pa.Table.from_pandas(df, preserve_index=False)
        if part not in escritores:
            escritores[part] = pq.ParquetWriter(pasta / f"{part}.parquet", tab.schema, compression="zstd")
        escritores[part].write_table(tab)
        linhas[part] += len(df)
        v = pa.Table.from_pandas(sim.verdade_minuto(dia), preserve_index=False)
        if verdade is None:
            verdade = pq.ParquetWriter(pasta / "verdade_1min.parquet", v.schema, compression="zstd")
        verdade.write_table(v)
        gab += [dict({kk: vv for kk, vv in g.items() if kk != "_ef"}, particao=part) for g in dia.gabarito]
        for i, pw in dia.pot.items():
            energia[i] = energia.get(i, 0.0) + float(pw.sum()) / 3.6e6
        por_dia.append(dict(data=dia.data.isoformat(), particao=part, kwh=round(float(dia.geral.sum()) / 3.6e6, 3),
                            tmax=round(dia.clima.tmax, 1), mensagens=len(df), linhas_anomalas=int(df["anomalia"].sum())))
    for w in escritores.values():
        w.close()
    verdade.close()
    import pandas as pd
    g = pd.DataFrame(gab)
    g.to_csv(pasta / "gabarito_falhas.csv", index=False)
    falhas = g[g["origem"] != "rede"].drop_duplicates("falha_id") if len(g) else g
    total = sum(d["kwh"] for d in por_dia)
    resumo = dict(perfil=perfil, casa=sim.c.casa, semente=semente, inicio=inicio.isoformat(), dias=dias, particoes={k: dict(dias=b - a, inicio=(inicio + dt.timedelta(days=a)).isoformat(), linhas=linhas[k]) for k, (a, b) in lim.items()},
                  canais=[dict(chave=c.chave, medidor=c.medidor, canal=c.numero, comodo=c.comodo, geral=c.geral, fase=c.fase, modelo_id=c.modelo_id,
                               firmware=c.sensor.get("firmware"), modo=c.sensor.get("modo"), intervalo_s=sim.sensores[c.chave].intervalo, aparelhos=c.instancias) for c in sim.c.canais.values()],
                  kwh_mes_equivalente=round(total / dias * 30.42, 1),
                  falhas_injetadas=int(len(falhas)), falhas_efetivas=int(falhas["efetiva"].sum()) if len(falhas) else 0,
                  falhas_por_tipo=falhas["tipo"].value_counts().to_dict() if len(falhas) else {},
                  falhas_por_particao=falhas["particao"].value_counts().to_dict() if len(falhas) else {},
                  faltas_de_energia_da_rede=int((g["origem"] == "rede").sum()) if len(g) else 0,
                  kwh_por_aparelho={k: round(v, 2) for k, v in sorted(energia.items(), key=lambda x: -x[1])},
                  por_dia=por_dia, segundos_para_gerar=round(time.time() - t0, 1))
    (pasta / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    return resumo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--perfis", nargs="+", default=PADRAO["perfis"])
    ap.add_argument("--sementes", nargs="+", type=int, default=PADRAO["sementes"])
    ap.add_argument("--dias", type=int, default=PADRAO["dias"])
    ap.add_argument("--falhas-por-semana", type=float, default=PADRAO["falhas_por_semana"])
    ap.add_argument("--saida", default=str(BASE.parent / "datasets" / VERSAO))
    ap.add_argument("--pular-existentes", action="store_true", help="não refaz perfil/semente que já tem resumo.json")
    a = ap.parse_args(argv)
    raiz = Path(a.saida)
    raiz.mkdir(parents=True, exist_ok=True)
    for perfil in a.perfis:
        for s in a.sementes:
            pasta = raiz / perfil / f"semente_{s}"
            if a.pular_existentes and (pasta / "resumo.json").exists():
                print(f"{perfil} semente {s}: já existe, pulado", flush=True)
                continue
            inicio = dt.date.fromisoformat(PADRAO["inicio_base"]) + dt.timedelta(days=PADRAO["passo_inicio_dias"] * (s - 1))
            r = gerar(perfil, s, a.dias, inicio, PADRAO["fracoes"], a.falhas_por_semana, PADRAO["prob_medido"], pasta)
            print(f"{perfil} semente {s}: {r['kwh_mes_equivalente']} kWh/mês, {sum(p['linhas'] for p in r['particoes'].values())} linhas, "
                  f"{r['falhas_injetadas']} falhas ({r['falhas_efetivas']} efetivas), {r['segundos_para_gerar']} s", flush=True)
    arquivos = []
    for f in sorted(raiz.rglob("*")):
        if f.is_file() and f.name != "manifesto.json":
            arquivos.append(dict(arquivo=f.relative_to(raiz).as_posix(), bytes=f.stat().st_size, sha256=sha256(f)))
    resumos = {f"{p.parent.name}/{p.name}": json.loads((p / "resumo.json").read_text(encoding="utf-8")) for p in sorted(raiz.glob("*/semente_*")) if (p / "resumo.json").exists()}
    manifesto = dict(versao=VERSAO, gerado_em=dt.datetime.now().isoformat(timespec="seconds"), casasim=__version__, hash_codigo_e_dados_de_entrada=hash_codigo(),
                     parametros=dict(PADRAO, dias=a.dias, falhas_por_semana=a.falhas_por_semana),
                     regras=["Treino: nenhuma falha injetada (faltas de energia naturais da rede podem ocorrer e não são anomalia de aparelho).",
                             "Calibração: escolher limiares e τ. Teste: só para o resultado final.",
                             "Colunas anomalia, falha_id, falha_tipo e canal_direto são gabarito: nunca entram no detector.",
                             "Cada semente começa num mês diferente (passo de 73 dias) para cobrir as estações."],
                     conjuntos={k: dict(kwh_mes=v["kwh_mes_equivalente"], falhas=v["falhas_injetadas"], efetivas=v["falhas_efetivas"],
                                        linhas={p: d["linhas"] for p, d in v["particoes"].items()}) for k, v in resumos.items()},
                     arquivos=arquivos, total_mb=round(sum(x["bytes"] for x in arquivos) / 1e6, 1))
    (raiz / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manifesto: {len(arquivos)} arquivos, {manifesto['total_mb']} MB", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
