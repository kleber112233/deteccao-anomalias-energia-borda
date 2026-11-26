"""E2 — custo por inferência de cada modelo (rodar NO Raspberry Pi).

    python -m detector custo --casa baselines_casa --dados semente_1 --saida e2_resultado.json

- `--casa`: pasta de UMA casa da rodada oficial (`resultados/baselines_v1/perfilN/semente_S`, com as subpastas regra,
  if, ocsvm, ae, lstm_ae, cada uma com os .onnx e o config.json, e o casa.json).
- Atributos reais: 1 dia da partição de teste, calculados com os limiares do casa.json (não treina nada).
- Para cada modelo e canal: latência de UMA inferência (lote de 1, 1 thread), repetida N vezes; mediana, p95, p99.
- Também: tamanho do .onnx, memória do processo depois de carregar tudo, e o estado do Pi antes e depois
  (governador da CPU, frequência, temperatura e `vcgencmd get_throttled`).
"""
from __future__ import annotations

import json
import platform
import subprocess
import time
from pathlib import Path

import numpy as np

MODELOS = ("regra", "if", "ocsvm", "ae", "lstm_ae")


def _ler(caminho: str) -> str | None:
    try:
        return Path(caminho).read_text().strip()
    except Exception:
        return None


def _cmd(*args) -> str | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return None


def _rss() -> int:
    """Memória residente do processo (bytes), lida de /proc (Linux) — sem depender do psutil."""
    try:
        for linha in Path("/proc/self/status").read_text().splitlines():
            if linha.startswith("VmRSS:"):
                return int(linha.split()[1]) * 1024
    except Exception:
        pass
    return 0


def estado_pi() -> dict:
    t = _ler("/sys/class/thermal/thermal_zone0/temp")
    f = _ler("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
    return {"governador": _ler("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
            "freq_mhz": int(f) / 1000 if f else None, "temp_c": int(t) / 1000 if t else None,
            "throttled": _cmd("vcgencmd", "get_throttled"), "clock_arm": _cmd("vcgencmd", "measure_clock", "arm"),
            "relogio": time.strftime("%Y-%m-%d %H:%M:%S")}


def medir(casa: str | Path, dados: str | Path, repeticoes: int = 2000, aquecimento: int = 50) -> dict:
    import onnxruntime as ort
    from .atributos import Extrator
    from .dados import carregar_telemetria
    from .experimento import janelas
    casa, dados = Path(casa), Path(dados)
    antes = estado_pi()
    info = json.loads((casa / "casa.json").read_text(encoding="utf-8"))
    ext = Extrator()
    ext.limiar_on = info["limiar_ligado_w"]
    ext.p_on_hora = info["p_ligado_por_hora"]
    tel = carregar_telemetria(dados, "teste")
    t0 = time.perf_counter()
    A = ext.transformar(tel)
    seg_atrib = time.perf_counter() - t0
    m0 = A.m0
    rss0 = _rss()
    so = ort.SessionOptions()
    so.intra_op_num_threads = 1
    so.inter_op_num_threads = 1
    res = {}
    for m in MODELOS:
        d = casa / m
        if not d.exists():
            continue
        cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        lat, tam = [], 0
        for c in cfg["canais"]:
            f = d / f"{c}.onnx"
            tam += f.stat().st_size
            sess = ort.InferenceSession(str(f), so, providers=["CPUExecutionProvider"])
            if cfg["entrada"] == "seq":
                L = cfg["canais"][c]["hiperparametros"]["L_minutos"]
                idx = np.arange(max(m0, L - 1), min(A.M, m0 + 1440))
                X = janelas(A.seq[c], L, idx).astype(np.float32)
            else:
                X = A.tab[c][m0:m0 + 1440].astype(np.float32)
            n = min(repeticoes, len(X))
            sel = np.random.default_rng(0).choice(len(X), n, replace=len(X) < n)
            for i in sel[:aquecimento]:
                sess.run(["score"], {"x": X[i:i + 1]})
            for i in sel:
                x = X[i:i + 1]
                t = time.perf_counter_ns()
                sess.run(["score"], {"x": x})
                lat.append((time.perf_counter_ns() - t) / 1000.0)
        lat = np.array(lat)
        res[m] = {"canais": len(cfg["canais"]), "inferencias": int(len(lat)), "us_mediana": float(np.median(lat)),
                  "us_p95": float(np.percentile(lat, 95)), "us_p99": float(np.percentile(lat, 99)),
                  "us_media": float(lat.mean()), "kb_total_onnx": round(tam / 1024, 1),
                  "kb_por_canal": round(tam / 1024 / len(cfg["canais"]), 1)}
    rss1 = _rss()
    depois = estado_pi()
    return {"casa": str(casa), "canais": len(A.canais), "minutos_de_atributos": int(A.M),
            "ms_atributos_por_minuto_casa_vetorizado": 1e3 * seg_atrib / max(A.M, 1), "modelos": res,
            "mb_sessoes": round((rss1 - rss0) / 2**20, 1), "mb_processo": round(rss1 / 2**20, 1),
            "maquina": platform.machine(), "python": platform.python_version(), "pi_antes": antes, "pi_depois": depois}
