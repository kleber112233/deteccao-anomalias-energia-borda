"""Confere se o Raspberry Pi está pronto para a etapa 2 do TCC.

Uso (no Pi, com o ambiente virtual ativado):
    python conferir_pi.py                      # sistema, pacotes e broker local
    python conferir_pi.py --segundos 30        # escuta a casa por 30 s
    python conferir_pi.py --broker 192.168.0.50

Não altera nada no sistema; só lê e mostra.
"""
from __future__ import annotations

import argparse
import base64
import importlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

OBRIGATORIOS = {"ts", "medidor_id", "canal", "potencia_w", "energia_wh"}        # docs/CONTRATO_MQTT.md
PROIBIDOS = {"anomalia", "falha_id", "falha_tipo", "canal_direto", "gabarito", "rotulo", "falha"}
PACOTES = [("paho.mqtt", "paho-mqtt", True), ("numpy", "numpy", True), ("sklearn", "scikit-learn", True),
           ("onnxruntime", "onnxruntime", True), ("psutil", "psutil", True), ("pandas", "pandas", True),
           ("pyarrow", "pyarrow", True), ("httpx", "httpx", True), ("ai_edge_litert", "ai-edge-litert", False)]
# modelo ONNX mínimo (y = x·[2,3] + 1), só para provar que o runtime executa neste processador
MODELO_TESTE = ("CAc6eAoRCgF4CgFXEgFtIgZNYXRNdWwKDgoBbQoBYhIBeSIDQWRkEgV0ZXN0ZSoTCAIIARABQgFXSggAAABAAABAQCoNCAEQAUIBYkoE"
                "AACAP1oTCgF4Eg4KDAgBEggKAggBCgIIAmITCgF5Eg4KDAgBEggKAggBCgIIAUIECgAQDQ==")

pendencias: list[str] = []


def cmd(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def ler(caminho: str) -> str:
    try:
        return Path(caminho).read_text(errors="ignore").strip("\x00\n ")
    except Exception:
        return ""


def linha(rotulo: str, valor: str, ok: bool | None = None, pendencia: str | None = None) -> None:
    marca = {True: "ok ", False: "!! ", None: "   "}[ok]
    print(f"  {marca}{rotulo:<22}{valor}")
    if ok is False:
        pendencias.append(pendencia or f"{rotulo}: {valor}")


def sistema() -> None:
    print("\n1. Sistema")
    so = next((l.split("=", 1)[1].strip('"') for l in ler("/etc/os-release").splitlines() if l.startswith("PRETTY_NAME=")), "?")
    arq = platform.machine()
    linha("Placa", ler("/proc/device-tree/model") or "não é um Raspberry Pi (ou não foi possível ler)")
    linha("Sistema", so)
    linha("Arquitetura", arq, arq == "aarch64", "o sistema não é de 64 bits (aarch64): regrave o cartão com a versão 64-bit")
    linha("Python", platform.python_version(), sys.version_info >= (3, 11), "Python abaixo de 3.11")
    linha("Ambiente virtual", sys.prefix, sys.prefix != sys.base_prefix, "rode com o ambiente virtual ativado (source .venv/bin/activate)")
    mem = next((int(l.split()[1]) // 1024 for l in ler("/proc/meminfo").splitlines() if l.startswith("MemTotal")), 0)
    linha("Memória", f"{mem} MB")
    linha("Página de memória", f"{os.sysconf('SC_PAGE_SIZE') // 1024} kB")
    fuso = cmd("timedatectl", "show", "-p", "Timezone", "--value")
    linha("Fuso horário", fuso or "?", fuso == "America/Sao_Paulo" if fuso else None, "fuso diferente de America/Sao_Paulo")
    ntp = cmd("timedatectl", "show", "-p", "NTPSynchronized", "--value")
    linha("Relógio sincronizado", ntp or "?", ntp == "yes" if ntp else None, "relógio sem sincronismo (NTP); a latência do E5 depende disso")


def saude() -> None:
    print("\n2. Saúde da placa")
    t = ler("/sys/class/thermal/thermal_zone0/temp")
    if t.isdigit():
        c = int(t) / 1000
        linha("Temperatura", f"{c:.1f} °C", c < 70, "temperatura acima de 70 °C em repouso: falta dissipador ou ventoinha")
    else:
        linha("Temperatura", "não foi possível ler")
    th = cmd("vcgencmd", "get_throttled")
    if th:
        linha("Limitação (throttled)", th, th.endswith("=0x0"), f"{th}: houve subtensão ou superaquecimento desde a partida (fonte fraca ou falta de refrigeração)")
    else:
        linha("Limitação (throttled)", "vcgencmd não disponível")
    gov = ler("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    linha("Governador da CPU", gov or "?")
    if gov and gov != "performance":
        print("       (para os experimentos E3/E4, fixe em 'performance'; ver PREPARO_PI.md)")


def pacotes() -> None:
    print("\n3. Pacotes Python")
    for modulo, nome, obrigatorio in PACOTES:
        try:
            m = importlib.import_module(modulo)
            versao = getattr(m, "__version__", None)
            if versao is None:
                from importlib.metadata import version
                versao = version(nome)
            linha(nome, str(versao), True)
        except Exception as e:
            if obrigatorio:
                linha(nome, f"faltando ({type(e).__name__})", False, f"instalar {nome} (pip install -r requirements-pi.txt)")
            else:
                linha(nome, "não instalado (opcional)")


def inferencia() -> None:
    print("\n4. Inferência (teste rápido, sem relação com os modelos do TCC)")
    try:
        import numpy as np
        import onnxruntime as ort
        op = ort.SessionOptions()
        op.intra_op_num_threads = 1
        s = ort.InferenceSession(base64.b64decode(MODELO_TESTE), op, providers=["CPUExecutionProvider"])
        y = s.run(None, {"x": np.array([[1, 1]], dtype=np.float32)})[0]
        linha("ONNX Runtime", f"executou (saída {float(y[0, 0]):g}, esperado 6)", abs(float(y[0, 0]) - 6) < 1e-6, "ONNX Runtime devolveu resultado errado")
    except Exception as e:
        linha("ONNX Runtime", f"falhou: {type(e).__name__}: {e}", False, "ONNX Runtime não executa")
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
        rng = np.random.default_rng(0)
        x = rng.normal(size=(2000, 8)).astype(np.float32)
        modelo = IsolationForest(n_estimators=100, random_state=0).fit(x)
        t0 = time.perf_counter()
        for i in range(100):
            modelo.decision_function(x[i:i + 1])
        ms = (time.perf_counter() - t0) / 100 * 1000
        linha("Isolation Forest", f"{ms:.1f} ms por amostra (scikit-learn, 100 árvores)", True)
    except Exception as e:
        linha("Isolation Forest", f"falhou: {type(e).__name__}: {e}", False, "scikit-learn não executa")


def broker(host: str, porta: int, segundos: int) -> None:
    print(f"\n5. Broker MQTT em {host}:{porta} (escutando {segundos} s)")
    try:
        import paho.mqtt.client as mqtt
    except Exception:
        linha("paho-mqtt", "faltando", False, "instalar paho-mqtt")
        return
    est = dict(conectado=False, n=0, canais=set(), casas=set(), invalidas=0, vazou=set())

    def ao_conectar(cli, userdata, flags, codigo, props=None):
        est["conectado"] = True
        cli.subscribe("casa/+/+/+/telemetria")

    def ao_receber(cli, userdata, msg):
        est["n"] += 1
        try:
            d = json.loads(msg.payload.decode("utf-8"))
            if not OBRIGATORIOS <= set(d):
                est["invalidas"] += 1
            est["vazou"] |= PROIBIDOS & set(d)
            p = msg.topic.split("/")
            est["casas"].add(p[1])
            est["canais"].add((p[1], p[2], p[3], d.get("canal")))
        except Exception:
            est["invalidas"] += 1

    try:
        cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="conferir_pi")
    except AttributeError:                                   # paho-mqtt 1.x
        cli = mqtt.Client(client_id="conferir_pi")
    cli.on_connect, cli.on_message = ao_conectar, ao_receber
    try:
        cli.connect(host, porta, keepalive=30)
    except Exception as e:
        linha("Conexão", f"falhou: {type(e).__name__}: {e}", False, f"broker inacessível em {host}:{porta} (Mosquitto instalado e rodando?)")
        return
    cli.loop_start()
    time.sleep(segundos)
    cli.loop_stop()
    cli.disconnect()
    linha("Conexão", "conectado" if est["conectado"] else "sem resposta do broker", est["conectado"], "o broker não respondeu")
    if est["n"] == 0:
        linha("Telemetria", "nenhuma mensagem (normal se o simulador não estiver publicando agora)")
        return
    linha("Telemetria", f"{est['n']} mensagens ({est['n'] / segundos:.1f}/s), {len(est['canais'])} canais, casas: {', '.join(sorted(est['casas']))}", True)
    linha("Formato", f"{est['invalidas']} fora do contrato", est["invalidas"] == 0, "há mensagens fora do contrato MQTT")
    linha("Gabarito no MQTT", ", ".join(sorted(est["vazou"])) or "nenhum campo de gabarito", not est["vazou"], "campo de gabarito chegando pelo MQTT")


def main() -> int:
    ap = argparse.ArgumentParser(description="Confere se o Pi está pronto para a etapa 2")
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--porta", type=int, default=1883)
    ap.add_argument("--segundos", type=int, default=10)
    a = ap.parse_args()
    sistema()
    saude()
    pacotes()
    inferencia()
    broker(a.broker, a.porta, a.segundos)
    print()
    if pendencias:
        print(f"PENDÊNCIAS ({len(pendencias)}):")
        for p in pendencias:
            print("  -", p)
        return 1
    print("Tudo certo: o Pi está pronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
