"""Serviço de detecção no Raspberry Pi: assina a telemetria por MQTT, roda a cascata e publica os alertas.

    python -m detector servico --pacote pacotes/perfil1_s1 --broker localhost

- Assina `casa/{casa}/+/+/telemetria` (contrato MQTT v1.2) e publica em `casa/sistema/alertas`.
- A cada 10 s imprime: mensagens/s, minutos fechados, % de minutos-canal escalados ao LSTM-AE, alertas,
  CPU e memória do processo, temperatura da CPU e o custo médio de cada etapa por minuto.
- Grava em JSONL (`--registro`) cada alerta e cada linha de estado, para o E2–E5.

Modo de carga (E3/E4): `--carga pacotes/perfil3_s1` atende qualquer casa cujo nome comece com `--prefixo`
(padrão "carga", as casas virtuais do `python -m casasim carga`), criando uma CasaAoVivo própria para cada uma
(estado e atributos independentes) que COMPARTILHA as sessões ONNX da casa-modelo (mesmos arquivos .onnx).
Mede o atraso de cada mensagem (hora do Pi ao processar − `ts` do envio) e, com `--controlador`, ajusta o
orçamento da cascata pela carga: desce um nível quando o atraso p95 passa de `--atraso-max` s e sobe um nível depois
de 3 janelas calmas (atraso p95 < 1/4 do limite), entre 0 e o orçamento inicial, pelos orçamentos calibrados do pacote.
"""
from __future__ import annotations

import json
import signal
import sys
import threading
import time
from pathlib import Path

from datetime import datetime

from .aovivo import CasaAoVivo

NIVEIS = (0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0)   # orçamentos calibrados (os do pacote valem)


def _ts_float(ts) -> float:
    return float(ts) if isinstance(ts, (int, float)) else datetime.fromisoformat(ts).timestamp()


def _pct(v: list[float], q: float) -> float | None:
    if not v:
        return None
    v = sorted(v)
    return round(v[min(len(v) - 1, int(q * (len(v) - 1) + 0.5))], 3)

TOPICO_ALERTAS = "casa/sistema/alertas"
TOPICO_COMANDO = "casa/sistema/detector/comando"   # E3/E4: o roteiro do PC muda o orçamento, liga o controlador, zera


def _temperatura() -> float | None:
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0
    except Exception:
        return None


def _aquecer(c: CasaAoVivo):
    """SÓ PARA O E3/E4: casa virtual nasce como se já estivesse ligada há 1 h (janela do LSTM-AE cheia de zeros),
    para que o estágio 2 rode desde o 1º minuto e o custo medido seja o de casas em regime. Os scores da 1ª hora
    não valem como detecção (e os dados do gerador de carga, reenviados fora de alinhamento, também não)."""
    import numpy as np
    from .atributos import nomes_seq
    for at in c.at.values():
        zero = np.zeros(len(nomes_seq(at.geral)), np.float32)
        while len(at.seq) < at.seq.maxlen:
            at.seq.append(zero)
    c.i = c.L - 1


class _ProcSimples:
    """Substituto mínimo do psutil.Process (CPU do processo por os.times, memória por /proc)."""
    def __init__(self):
        import os
        self._os, self._ant = os, None

    def cpu_percent(self, _=None):
        t, w = sum(self._os.times()[:2]), time.time()
        ant, self._ant = self._ant, (t, w)
        return 0.0 if ant is None else round(100 * (t - ant[0]) / max(w - ant[1], 1e-9), 1)

    def memory_info(self):
        from types import SimpleNamespace
        try:
            kb = next(int(l.split()[1]) for l in open("/proc/self/status") if l.startswith("VmRSS:"))
        except Exception:
            kb = 0
        return SimpleNamespace(rss=kb * 1024)


class Servico:
    def __init__(self, pacotes: list[str], broker: str, porta: int = 1883, orcamento: float | None = None,
                 registro: str | None = None, intervalo_estado: float = 10.0, carga: str | None = None,
                 prefixo: str = "carga", controlador: bool = False, atraso_max: float = 2.0, aquecer: bool = True):
        self.casas = {}
        for p in pacotes or []:
            c = CasaAoVivo(p, orcamento)
            self.casas[c.casa] = c
        self.pacote_carga, self.prefixo = carga, prefixo
        self.modelo = CasaAoVivo(carga, orcamento) if carga else None
        b0 = self.modelo.params.orcamento if self.modelo else orcamento
        self.orcamento = b0
        self.controlador, self.atraso_max = controlador, float(atraso_max)
        self.aquecer = aquecer
        self.niveis = sorted(float(k) for k in self.modelo.cfg["cascata"]) if self.modelo else list(NIVEIS)
        self.nivel_max = max(i for i, b in enumerate(self.niveis) if b <= (b0 if b0 is not None else 1.0) + 1e-9)
        self.nivel = self.nivel_max
        self.calmas = 0
        from collections import deque
        self.hist: deque = deque(maxlen=6)
        self.espera = 0
        self.calmas_exigidas = 18          # janelas calmas para subir (3 min); dobra se a subida anterior deu errado
        self.ult_subida = -10**9           # nº da janela da última subida
        self.janela = 0
        import queue
        self.fila: queue.Queue = queue.Queue()
        self.atrasos: list[float] = []
        self.base_atraso: float | None = None
        self.broker, self.porta = broker, porta
        self.intervalo = intervalo_estado
        self.reg = open(registro, "a", encoding="utf-8") if registro else None
        self.trava = threading.Lock()
        self.erros = 0
        self._ant = {"t": time.time(), "mensagens": 0}
        try:
            import psutil
            self.proc = psutil.Process()
        except ImportError:                                      # psutil está no Pi; nos testes pode faltar
            self.proc = _ProcSimples()
        self.proc.cpu_percent(None)

    def _registrar(self, tipo: str, dados: dict):
        if self.reg:
            self.reg.write(json.dumps({"tipo": tipo, "relogio": time.time(), **dados}, ensure_ascii=False) + "\n")
            self.reg.flush()

    def _ao_receber(self, cli, userdata, msg):
        try:
            if msg.topic == TOPICO_COMANDO:
                self.comando(json.loads(msg.payload))
                return
            partes = msg.topic.split("/")
            casa = self.casas.get(partes[1])
            if casa is None:
                if self.modelo is None or not partes[1].startswith(self.prefixo):
                    return
                casa = self._clonar(partes[1])
            d = json.loads(msg.payload)
            with self.trava:
                alertas = casa.recebe(d["medidor_id"], d.get("canal", 1), d["ts"], d["potencia_w"], d["energia_wh"])
                if self.modelo is not None:
                    self.atrasos.append(time.time() - _ts_float(d["ts"]))
            for a in alertas:
                cli.publish(TOPICO_ALERTAS, json.dumps(a, ensure_ascii=False), qos=1)
                self._registrar("alerta", a)
                print(f"ALERTA {a['ts']} {a['casa']}/{a['medidor_id']}: {a['estagio']} score={a['score']}", flush=True)
        except Exception as e:                                   # uma mensagem ruim não derruba o serviço
            self.erros += 1
            if self.erros <= 5:
                print(f"erro ao processar {msg.topic}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    def comando(self, d: dict) -> dict:
        """Comando do roteiro de bancada (E3/E4), JSON em `casa/sistema/detector/comando`:
        {"marca": "E3 b=1", "reset": true, "orcamento": 1.0, "controlador": false, "atraso_max": 2.0}.
        `reset` descarta as casas de carga (memória e estado) e a linha de base do atraso."""
        with self.trava:
            if d.get("reset"):
                for nome in [n for n in self.casas if n.startswith(self.prefixo)]:
                    del self.casas[nome]
                self.atrasos, self.base_atraso, self.calmas, self.espera = [], None, 0, 0
                self.hist.clear()
                self.calmas_exigidas, self.ult_subida, self.janela = 18, -10**9, 0
                self._ant = {"t": time.time(), "mensagens": 0}
            if "atraso_max" in d:
                self.atraso_max = float(d["atraso_max"])
            if "controlador" in d:
                self.controlador = bool(d["controlador"])
            if "orcamento" in d:
                b = float(d["orcamento"])
                self.nivel_max = self.nivel = max(i for i, x in enumerate(self.niveis) if x <= b + 1e-9)
                self.orcamento = self.niveis[self.nivel]
                if self.modelo is not None:
                    self.modelo.definir_orcamento(self.orcamento)
                for c in self.casas.values():
                    c.definir_orcamento(self.orcamento)
        r = {"marca": d.get("marca"), "orcamento": self.orcamento, "controlador": self.controlador,
             "atraso_max": self.atraso_max, "casas": len(self.casas)}
        self._registrar("comando", {"pedido": d, **r})
        print(f"COMANDO {json.dumps(d, ensure_ascii=False)} → {json.dumps(r, ensure_ascii=False)}", flush=True)
        return r

    def _clonar(self, nome: str) -> CasaAoVivo:
        """Casa virtual de carga: estado próprio, sessões ONNX da casa-modelo."""
        with self.trava:
            if nome not in self.casas:
                c = CasaAoVivo(self.pacote_carga, self.orcamento, carregar_modelos=False)
                c.sess = self.modelo.sess
                c.casa = nome
                if self.aquecer:
                    _aquecer(c)
                self.casas[nome] = c
            return self.casas[nome]

    def _controlar(self, p50, pior):
        """Controlador de carga do E4. Olha o PIOR atraso (acima da linha de base, que absorve a diferença de relógio
        PC × Pi) do último minuto (6 janelas de 10 s), porque o atraso aparece na virada do minuto, quando o minuto de
        todas as casas é processado. Desce um nível se o pior atraso passou do limite; sobe um nível depois de 3
        minutos seguidos com o pior atraso abaixo de metade do limite (o tempo exigido dobra, até 12 min, quando uma
        subida é desfeita em até 3 min). Depois de mudar, espera 1 minuto (o efeito só aparece na virada seguinte).
        Ao descer, a vigilância aberta com o τ antigo é zerada (CasaAoVivo.definir_orcamento). [Versão 2, depois da 1ª rodada do E3/E4, DIARIO K11: a versão 1 olhava o p95 de
        cada janela de 10 s e oscilava.]"""
        if p50 is not None:
            self.base_atraso = p50 if self.base_atraso is None else min(self.base_atraso, p50)
        if not self.controlador or pior is None:
            return
        self.janela += 1
        self.hist.append(pior - (self.base_atraso or 0.0))
        if self.espera > 0:
            self.espera -= 1
            return
        p = max(self.hist)
        novo = self.nivel
        if p > self.atraso_max and self.nivel > 0:
            novo, self.calmas = self.nivel - 1, 0
            if self.janela - self.ult_subida <= 18:          # a subida de há pouco não coube: espera o dobro
                self.calmas_exigidas = min(2 * self.calmas_exigidas, 72)
        elif p < self.atraso_max / 2 and len(self.hist) == self.hist.maxlen:
            self.calmas += 1
            if self.calmas >= self.calmas_exigidas and self.nivel < self.nivel_max:
                novo, self.calmas = self.nivel + 1, 0
                self.ult_subida = self.janela
        else:
            self.calmas = 0
        if novo != self.nivel:
            self.espera = 6
            self.hist.clear()
            self.nivel = novo
            self.orcamento = self.niveis[novo]
            with self.trava:
                for c in self.casas.values():
                    c.definir_orcamento(self.orcamento)

    def estado_carga(self) -> dict:
        """Estado agregado do modo de carga (uma linha, sem o detalhe por casa)."""
        agora = time.time()
        with self.trava:
            at, self.atrasos = self.atrasos, []
            tot = {k: sum(c.stats[k] for c in self.casas.values())
                   for k in ("mensagens", "minutos", "decisoes", "escaladas", "alertas", "seg_atributos",
                             "seg_estagio1", "seg_estagio2", "fora_de_ordem")}
            n_casas, n_canais = len(self.casas), sum(len(c.canais) for c in self.casas.values())
        ant = self._ant
        dt_ = max(agora - ant["t"], 1e-9)
        taxa = (tot["mensagens"] - ant["mensagens"]) / dt_
        dmin = max(tot["minutos"] - ant.get("minutos", 0), 1)
        r = {"msg_por_s": round(taxa, 1), "casas": n_casas, "canais": n_canais,
             "atraso_p50_s": _pct(at, 0.5), "atraso_p95_s": _pct(at, 0.95), "atraso_max_s": _pct(at, 1.0),
             "orcamento": self.orcamento,
             "escalados_pct_janela": round(100 * (tot["escaladas"] - ant.get("escaladas", 0))
                                           / max(tot["decisoes"] - ant.get("decisoes", 0), 1), 2),
             "ms_por_minuto_casa_janela": round(1e3 * sum(tot[k] - ant.get(k, 0.0) for k in
                                                         ("seg_atributos", "seg_estagio1", "seg_estagio2")) / dmin, 3),
             "cpu_pct": self.proc.cpu_percent(None), "mem_mb": round(self.proc.memory_info().rss / 2**20, 1),
             "temp_c": _temperatura(), "erros": self.erros, "total": tot}
        self._ant = {"t": agora, **tot}
        r["fila"] = self.fila.qsize()
        self._controlar(r["atraso_p50_s"], r["atraso_max_s"])
        r["orcamento_proximo"] = self.orcamento
        return r

    def estado(self) -> dict:
        agora = time.time()
        with self.trava:
            st = {c: dict(casa.stats, orcamento=casa.params.orcamento) for c, casa in self.casas.items()}
        tot = sum(s["mensagens"] for s in st.values())
        taxa = (tot - self._ant["mensagens"]) / max(agora - self._ant["t"], 1e-9)
        self._ant = {"t": agora, "mensagens": tot}
        mem = self.proc.memory_info().rss / 2**20
        return {"msg_por_s": round(taxa, 1), "cpu_pct": self.proc.cpu_percent(None), "mem_mb": round(mem, 1),
                "temp_c": _temperatura(), "erros": self.erros, "casas": st}

    def rodar(self):
        import paho.mqtt.client as mqtt
        cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"detector-{int(time.time())}")
        # A thread de rede do MQTT só enfileira; outra thread processa. Assim o socket continua sendo lido durante a
        # virada do minuto (quando o minuto de todas as casas é processado) e o Mosquitto não descarta mensagens
        # (1ª rodada do E3, DIARIO K11: até 24 % perdidas com o processamento dentro da thread de rede).
        # Comandos do roteiro não entram na fila: com fila acumulada (sobrecarga), um `reset` esperaria todo o
        # atraso acumulado (E6: comando aplicado 94 s depois; DIARIO K16).
        cli.on_message = lambda c, u, m: (self._ao_receber(c, u, m) if m.topic == TOPICO_COMANDO else self.fila.put(m))
        fim_trab = threading.Event()

        def trabalhador():
            import queue
            while not fim_trab.is_set():
                try:
                    m = self.fila.get(timeout=0.5)
                except queue.Empty:
                    continue
                self._ao_receber(cli, None, m)
        trab = threading.Thread(target=trabalhador, name="detector-processa", daemon=True)
        trab.start()
        topicos = (["casa/+/+/+/telemetria", TOPICO_COMANDO] if self.modelo
                   else [f"casa/{casa}/+/+/telemetria" for casa in self.casas])
        cli.on_connect = lambda c, u, f, rc, p=None: [c.subscribe(t, qos=0) for t in topicos]
        cli.connect(self.broker, self.porta, keepalive=30)
        parar = threading.Event()

        def ao_sinal(*_):
            if parar.is_set():                       # 2º pedido de parada: sai na hora
                import os
                if self.reg:
                    self.reg.flush()
                os._exit(1)
            parar.set()
        signal.signal(signal.SIGINT, ao_sinal)
        signal.signal(signal.SIGTERM, ao_sinal)
        cli.loop_start()
        print(f"detector ouvindo {self.broker}:{self.porta}, casas: {', '.join(self.casas) or '-'}"
              + (f"; modo de carga: casas '{self.prefixo}*' com o modelo {self.pacote_carga}, orçamento {self.orcamento}"
                 f"{', controlador ligado (atraso máx. ' + str(self.atraso_max) + ' s)' if self.controlador else ''}"
                 if self.modelo else ""), flush=True)
        try:
            while not parar.wait(self.intervalo):
                if self.modelo is not None:
                    e = self.estado_carga()
                    self._registrar("carga", e)
                    print(f"{time.strftime('%H:%M:%S')} casas={e['casas']:4d} canais={e['canais']:5d} "
                          f"{e['msg_por_s']:8.1f} msg/s  atraso p50/p95/máx={e['atraso_p50_s']}/{e['atraso_p95_s']}/"
                          f"{e['atraso_max_s']} s  orçamento={e['orcamento']}→{e['orcamento_proximo']}  "
                          f"escalados={e['escalados_pct_janela']}%  ms/min-casa={e['ms_por_minuto_casa_janela']}  "
                          f"fila={e['fila']}  CPU={e['cpu_pct']:5.1f}%  mem={e['mem_mb']} MB  temp={e['temp_c']} °C",
                          flush=True)
                    continue
                e = self.estado()
                self._registrar("estado", e)
                for nome, s in e["casas"].items():
                    n = max(s["minutos"], 1)
                    esc = 100 * s["escaladas"] / max(s["decisoes"], 1)
                    print(f"\n[{nome}] {e['msg_por_s']:7.1f} msg/s  minutos={s['minutos']}  escalados={esc:4.1f}%  "
                          f"alertas={s['alertas']}  CPU={e['cpu_pct']:5.1f}%  mem={e['mem_mb']} MB  "
                          f"temp={e['temp_c']} °C  ms/minuto: atributos={1e3 * s['seg_atributos'] / n:.2f} "
                          f"estágio1={1e3 * s['seg_estagio1'] / n:.2f} estágio2={1e3 * s['seg_estagio2'] / n:.2f}",
                          flush=True)
        finally:
            try:
                self._registrar("fim", self.estado_carga() if self.modelo is not None else self.estado())
            finally:
                if self.reg:
                    self.reg.close()
                    self.reg = None
                fim_trab.set()
                try:
                    cli.disconnect()
                    cli.loop_stop()
                except Exception:
                    pass
                print("detector parado.", flush=True)


def reproduzir(pacote: str, dados: str, particao: str = "teste", orcamento: float | None = None) -> dict:
    """Passa uma partição gravada pela versão ao vivo, sem MQTT (custo por minuto e alertas, no próprio Pi)."""
    from .dados import carregar_telemetria
    casa = CasaAoVivo(pacote, orcamento)
    tel = carregar_telemetria(dados, particao)
    msgs = sorted((int(t), c, float(p), float(e)) for c in tel.canais
                  for t, p, e in zip(tel.ts[c], tel.p[c], tel.e[c]) if c in casa.sinais)
    t0 = time.perf_counter()
    alertas = []
    for t, c, p, e in msgs:
        alertas += casa.recebe_chave(c, t, p, e)
    alertas += casa.finalizar(tel.fim)
    seg = time.perf_counter() - t0
    s = casa.stats
    n = max(s["minutos"], 1)
    return {"mensagens": s["mensagens"], "minutos": s["minutos"], "canais": len(casa.canais), "segundos": seg,
            "ms_por_minuto": 1e3 * seg / n, "us_por_mensagem": 1e6 * seg / max(s["mensagens"], 1),
            "ms_atributos": 1e3 * s["seg_atributos"] / n, "ms_estagio1": 1e3 * s["seg_estagio1"] / n,
            "ms_estagio2": 1e3 * s["seg_estagio2"] / n,
            "escalados_pct": 100 * s["escaladas"] / max(s["decisoes"], 1), "alertas": len(alertas),
            "orcamento": casa.params.orcamento, "temp_c": _temperatura()}
