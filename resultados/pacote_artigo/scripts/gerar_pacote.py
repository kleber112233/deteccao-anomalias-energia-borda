"""Pacote de resultados para o artigo (etapa 3): tabelas finais e figuras de E1–E6 num lugar só.

    python gerar_pacote.py <pasta TCC> <saída>        (precisa de pandas e matplotlib)

Lê SÓ os arquivos de resultado já gravados em TCC/resultados (nada é treinado nem medido de novo). Cada tabela e
figura diz de que arquivo veio; o LEIAME do pacote diz em que seção do DIARIO está o contexto.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

TCC, OUT = Path(sys.argv[1]), Path(sys.argv[2])
R = TCC / "resultados"
TAB, FIG = OUT / "tabelas", OUT / "figuras"
TAB.mkdir(parents=True, exist_ok=True)
FIG.mkdir(parents=True, exist_ok=True)

# Paleta categórica validada (skill de visualização, ordem fixa) + texto neutro. Identidade nunca só pela cor:
# marcadores e estilos de linha diferentes (o artigo pode ser impresso em preto e branco).
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
TXT, TXT2, GRADE = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": TXT2, "axes.labelcolor": TXT, "xtick.color": TXT2,
                     "ytick.color": TXT2, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": GRADE, "grid.linewidth": 0.6, "axes.axisbelow": True, "legend.frameon": False,
                     "figure.dpi": 100, "savefig.dpi": 300, "lines.linewidth": 2})
CURTO = {"regra": "Regra\n(limiar fixo)", "if": "Isolation\nForest", "ocsvm": "OCSVM", "ae": "Autoencoder",
         "lstm_ae": "LSTM-AE"}
NOME = {"regra": "Regra (limiar fixo)", "if": "Isolation Forest", "ocsvm": "OCSVM", "ae": "Autoencoder",
        "lstm_ae": "LSTM-AE"}
MODELOS = ["regra", "if", "ocsvm", "ae", "lstm_ae"]
TIPO = {"magnitude": "Magnitude", "duracao_excessiva": "Duração excessiva", "fora_de_horario": "Fora de horário",
        "queda": "Queda", "pico": "Pico", "consumo_nao_explicado": "Consumo não explicado"}
indice: list[dict] = []


def salvar_tab(df: pd.DataFrame, nome: str, titulo: str, fonte: str, casas=3):
    df.to_csv(TAB / f"{nome}.csv", index=False)
    indice.append({"arquivo": f"tabelas/{nome}.csv", "titulo": titulo, "fonte": fonte,
                   "md": df.round(casas).to_markdown(index=False) if hasattr(df, "to_markdown") else ""})


def salvar_fig(fig, nome: str, titulo: str, fonte: str):
    fig.savefig(FIG / f"{nome}.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    indice.append({"arquivo": f"figuras/{nome}.png", "titulo": titulo, "fonte": fonte, "md": ""})


def media_dp(g: pd.DataFrame, col: str) -> str:
    return f"{g[col].mean():.3f} ± {g[col].std(ddof=1):.3f}"


# ------------------------------------------------------------------ E1a: baselines no teste (15 casas, 5 sementes)
ps = pd.read_csv(R / "baselines_v1/tabela_por_semente.csv")
linhas = []
for m in MODELOS:
    g = ps[ps["modelo"] == m]
    linhas.append({"modelo": NOME[m], "AUC-PR evento": media_dp(g, "auc_pr_evento"), "F1": media_dp(g, "f1"),
                   "precisão": media_dp(g, "precisao"), "revocação": media_dp(g, "revocacao"),
                   "FP/dia": f"{g['fp_por_dia'].mean():.2f}", "atraso mediano (min)": f"{g['atraso_mediana_min'].mean():.1f}",
                   "µs por janela (x86)": f"{g['us_por_janela'].median():.2f}"})
salvar_tab(pd.DataFrame(linhas), "T1_baselines_teste",
           "E1 — baselines no teste: média ± desvio-padrão das 15 casas (3 perfis × 5 sementes)",
           "resultados/baselines_v1/tabela_por_semente.csv (DIARIO do detector, seção H)")
pm = pd.read_csv(R / "baselines_v1/tabela_perfil_modelo.csv")
t = pm.pivot_table(index="modelo", columns="perfil", values="auc_pr_evento_mean").reindex(MODELOS)
t.index = [NOME[m] for m in t.index]
salvar_tab(t.reset_index().rename(columns={"index": "modelo"}), "T1b_baselines_auc_por_perfil",
           "E1 — AUC-PR por evento no teste, por perfil (média das 5 sementes)", "resultados/baselines_v1/tabela_perfil_modelo.csv")
bt = pd.read_csv(R / "baselines_v1/tabela_por_tipo.csv").groupby(["modelo", "tipo"])[["eventos", "detectados"]].sum()
bt = bt.reset_index()
tt = bt.assign(v=bt["detectados"].astype(int).astype(str) + "/" + bt["eventos"].astype(int).astype(str)).pivot(
    index="tipo", columns="modelo", values="v")[MODELOS]
tt.columns = [NOME[m] for m in tt.columns]
tt.index = [TIPO.get(i, i) for i in tt.index]
salvar_tab(tt.reset_index().rename(columns={"index": "tipo de falha"}), "T1c_baselines_por_tipo",
           "E1 — falhas detectadas / falhas no teste, por tipo e modelo (15 casas somadas)",
           "resultados/baselines_v1/tabela_por_tipo.csv")

fig, ax = plt.subplots(figsize=(6.2, 2.8))
vals = [ps[ps["modelo"] == m]["auc_pr_evento"] for m in MODELOS]
mu, dp = [v.mean() for v in vals], [v.std(ddof=1) for v in vals]
ax.bar(range(5), mu, width=0.6, color=C[0], yerr=dp, capsize=3, error_kw={"ecolor": TXT2, "lw": 1})
for i, v in enumerate(mu):
    ax.text(i, v + dp[i] + 0.02, f"{v:.2f}", ha="center", va="bottom", color=TXT, fontsize=8)
ax.set_xticks(range(5), [CURTO[m] for m in MODELOS])
ax.set_ylabel("AUC-PR por evento")
ax.set_ylim(0, max(np.add(mu, dp)) * 1.25)
ax.set_title("E1 — Qualidade dos baselines no teste (média ± dp, 15 casas)", loc="left", color=TXT, fontsize=10)
salvar_fig(fig, "F1_baselines_auc", "E1 — AUC-PR por evento dos cinco baselines no teste",
           "resultados/baselines_v1/tabela_por_semente.csv")

# ------------------------------------------------------------------ E1b: cascata (orçamento de escalada)
ca = pd.read_csv(R / "cascata_v1/tabela_cascata.csv")
cat = ca[ca["perfil"] == "todos"].sort_values("orcamento")
tab = pd.DataFrame({"orçamento (% escalado)": (100 * cat["orcamento"]).round(0).astype(int),
                    "escalados no teste (%)": (100 * cat["escalados_mean"]).round(1),
                    "F1": cat["f1_mean"].map(lambda v: f"{v:.3f}") + " ± " + cat["f1_std"].map(lambda v: f"{v:.3f}"),
                    "AUC-PR evento": cat["auc_pr_evento_mean"].round(3), "FP/dia": cat["fp_por_dia_mean"].round(2),
                    "revocação do estágio 1": cat["revocacao_estagio1_mean"].round(3),
                    "custo relativo ao LSTM-AE sempre": cat["custo_relativo_ao_lstm_mean"].round(3)})
salvar_tab(tab, "T2_cascata_orcamentos", "E1 — cascata OCSVM + regra → LSTM-AE no teste, por orçamento (15 casas)",
           "resultados/cascata_v1/tabela_cascata.csv (DIARIO, seção I)")
fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.7))
x = 100 * cat["orcamento"].values
for ax, col, rot in ((axs[0], "f1_mean", "F1 (média das 15 casas)"), (axs[1], "custo_relativo_ao_lstm_mean",
                                                                     "custo relativo ao LSTM-AE sempre ligado")):
    ax.plot(x, cat[col].values, color=C[0], marker="o", markersize=5)
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xticks([0, 1, 2, 5, 10, 20, 50, 100], ["0", "1", "2", "5", "10", "20", "50", "100"])
    ax.set_xlabel("orçamento de escalada (% dos minutos-canal)")
    ax.set_ylabel(rot)
axs[0].set_ylim(0, 0.6)
axs[0].set_title("Qualidade quase não muda", loc="left", color=TXT, fontsize=10)
axs[1].set_title("Custo cai com o orçamento", loc="left", color=TXT, fontsize=10)
salvar_fig(fig, "F2_cascata_orcamento", "E1 — F1 e custo da cascata em função do orçamento de escalada",
           "resultados/cascata_v1/tabela_cascata.csv")

# ------------------------------------------------------------------ E1c: arquitetura (variantes) nos dados novos
var = [("oficial_ocsvm_regra_lstm", "OCSVM + regra → LSTM-AE (oficial)"), ("ocsvm_regra_ae", "OCSVM + regra → AE"),
       ("ocsvm_sem_regra", "OCSVM → LSTM-AE (sem regra)"), ("if_mais_regra", "IF + regra → LSTM-AE"),
       ("plano_original_if", "IF → LSTM-AE (plano original)")]
lin = []
for d, nome in var:
    for base, rot in ((R / "cascata_exploratoria", "teste (já usado)"), (R / "cascata_campanha", "28 dias novos")):
        dd = "oficial" if (base.name == "cascata_exploratoria" and d.startswith("oficial")) else d
        f = base / dd / "tabela_cascata_por_semente.csv"
        if not f.exists():
            continue
        s = pd.read_csv(f)
        s = s[np.isclose(s["orcamento"], 0.05)]
        lin.append({"arquitetura": nome, "dados": rot, "F1": f"{s['f1'].mean():.3f} ± {s['f1'].std(ddof=1):.3f}",
                    "revocação": round(s["revocacao"].mean(), 3), "precisão": round(s["precisao"].mean(), 3),
                    "FP/dia": round(s["fp_por_dia"].mean(), 2)})
salvar_tab(pd.DataFrame(lin), "T3_arquiteturas",
           "Análise de sensibilidade da arquitetura (orçamento 5 %): no teste (exploratório) e nos 28 dias novos",
           "resultados/cascata_exploratoria e resultados/cascata_campanha (DIARIO K6, K7; testes pareados em K7)")

# ------------------------------------------------------------------ E1d: campanha (dados novos + robustez)
cp = pd.read_csv(R / "campanha_v1/tabela_campanha.csv")
ordem = ["limpo_b5", "limpo_b0", "limpo_b100", "fora_de_ordem", "duplicadas", "medidor_off", "deriva_geral_5",
         "perda_1", "perda_5", "perda_20", "deriva_todos_5"]
rot = {"limpo_b5": "sem perturbação (orçamento 5 %)", "limpo_b0": "sem perturbação (só estágio 1)",
       "limpo_b100": "sem perturbação (LSTM-AE sempre)", "fora_de_ordem": "5 % das mensagens fora de ordem",
       "duplicadas": "5 % duplicadas", "medidor_off": "1 medidor mudo 6 h por semana",
       "deriva_geral_5": "deriva +5 % no medidor geral", "perda_1": "1 % das mensagens perdidas",
       "perda_5": "5 % perdidas", "perda_20": "20 % perdidas", "deriva_todos_5": "deriva +5 % em todos os medidores"}
cp = cp.set_index("cenario").loc[ordem].reset_index()
salvar_tab(pd.DataFrame({"cenário": cp["cenario"].map(rot), "revocação": cp["revocacao"].round(3),
                         "precisão": cp["precisao"].round(3), "F1": cp["f1"].round(3),
                         "FP/dia": cp["fp_por_dia"].round(2), "faltas reconhecidas": cp["faltas_reconhecidas"].astype(int).astype(str) + "/" + cp["faltas"].astype(int).astype(str)}),
           "T4_campanha_robustez", "Campanha com 28 dias novos por casa (15 casas, 418 dias, 423 falhas): robustez",
           "resultados/campanha_v1/tabela_campanha.csv (DIARIO K5)")
fig, ax = plt.subplots(figsize=(6.6, 3.4))
y = np.arange(len(cp))[::-1]
ax.barh(y, cp["fp_por_dia"], height=0.6, color=[C[0] if c.startswith("limpo") else C[1] for c in cp["cenario"]])
for yi, v in zip(y, cp["fp_por_dia"]):
    ax.text(v + 0.08, yi, f"{v:.2f}", va="center", color=TXT, fontsize=8)
ax.set_yticks(y, cp["cenario"].map(rot))
ax.set_xlabel("alertas falsos por dia por casa")
ax.grid(axis="y", visible=False)
ax.set_title("Robustez: perda de mensagens e deriva em todos os medidores elevam os alertas falsos",
             loc="left", color=TXT, fontsize=9.5)
ax.text(0.98, 0.96, "azul: sem perturbação\nlaranja: com perturbação", transform=ax.transAxes, ha="right", va="top",
        color=TXT2, fontsize=8)
salvar_fig(fig, "F3_campanha_robustez", "Campanha — alertas falsos por dia em cada perturbação (azul: sem perturbação)",
           "resultados/campanha_v1/tabela_campanha.csv")

# ------------------------------------------------------------------ E2: custo no Pi 5
lin = []
for perfil in ("perfil1", "perfil3"):
    j = json.loads((R / f"e2_20261123_0912/custo_{perfil}_semente_1.json").read_text())
    for m in MODELOS:
        v = j["modelos"][m]
        lin.append({"casa": f"{perfil}_s1 ({j['canais']} canais)", "modelo": NOME[m], "mediana (µs)": round(v["us_mediana"], 1),
                    "p99 (µs)": round(v["us_p99"], 1), ".onnx por canal (kB)": v["kb_por_canal"]})
salvar_tab(pd.DataFrame(lin), "T5_e2_latencia_inferencia",
           "E2 — latência de UMA inferência no Raspberry Pi 5 (lote 1, 1 thread, 2.000 repetições, 2,4 GHz, sem throttling)",
           "resultados/e2_20261123_0912/custo_*.json (DIARIO K9)")
lin = []
for versao, pasta in (("atributos antigos", "e2_20261123_0833"), ("atributos otimizados (final)", "e2_20261123_0912")):
    for perfil in ("perfil1", "perfil3"):
        for l in (R / pasta / f"reproduzir_{perfil}_s1.txt").read_text().splitlines():
            if l.startswith("{"):
                d = json.loads(l)
                lin.append({"versão": versao, "casa": f"{perfil}_s1 ({d['canais']} canais)",
                            "orçamento (%)": int(round(100 * d["orcamento"])), "ms por minuto de casa": round(d["ms_por_minuto"], 3),
                            "atributos": round(d["ms_atributos"], 3), "estágio 1": round(d["ms_estagio1"], 3),
                            "estágio 2": round(d["ms_estagio2"], 3), "escalados (%)": round(d["escalados_pct"], 1),
                            "alertas": d["alertas"]})
e2 = pd.DataFrame(lin)
salvar_tab(e2, "T6_e2_sistema_por_minuto",
           "E2 — custo do sistema ao vivo no Pi 5 por minuto de casa (36.000 min de teste), antes e depois da otimização",
           "resultados/e2_*/reproduzir_*.txt (DIARIO K9)")
fig, ax = plt.subplots(figsize=(6.2, 2.6))
j1 = json.loads((R / "e2_20261123_0912/custo_perfil1_semente_1.json").read_text())
med = [j1["modelos"][m]["us_mediana"] for m in MODELOS]
ax.bar(range(5), med, width=0.6, color=C[0])
ax.set_yscale("log")
for i, v in enumerate(med):
    ax.text(i, v * 1.15, f"{v:,.0f} µs".replace(",", "."), ha="center", va="bottom", color=TXT, fontsize=8)
ax.set_xticks(range(5), [CURTO[m] for m in MODELOS])
ax.set_ylabel("µs por inferência (escala log)")
ax.set_ylim(5, 8000)
ax.set_title("E2 — Uma inferência no Raspberry Pi 5 (mediana)", loc="left", color=TXT, fontsize=10)
salvar_fig(fig, "F4_e2_latencia", "E2 — latência de uma inferência por modelo no Pi 5 (perfil1_s1)",
           "resultados/e2_20261123_0912/custo_perfil1_semente_1.json")

# ------------------------------------------------------------------ E3: capacidade (1ª rodada: rampa) e 2ª rodada
d1 = pd.read_csv(R / "e3_20261123_1012/analise/e3_degraus.csv")
fig, ax = plt.subplots(figsize=(6.2, 3.0))
for i, (rd, nome, mk, ls) in enumerate((("E3_b1", "LSTM-AE sempre (100 %)", "o", "-"),
                                        ("E3_b005", "cascata, orçamento 5 %*", "s", "--"),
                                        ("E3_b0", "só estágio 1 (0 %)", "^", ":"))):
    g = d1[d1["rodada"] == rd]
    ax.plot(g["casas"], g["atraso_pior_s"], color=C[[1, 0, 2][i]], marker=mk, markersize=5, linestyle=ls, label=nome)
ax.axhline(30, color=TXT2, lw=1, ls="--")
ax.text(1400, 31, "limite de 30 s", color=TXT2, fontsize=8)
ax.set_xlabel("casas perfil3 simultâneas (32 canais cada)")
ax.set_ylabel("pior atraso de alerta (s)")
ax.legend(loc="upper left")
ax.set_title("E3 — Atraso na virada do minuto ≈ nº de casas × custo por casa", loc="left", color=TXT, fontsize=10)
salvar_fig(fig, "F5_e3_atraso_por_casas", "E3 (1ª rodada, rampa 50→3.000 casas): pior atraso de alerta por nº de casas. "
           "*Nesta rodada o gerador desalinhava os canais e o orçamento de 5 % escalou 64 % (DIARIO K11)",
           "resultados/e3_20261123_1012/analise/e3_degraus.csv")
salvar_tab(d1[["rodada", "casas", "canais", "msg_s_enviadas", "msg_s_processadas", "fracao_processada", "atraso_pior_s",
               "escalados_pct", "ms_por_minuto_casa", "cpu_detector_media", "mem_mb_max"]],
           "T7_e3_rampa", "E3 — 1ª rodada (rampa, uma mensagem por canal a cada 10 s), por degrau",
           "resultados/e3_20261123_1012/analise/e3_degraus.csv (DIARIO K11)")
lin = []
for pasta, rd, rot_ in (("e3_20261123_1331", "E3f_b1", "LSTM-AE sempre (100 %), 2,4 GHz"),
                        ("e3_20261123_1331", "E3f_b005", "cascata 5 %, 2,4 GHz"),
                        ("e3_20261123_1552", "E4f_ctrl", "controlador (limite 30 s), 2,4 GHz"),
                        ("e3_20261123_1632", "E6_b1", "LSTM-AE sempre (100 %), 1,5 GHz"),
                        ("e3_20261123_1632", "E6_ctrl", "controlador (limite 30 s), 1,5 GHz")):
    g = pd.read_csv(R / pasta / "analise/e3_degraus.csv")
    g = g[g["rodada"] == rd]
    r = g[g["tipo"] == "regime_5min_final"]
    r = r if len(r) else g[g["tipo"] == "degrau"]
    r = r.iloc[0]
    lin.append({"configuração": rot_, "trecho": r["tipo"], "processado (%)": round(100 * r["fracao_processada"], 1),
                "fila (fim − início)": int(r["fila_fim_menos_inicio"]), "pior atraso (s)": round(r["atraso_pior_s"], 1),
                "escalados (%)": round(r["escalados_pct"], 1), "ms por min-casa": round(r["ms_por_minuto_casa"], 2),
                "CPU detector (%)": r["cpu_detector_media"], "orçamentos": r["orcamentos_usados"],
                "memória (MB)": r["mem_mb_max"]})
salvar_tab(pd.DataFrame(lin), "T8_e3_e4_e6_4000_casas",
           "E3/E4/E6 — 4.000 casas perfil3 fiéis (128 mil canais, ~3.080 msg/s): sustenta? (últimos 5 min de cada rodada)",
           "resultados/e3_20261123_1331, _1552, _1632 /analise/e3_degraus.csv (DIARIO K13, K14, K16)")

# ------------------------------------------------------------------ E4/E6: trajetória do controlador
fig, axs = plt.subplots(2, 1, figsize=(6.4, 4.6), sharex=True)
for pasta, rot_, cor, mk, ls in (("e3_20261123_1552", "Pi 5 a 2,4 GHz (E4)", C[0], "o", "-"),
                                 ("e3_20261123_1632", "Pi 5 limitado a 1,5 GHz (E6)", C[1], "s", "--")):
    t = pd.read_csv(R / pasta / "analise/e4_trajetoria.csv")
    t["min"] = t["minuto"].astype(int)
    g = t.groupby("min").agg(orc=("orcamento", "min"), pior=("exc_max", "max")).iloc[:-1]
    axs[0].step(g.index, 100 * g["orc"], where="post", color=cor, linestyle=ls, label=rot_)
    axs[1].plot(g.index, g["pior"], color=cor, marker=mk, markersize=3.5, linestyle=ls, label=rot_)
axs[0].set_yscale("symlog", linthresh=1)
axs[0].set_yticks([0, 1, 2, 5, 10, 20, 50, 100], ["0", "1", "2", "5", "10", "20", "50", "100"])
axs[0].set_ylabel("orçamento (%)")
axs[0].legend(loc="upper right")
axs[0].set_title("E4/E6 — O controlador escolhe sozinho o orçamento que cabe no hardware", loc="left", color=TXT, fontsize=10)
axs[1].axhline(30, color=TXT2, lw=1, ls="--")
axs[1].text(12, 36, "limite de 30 s", color=TXT2, fontsize=8)
axs[1].set_ylabel("pior atraso no minuto (s)")
axs[1].set_xlabel("minutos desde o início (4.000 casas perfil3)")
salvar_fig(fig, "F6_e4_e6_controlador", "E4 e E6 — trajetória do controlador de carga (orçamento e pior atraso por minuto)",
           "resultados/e3_20261123_1552 e e3_20261123_1632 /analise/e4_trajetoria.csv (DIARIO K14, K16)")

# ------------------------------------------------------------------ E5: ponta a ponta
e5 = json.loads((R / "e5_bateria_noturna/e5_resumo.json").read_text())
ev = pd.read_csv(R / "e5_bateria_noturna/e5_eventos.csv")
proprio = ev["canal_direto"].fillna("").astype(str).isin(["t1", "t2", "t3", "t4"])
salvar_tab(pd.DataFrame([
    {"medida": "falhas injetadas pelo painel", "valor": e5["eventos"]},
    {"medida": "dias simulados (120×)", "valor": e5["dias_simulados"]},
    {"medida": "revocação (todas)", "valor": round(e5["revocacao"], 3)},
    {"medida": "revocação — aparelhos com medidor próprio", "valor": f"{int(ev[proprio]['detectado'].sum())}/{int(proprio.sum())}"},
    {"medida": "revocação — sem medidor próprio / consumo não explicado", "valor": f"{int(ev[~proprio]['detectado'].sum())}/{int((~proprio).sum())}"},
    {"medida": "precisão", "valor": round(e5["precisao"], 3)},
    {"medida": "alertas falsos por dia", "valor": round(e5["fp_por_dia"], 3)},
    {"medida": "atraso mediano de detecção (min simulados)", "valor": round(e5["atraso_sim_mediana_min"], 1)},
    {"medida": "latência do sistema, mediana (s reais)", "valor": round(e5["latencia_sistema_mediana_s"], 2)},
    {"medida": "faltas de energia / alertas falsos durante elas", "valor": f"{e5['faltas_de_energia']} / {e5['falsos_durante_falta']}"}]),
    "T9_e5_ponta_a_ponta", "E5 — sessão ao vivo painel → MQTT → Pi 5 → painel (perfil1_s1, orçamento 5 %)",
    "resultados/e5_bateria_noturna (DIARIO K8)")

# ------------------------------------------------------------------ Realismo do simulador × casa real
real = pd.read_csv(OUT / "tabelas/realismo_boa_energia.csv", index_col=0) if (OUT / "tabelas/realismo_boa_energia.csv").exists() else None
forma = OUT / "tabelas/realismo_forma_do_dia.csv"
if real is not None and forma.exists():
    f = pd.read_csv(forma, index_col=0)
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    estilos = {"Boa Energia (real)": (TXT, "o", "-", 2.4), "perfil1": (C[0], None, "--", 1.8),
               "perfil2": (C[1], None, "-.", 1.8), "perfil3": (C[2], None, ":", 1.8)}
    for col in f.columns:
        cor, mk, ls, lw = estilos[col]
        ax.plot(f.index, f[col], color=cor, marker=mk, markersize=3.5, linestyle=ls, lw=lw,
                label=col if col != "Boa Energia (real)" else "casa real (Boa Energia, SP, fev/2020)")
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlabel("hora do dia")
    ax.set_ylabel("consumo / média do dia")
    ax.legend(loc="upper left", ncol=2, fontsize=8)
    ax.set_title("Forma do dia: casa real × casas simuladas (medidor geral, por hora)", loc="left", color=TXT, fontsize=10)
    salvar_fig(fig, "F7_realismo_forma_do_dia", "Realismo — forma média do dia da casa real (Boa Energia) e dos 3 perfis",
               "tabelas/realismo_forma_do_dia.csv (scripts/realismo_boa_energia.py)")
    indice.append({"arquivo": "tabelas/realismo_boa_energia.csv",
                   "titulo": "Realismo — casa real (Boa Energia) × perfis simulados: consumo, variabilidade e forma",
                   "fonte": "dados_reais/boa_energia/BoaEnergia.csv + datasets/v1 (treino)", "md": real.round(3).reset_index().rename(columns={"index": "casa"}).to_markdown(index=False)})

(OUT / "indice.json").write_text(json.dumps([{k: v for k, v in i.items() if k != "md"} for i in indice],
                                            ensure_ascii=False, indent=1), encoding="utf-8")
md = ["# Tabelas e figuras geradas (automático)\n"]
for i in indice:
    md.append(f"## {i['titulo']}\n\nArquivo: `{i['arquivo']}` — fonte: {i['fonte']}\n")
    if i["md"]:
        md.append(i["md"] + "\n")
(OUT / "TABELAS_E_FIGURAS.md").write_text("\n".join(md), encoding="utf-8")
print(f"{len(indice)} itens em {OUT}")
