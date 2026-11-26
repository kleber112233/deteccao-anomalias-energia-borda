"""Comparação pareada (mesma casa) entre variantes da cascata: diferença de F1 por casa, IC 95 % por bootstrap das
casas e teste de Wilcoxon pareado. Uso: python pareado.py <pasta_base> <variante_ref> <variante> ... (b = 0,05)."""
import sys
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

base, ref, outras = sys.argv[1], sys.argv[2], sys.argv[3:]
B = float(__import__("os").environ.get("ORC", "0.05"))


def ler(v, b=B):
    t = pd.read_csv(f"{base}/{v}/tabela_cascata_por_semente.csv")
    t = t[np.isclose(t.orcamento, b)].set_index(["perfil", "semente"]).sort_index()
    return t


r = ler(ref)
rng = np.random.default_rng(0)
print(f"referência: {ref} (b={B}); F1 médio {r.f1.mean():.3f}")
for v in outras:
    b = 0.0 if v.endswith("@b0") else B
    t = ler(v.replace("@b0", ""), b)
    d = (t.f1 - r.f1).dropna()
    boot = [rng.choice(d.values, len(d)).mean() for _ in range(10000)]
    try:
        p = wilcoxon(d.values).pvalue if np.any(d.values != 0) else 1.0
    except ValueError:
        p = float("nan")
    print(f"{v:28s} F1 {t.f1.mean():.3f}  Δ={d.mean():+.3f}  IC95 [{np.percentile(boot, 2.5):+.3f}, {np.percentile(boot, 97.5):+.3f}]"
          f"  melhor/igual/pior = {(d > 1e-9).sum()}/{(abs(d) <= 1e-9).sum()}/{(d < -1e-9).sum()}  Wilcoxon p={p:.3f}"
          f"  FP/dia {t.fp_por_dia.mean():.2f}")
