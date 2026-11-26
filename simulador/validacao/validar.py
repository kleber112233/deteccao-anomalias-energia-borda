"""Validação do simulador: compara cada perfil com as metas (EPE), a curva diária esperada e a
participação por uso final (PPH, informativa). Gera gráficos e validacao.json em validacao/resultados/.

Uso:  python validacao/validar.py [--dias-por-estacao 14] [--semente 42]
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
from pathlib import Path
import numpy as np

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from casasim import Simulador  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

AZUL, LARANJA, VERDE, CINZA, TINTA, TINTA2 = "#2a78d6", "#eb6834", "#1baf7a", "#b9b8b2", "#0b0b0b", "#52514e"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#8b8a84",
                     "axes.labelcolor": TINTA2, "xtick.color": TINTA2, "ytick.color": TINTA2, "axes.grid": True, "grid.color": "#e3e2dd",
                     "grid.linewidth": 0.8, "axes.axisbelow": True, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "savefig.dpi": 160})
ESTACOES = {"verão (jan)": "2026-01-05", "outono (abr)": "2026-04-06", "inverno (jul)": "2026-07-06", "primavera (out)": "2026-10-05"}
GRUPOS = {"chuveiro": ["chuveiro_eletrico"], "geladeira_freezer": ["geladeira", "freezer"], "condicionamento": ["ar_condicionado", "ventilador", "aquecedor"],
          "iluminacao": ["lampada"], "tv_eletronicos": ["tv", "videogame", "notebook", "computador_desktop", "monitor", "roteador"]}
NOME_GRUPO = {"chuveiro": "Chuveiro", "geladeira_freezer": "Geladeira e freezer", "condicionamento": "Ar-condicionado e ventilador",
              "iluminacao": "Iluminação", "tv_eletronicos": "TV e eletrônicos", "outros": "Outros"}
NOMES = {"perfil1": "Perfil 1 (modesto)", "perfil2": "Perfil 2 (mediano)", "perfil3": "Perfil 3 (alto padrão)"}


def aneel_horaria():
    """Forma média da curva residencial (B1) de dia útil da CPFL Paulista 2023, por hora (média = 1)."""
    f = BASE.parent / "dados_reais" / "aneel_ctr" / "curvas_b1_normalizadas.json"
    if not f.exists():
        return None
    m = np.array(json.loads(f.read_text(encoding="utf-8"))["cpfl_paulista_2023"]["Dia Útil"]["media"])
    h = m.reshape(24, 4).mean(axis=1)
    return h / h.mean()


def rodar(perfil: str, dias: int, semente: int) -> dict:
    hora = np.zeros(24)
    util = np.zeros(24); n_util = [0]
    tipos: dict[str, float] = {}
    por_est, n = {}, 0
    for nome, inicio in ESTACOES.items():
        sim = Simulador(perfil, semente, inicio, faltas_naturais=False)
        def ao_dia(dia):
            h = dia.geral.reshape(24, 3600).mean(axis=1)
            hora[:] += h
            if dia.data.weekday() < 5:
                util[:] += h; n_util[0] += 1
        r = sim.executar(dias, ao_dia=ao_dia)
        por_est[nome] = r["kwh_dia_medio"]
        for t, e in r["kwh_por_tipo"].items():
            tipos[t] = tipos.get(t, 0) + e
        n += dias
    total = sum(tipos.values())
    base = float(sim.c.personas["habitos"].get("carga_base_w", 0)) * 24 * n / 1000
    grupos = {g: sum(tipos.get(t, 0) for t in ts) for g, ts in GRUPOS.items()}
    grupos["outros"] = total + base - sum(grupos.values())
    hora /= n
    util /= max(1, n_util[0])
    ref = aneel_horaria()
    r_aneel = float(np.corrcoef(util / util.mean(), ref)[0, 1]) if ref is not None else None
    jan = [float(hora[(np.arange(3) + h) % 24].mean()) for h in range(24)]
    return dict(perfil=perfil, dias=n, curva_dia_util_w=util.round(1).tolist(), correlacao_curva_cpfl=round(r_aneel, 3) if r_aneel is not None else None, kwh_mes=round((total + base) / n * 30.42, 1), kwh_dia_por_estacao=por_est, curva_horaria_w=hora.round(1).tolist(),
                janela_3h_mais_carregada=int(np.argmax(jan)), razao_pico_media=round(float(hora[18:21].mean() / hora.mean()), 2),
                participacao_pct={g: round(100 * v / (total + base), 1) for g, v in grupos.items()},
                kwh_mes_por_tipo={t: round(e / n * 30.42, 1) for t, e in sorted(tipos.items(), key=lambda x: -x[1])})


def figuras(res: dict, metas: dict, pasta: Path, semente: int) -> None:
    epe = metas["epe"]["consumo_medio_residencial_sudeste_kwh_mes"]
    # 1) consumo mensal x meta
    fig, axs = plt.subplots(1, 3, figsize=(10, 3.4))
    for ax, (p, r) in zip(axs, res.items()):
        m = metas["metas_kwh_mes"][p]
        ax.axhspan(m["min"], m["max"], color=VERDE, alpha=0.15, lw=0)
        ax.bar([0], [r["kwh_mes"]], width=0.3, color=AZUL)
        ax.axhline(epe, color=TINTA2, lw=1.2, ls="--")
        ax.text(0.47, epe, f" média Sudeste (EPE): {epe:.0f}".replace(".", ","), va="bottom", ha="right", fontsize=8.5, color=TINTA2)
        ax.text(0, r["kwh_mes"], f"{r['kwh_mes']:.0f} kWh/mês", ha="center", va="bottom", fontsize=10, color=TINTA, fontweight="bold")
        ax.text(-0.47, m["max"], f"meta EPE ({m['faixa_renda_sm']} SM): {m['min']}–{m['max']}", va="bottom", fontsize=8.5, color="#0d7a55")
        ax.set_xlim(-0.5, 0.5); ax.set_xticks([]); ax.set_ylim(0, max(m["max"], r["kwh_mes"], epe) * 1.25)
        ax.set_title(NOMES[p], fontsize=10.5, loc="left", color=TINTA); ax.grid(axis="x", visible=False)
    axs[0].set_ylabel("kWh por mês")
    fig.suptitle("Consumo mensal simulado (média de quatro estações) e meta pela EPE por faixa de renda (±25%)", fontsize=11, x=0.01, ha="left", color=TINTA)
    fig.tight_layout(); fig.savefig(pasta / "fig1_consumo_mensal.png"); plt.close(fig)
    # 2) curva diária
    fig, axs = plt.subplots(1, 3, figsize=(10, 3.2))
    for ax, (p, r) in zip(axs, res.items()):
        c = np.array(r["curva_dia_util_w"]) / 1000
        ax.axvspan(18, 21, color=LARANJA, alpha=0.10, lw=0)
        ax.step(np.arange(25), np.append(c, c[-1]), where="post", color=AZUL, lw=2, label="simulado, dia útil")
        ref = aneel_horaria()
        if ref is not None:
            cu = np.array(r["curva_dia_util_w"]) / 1000
            ax.plot(np.arange(24) + 0.5, ref * cu.mean(), color=LARANJA, lw=1.6, marker="o", ms=3, label="residências da CPFL Paulista, dia útil (ANEEL, mesma média)")
        ax.axhline(c.mean(), color=TINTA2, lw=1, ls="--")
        ax.text(0.2, c.mean(), "média do dia", fontsize=8.5, va="bottom", color=TINTA2)
        ax.text(19.5, c.max() * 1.12, "ponta\n18h–21h", fontsize=8.5, ha="center", va="top", color="#a4421c")
        ax.set_xlim(0, 24); ax.set_xticks(range(0, 25, 6)); ax.set_xticklabels([f"{h}h" for h in range(0, 25, 6)]); ax.set_ylim(0, c.max() * 1.15)
        ax.set_title(f"{NOMES[p]}\ncorrelação com a CPFL: r = {r['correlacao_curva_cpfl']:.2f}".replace(".", ","), fontsize=9.5, loc="left", color=TINTA)
        ax.set_ylim(0, max(c.max(), (ref * np.array(r["curva_dia_util_w"]).mean() / 1000).max() if ref is not None else 0) * 1.18)
    axs[0].set_ylabel("kW (média horária)")
    h_, l_ = axs[0].get_legend_handles_labels()
    fig.legend(h_, l_, loc="lower center", ncol=2, frameon=False, fontsize=8.5)
    fig.suptitle("Curva de carga do dia útil: simulador × forma real das residências da CPFL Paulista", fontsize=11, x=0.01, ha="left", color=TINTA)
    fig.tight_layout(rect=(0, 0.07, 1, 1)); fig.savefig(pasta / "fig2_curva_diaria.png"); plt.close(fig)
    # 3) uso final
    ref = metas["pph_uso_final_referencia"]["participacao_pct"]
    ordem = list(NOME_GRUPO)
    fig, axs = plt.subplots(1, 3, figsize=(10.5, 3.3), sharey=True)
    for ax, (p, r) in zip(axs, res.items()):
        v = [r["participacao_pct"][g] for g in ordem]
        y = np.arange(len(ordem))[::-1]
        ax.barh(y, v, height=0.55, color=AZUL)
        for yi, vi in zip(y, v):
            ax.text(vi + 1, yi, f"{vi:.0f}%", va="center", fontsize=9, color=TINTA)
        if p == "perfil1":
            ax.scatter([ref[g] for g in ordem], y, marker="D", s=34, color=LARANJA, zorder=3, label="PPH 2019 Sudeste (Abrahão e Souza, 2021)", edgecolor="#fcfcfb", linewidth=1)
            ax.legend(fontsize=8, frameon=False, loc="lower right")
        ax.set_yticks(y); ax.set_yticklabels([NOME_GRUPO[g] for g in ordem]); ax.set_xlim(0, max(60, max(v) + 10))
        ax.set_title(NOMES[p], fontsize=10.5, loc="left", color=TINTA); ax.grid(axis="y", visible=False); ax.set_xlabel("% do consumo")
    fig.suptitle("Participação de cada uso final no consumo simulado", fontsize=11, x=0.01, ha="left", color=TINTA)
    fig.tight_layout(); fig.savefig(pasta / "fig3_uso_final.png"); plt.close(fig)
    # 4) o que o sensor enxerga: geladeira numa tomada de 30 s
    sim = Simulador("perfil1", semente, "2026-01-05", faltas_naturais=False)
    dia = sim.simular_dia()
    real, m = dia.pot["cozinha.geladeira"], dia.mensagens["t1"]
    liga = np.flatnonzero(np.diff((real > 50).astype(int)) == 1)
    a = int(liga[len(liga) // 2]) - 240
    b = a + 900
    sel = (m["t"] >= a) & (m["t"] < b)
    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.plot(np.arange(a, b) - a, real[a:b], color=CINZA, lw=1.6, label="potência real (1 leitura por segundo)")
    ax.step(m["t"][sel] - a, m["potencia_w"][sel], where="post", color=AZUL, lw=2, label="o que a tomada envia (a cada 30 s)")
    ax.scatter(m["t"][sel] - a, m["potencia_w"][sel], color=AZUL, s=22, zorder=3, edgecolor="#fcfcfb", linewidth=1)
    pico = float(real[a:b].max())
    ax.annotate(f"pico de partida de {pico:.0f} W\ndura 1 a 2 s e não chega ao Pi", xy=(int(np.argmax(real[a:b])), pico), xytext=(330, pico * 0.8),
                fontsize=9, color=TINTA, arrowprops=dict(arrowstyle="-", color=TINTA2, lw=0.8))
    ax.set_xlabel("segundos"); ax.set_ylabel("W"); ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.set_title("Perfil 1 — geladeira medida por tomada Tuya: o pico de partida do compressor some entre duas leituras", fontsize=10.5, loc="left", color=TINTA)
    fig.tight_layout(); fig.savefig(pasta / "fig4_sensor_x_real.png"); plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias-por-estacao", type=int, default=14); ap.add_argument("--semente", type=int, default=42)
    a = ap.parse_args()
    metas = json.loads((BASE / "dados" / "metas_validacao.json").read_text(encoding="utf-8"))
    pasta = BASE / "validacao" / "resultados"
    pasta.mkdir(parents=True, exist_ok=True)
    res, ok = {}, True
    for p in ("perfil1", "perfil2", "perfil3"):
        r = rodar(p, a.dias_por_estacao, a.semente)
        m = metas["metas_kwh_mes"][p]
        r["dentro_da_meta"] = m["min"] <= r["kwh_mes"] <= m["max"]
        r["pico_no_fim_da_tarde"] = r["janela_3h_mais_carregada"] in (17, 18, 19) and r["razao_pico_media"] >= 1.5
        r["aprovado"] = r["dentro_da_meta"] and (r["pico_no_fim_da_tarde"] or p == "perfil3")
        ok &= r["aprovado"]
        res[p] = r
        print(f"{NOMES[p]:24s} {r['kwh_mes']:7.1f} kWh/mês (meta {m['min']}–{m['max']}) | janela de 3 h mais carregada começa às {r['janela_3h_mais_carregada']}h | "
              f"pico/média {r['razao_pico_media']} | r(CPFL) {r['correlacao_curva_cpfl']} | {'APROVADO' if r['aprovado'] else 'REPROVADO'}")
        print("   por estação (kWh/dia):", r["kwh_dia_por_estacao"]); print("   uso final (%):", r["participacao_pct"])
    figuras(res, metas, pasta, a.semente)
    (pasta / "validacao.json").write_text(json.dumps(dict(gerado_em=dt.date.today().isoformat(), semente=a.semente, dias_por_estacao=a.dias_por_estacao,
                                                          epe=metas["epe"], resultados=res), ensure_ascii=False, indent=1), encoding="utf-8")
    print("Figuras e validacao.json em", pasta)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
