"""Detector ao vivo (o que roda no Raspberry Pi): mensagem por mensagem, um minuto de cada vez.

Reproduz EXATAMENTE os atributos de `atributos.py` e a cascata de `cascata.py`, mas de forma incremental:
- cada canal guarda só o necessário (últimas mensagens, acumuladores de energia do minuto, janelas de 15/60 min);
- o minuto m de uma casa é fechado quando chega uma mensagem com ts >= fim do minuto (as mensagens de uma casa
  chegam em ordem de tempo; o relógio é o das próprias mensagens, então funciona com o simulador acelerado);
- ao fechar o minuto: sinais → atributos → estágio 1 (OCSVM + regra) → estágio 2 (LSTM-AE) só se o canal estiver
  em vigilância → alertas.
Há testes que comparam, minuto a minuto, com a versão do notebook (`tests/test_detector.py`).

Só depende de numpy e onnxruntime (o que já está no venv do Pi).
"""
from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .atributos import (FUSO_S, RESIDUO, SUB_S, TETO_MIN, TOLERANCIA_OFF, VELHO_S, nomes_seq, nomes_tab)

JUNTAR_MIN = 10
RECUPERACAO_MIN = 30


def _slog(x: float) -> float:
    return math.copysign(math.log1p(abs(x)), x) if x == x else 0.0


def ts_epoch(ts) -> int:
    """`ts` do contrato MQTT (ISO 8601 com fuso) ou já em segundos."""
    if isinstance(ts, (int, float)):
        return int(ts)
    return int(datetime.fromisoformat(ts).timestamp())


def _iso(t: int) -> str:
    """Segundos → ISO 8601 no horário de Brasília, como no contrato MQTT."""
    return datetime.fromtimestamp(t + FUSO_S, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S-03:00")


def _soma(a: list) -> float:
    """Soma com a MESMA ordem de operações do numpy (`pairwise_sum`, n <= 128): resultado bit a bit igual a
    `np.sum`, sem o custo de criar um array para listas pequenas."""
    n = len(a)
    if n < 8:
        r = 0.0
        for x in a:
            r += x
        return r
    if n > 128:
        return float(np.sum(np.asarray(a, np.float64)))
    r0, r1, r2, r3, r4, r5, r6, r7 = a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]
    i = 8
    lim = n - (n % 8)
    while i < lim:
        r0 += a[i]; r1 += a[i + 1]; r2 += a[i + 2]; r3 += a[i + 3]
        r4 += a[i + 4]; r5 += a[i + 5]; r6 += a[i + 6]; r7 += a[i + 7]
        i += 8
    res = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7))
    while i < n:
        res += a[i]
        i += 1
    return res


# ------------------------------------------------------------------------------------------------ sinais

class SinaisCanal:
    """Sinais de 1 minuto de um canal (p_med, e_pot, exc, vivo), iguais a `atributos.sinais_por_minuto`."""

    def __init__(self):
        self.ts = deque()          # mensagens ainda úteis para o valor mantido (ts, p)
        self.p = deque()
        self.ult = None            # última mensagem (ts, p, e) para os intervalos de energia
        self.baldes: dict[int, list] = {}   # minuto absoluto → [Σ energia, Σ dt, maior excesso]

    def recebe(self, ts: int, p: float, e: float) -> bool:
        if self.ult is not None and ts < self.ult[0]:
            return False                                      # fora de ordem: descartada (contada pela casa)
        if self.ult is not None:
            dt = ts - self.ult[0]
            if 0 < dt <= VELHO_S:
                de = e - self.ult[2]
                pe = de * 3600.0 / dt
                exc = pe - 0.5 * (p + self.ult[1])
                b = self.baldes.setdefault(ts // 60, [0.0, 0.0, -math.inf])
                b[0] += de
                b[1] += dt
                if exc > b[2]:
                    b[2] = exc
        self.ult = (ts, p, e)
        self.ts.append(ts)
        self.p.append(p)
        return True

    def fecha(self, m: int) -> tuple[float, float, float, bool]:
        """Fecha o minuto absoluto m (janela [60m, 60m+60)). Devolve (p_med, e_pot, exc, vivo)."""
        a = 60 * m
        ts, p = self.ts, self.p
        n = len(ts)
        v = []
        j = -1                                              # última mensagem com ts <= tick
        for k in range(60 // SUB_S):
            tick = a + SUB_S * k
            while j + 1 < n and ts[j + 1] <= tick:
                j += 1
            v.append(p[j] if j >= 0 and tick - ts[j] <= VELHO_S else math.nan)
        cont = sum(1 for x in v if x == x)
        p_med = _soma([x if x == x else 0.0 for x in v]) / cont if cont else math.nan
        fim = a + 60
        while j + 1 < n and ts[j + 1] < fim:
            j += 1
        vivo = j >= 0 and (fim - ts[j]) <= VELHO_S
        b = self.baldes.pop(m, None)
        if b is not None and b[1] > 0:
            e_pot = b[0] * 3600.0 / b[1]
            exc = b[2] if math.isfinite(b[2]) else math.nan
        else:
            e_pot = exc = math.nan
        while len(self.ts) > 1 and self.ts[1] <= fim:
            self.ts.popleft()
            self.p.popleft()
        for k in [k for k in self.baldes if k < m]:
            del self.baldes[k]
        return p_med, e_pot, exc, bool(vivo)


# ------------------------------------------------------------------------------------------------ janelas

class Janela:
    """Últimos n valores (com NaN). Estatísticas iguais, bit a bit, às do numpy sobre os valores não-NaN
    (soma em pares; desvio com ddof=1; mediana) — e iguais às do pandas `rolling`, a menos do desvio-padrão, que
    o pandas calcula com acumulação incremental (diferença de até ~3e-4 no atributo, sem efeito nas decisões)."""

    def __init__(self, n: int):
        self.v = deque(maxlen=n)

    def add(self, x: float):
        self.v.append(x)

    def _a(self):
        return [x for x in self.v if x == x]

    def media(self):
        a = self._a()
        return _soma(a) / len(a) if a else math.nan

    def maximo(self):
        a = self._a()
        return max(a) if a else math.nan

    def minimo(self):
        a = self._a()
        return min(a) if a else math.nan

    def desvio(self):
        a = self._a()
        n = len(a)
        if n < 2:
            return math.nan
        m = _soma(a) / n
        return math.sqrt(_soma([(x - m) * (x - m) for x in a]) / (n - 1))

    def mediana(self):
        a = sorted(self._a())
        n = len(a)
        if not n:
            return math.nan
        h = n // 2
        return a[h] if n % 2 else (a[h - 1] + a[h]) / 2.0

    def soma(self):
        a = self._a()
        return _soma(a) if a else math.nan


class AtributosCanal:
    """Estado e atributos de um canal, iguais a `Extrator.transformar` (tabular e sequência)."""

    def __init__(self, limiar_on: float, p_on_hora: list[float], geral: bool, L: int = 60):
        self.limiar = limiar_on
        self.rar_hora = [-math.log10(x) for x in p_on_hora]
        self.geral = geral
        self.pm15, self.pm60 = Janela(15), Janela(60)
        self.ep15, self.ex15, self.on15 = Janela(15), Janela(15), Janela(15)
        self.part60, self.rar15 = Janela(60), Janela(15)
        self.seq = deque(maxlen=L)
        self.ult_on = -1
        self.ini_ep = -1
        self.ant_on = -10**9
        self.i = -1                 # índice do minuto desde o início (como no notebook)

    def passo(self, p_med, e_pot, exc, h_sin, h_cos, fds, hora_int, res15=None, res60=None, res=None):
        self.i += 1
        i = self.i
        on = (0.0 if p_med != p_med else p_med) > self.limiar
        partida = 0.0
        if on:
            if i - self.ant_on > TOLERANCIA_OFF + 1:
                self.ini_ep = i
                partida = 1.0
            self.ant_on = i
            self.ult_on = i
        desde = float(i - self.ult_on) if self.ult_on >= 0 else TETO_MIN
        ativo = self.ult_on >= 0 and desde <= TOLERANCIA_OFF
        run = float(i - self.ini_ep + 1) if ativo else 0.0
        run, desde = min(run, TETO_MIN), min(desde, TETO_MIN)
        rar = self.rar_hora[hora_int] * on
        ex = max(0.0 if exc != exc else exc, 0.0)
        for jan, x in ((self.pm15, p_med), (self.pm60, p_med), (self.ep15, e_pot), (self.ex15, ex),
                       (self.on15, float(on)), (self.part60, partida), (self.rar15, rar)):
            jan.add(x)
        n = lambda x: 0.0 if x != x else x
        tab = [_slog(n(self.pm15.media())), _slog(n(self.pm15.maximo())), _slog(n(self.pm15.desvio())),
               _slog(n(self.pm15.minimo())), _slog(n(self.pm60.media())), _slog(n(self.pm60.mediana())),
               _slog(n(self.ep15.media())), _slog(n(self.ex15.maximo())),
               self.on15.media(), self.part60.soma(), math.log1p(run), math.log1p(desde),
               self.rar15.maximo(), h_sin, h_cos, fds]
        seq = [_slog(n(p_med)), _slog(n(e_pot)), _slog(ex), float(on), math.log1p(run), math.log1p(desde), rar,
               h_sin, h_cos, fds]
        if self.geral:
            tab += [_slog(n(res60)), _slog(n(res15))]
            seq += [_slog(n(res))]
        self.seq.append(np.asarray(seq, np.float32))
        return np.asarray(tab, np.float32)


# ------------------------------------------------------------------------------------------------ cascata

@dataclass
class ParamsCascata:
    tau: float
    theta_saida: float
    theta2: float
    k: int
    orcamento: float
    V: int = 30


@dataclass
class EstadoCascata:
    run_r: int = 0
    run_m: int = 0
    ult_gatilho: int = -10**9
    ult_alarme: int = -10**9
    alerta_aberto: dict | None = None


class Sessao:
    def __init__(self, caminho: Path):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        self.s = ort.InferenceSession(str(caminho), so, providers=["CPUExecutionProvider"])

    def __call__(self, x: np.ndarray) -> float:
        return float(self.s.run(["score"], {"x": x})[0][0])


@dataclass
class Decisao:
    """O que aconteceu num canal num minuto (para registro e painel)."""
    canal: str
    s_ocsvm: float
    s_regra: float
    s_lstm: float | None
    vigilancia: bool
    alarme: bool


class CasaAoVivo:
    """Uma casa monitorada pelo Pi. Construída a partir do pacote gerado por `python -m detector empacotar`."""

    def __init__(self, pacote: str | Path, orcamento: float | None = None, carregar_modelos: bool = True):
        pacote = Path(pacote)
        self.cfg = json.loads((pacote / "casa_borda.json").read_text(encoding="utf-8"))
        c = self.cfg
        self.casa = c["casa"]
        self.canais_reais = [x for x in c["canais"] if x != RESIDUO]
        self.canais = list(c["canais"])
        self.geral = list(c["geral"])
        self.multi = set(c["medidores_varios_canais"])
        self.sinais = {x: SinaisCanal() for x in self.canais_reais}
        L = c["modelos"]["lstm_ae"]["L"]
        self.L = L
        self.at = {x: AtributosCanal(c["limiar_ligado_w"][x], c["p_ligado_por_hora"][x], x in self.geral, L)
                   for x in self.canais}
        self.res15, self.res60 = Janela(15), Janela(60)
        self.est = {x: EstadoCascata() for x in self.canais}
        self.norm = {m: c["modelos"][m]["normalizacao"] for m in ("ocsvm", "regra", "lstm_ae")}
        self.regra = (c["modelos"]["regra"]["theta"], c["modelos"]["regra"]["k"])
        self.sess = {}
        if carregar_modelos:
            for m in ("ocsvm", "lstm_ae"):
                self.sess[m] = {x: Sessao(pacote / m / f"{x}.onnx") for x in self.canais}
        self.definir_orcamento(c["orcamento_padrao"] if orcamento is None else orcamento)
        self.proximo: int | None = None
        self.silencio_ant = False
        self.supr_ate = -1
        self.i = -1
        self.stats = {"mensagens": 0, "fora_de_ordem": 0, "desconhecidas": 0, "minutos": 0, "decisoes": 0,
                      "escaladas": 0, "alertas": 0, "seg_atributos": 0.0, "seg_estagio1": 0.0, "seg_estagio2": 0.0}
        self.ultimo_minuto: dict = {}
        self.silencios: list[list[int]] = []

    # -------------------------------------------------------------------------------- configuração
    def definir_orcamento(self, b: float):
        """Escolhe um dos orçamentos calibrados (no Pi, o controlador de carga chama isto)."""
        orc = self.cfg["cascata"]
        chave = min(orc, key=lambda k: abs(float(k) - b))
        o = orc[chave]
        inf = lambda x, d: d if x is None else float(x)
        b = float(chave)
        tau = -math.inf if b >= 1.0 else (math.inf if b <= 0.0 else float(o["tau"]))
        ant = getattr(self, "params", None)
        if ant is not None and tau > ant.tau:
            # Orçamento menor = τ maior: a vigilância aberta com o τ antigo (30 min) não vale mais; sem isto o corte de
            # custo pedido pelo controlador só aparecia até 30 min depois (E4, 2ª rodada, DIARIO K13).
            for e in self.est.values():
                e.ult_gatilho = -10**9
        self.params = ParamsCascata(tau, inf(o["theta_saida"], math.inf), inf(o["theta2"], math.inf), int(o["k"]), b,
                                    int(self.cfg.get("vigilancia_min", 30)))

    def chave(self, medidor: str, canal: int) -> str:
        return f"{medidor}_c{canal}" if medidor in self.multi else medidor

    # -------------------------------------------------------------------------------- entrada
    def recebe(self, medidor: str, canal: int, ts, potencia_w: float, energia_wh: float) -> list[dict]:
        """Entrega uma mensagem de telemetria. Devolve os alertas novos (minutos fechados por esta mensagem)."""
        return self.recebe_chave(self.chave(medidor, int(canal)), ts_epoch(ts), potencia_w, energia_wh)

    def recebe_chave(self, c: str, t: int, potencia_w: float, energia_wh: float) -> list[dict]:
        self.stats["mensagens"] += 1
        alertas = []
        if self.proximo is None:
            self.proximo = t // 60
        while (self.proximo + 1) * 60 <= t:
            alertas += self._fecha(self.proximo)
            self.proximo += 1
        s = self.sinais.get(c)
        if s is None:
            self.stats["desconhecidas"] += 1
        elif not s.recebe(t, float(potencia_w), float(energia_wh)):
            self.stats["fora_de_ordem"] += 1
        return alertas

    def finalizar(self, ate_ts: int) -> list[dict]:
        """Fecha os minutos que terminam até `ate_ts` (fim de uma reprodução)."""
        out = []
        while self.proximo is not None and (self.proximo + 1) * 60 <= ate_ts:
            out += self._fecha(self.proximo)
            self.proximo += 1
        return out

    # -------------------------------------------------------------------------------- um minuto
    def _fecha(self, m: int) -> list[dict]:
        t0 = time.perf_counter()
        self.i += 1
        fim = 60 * (m + 1)
        loc = fim + FUSO_S
        hora = (loc % 86400) / 3600.0
        h_int = int(hora)
        h_sin, h_cos = math.sin(2 * math.pi * hora / 24), math.cos(2 * math.pi * hora / 24)
        fds = 1.0 if ((loc // 86400) + 3) % 7 >= 5 else 0.0

        sig = {c: self.sinais[c].fecha(m) for c in self.canais_reais}
        g_p = g_e = pr_p = pr_e = 0.0
        vivo_g = False
        for c, (pm, ep, ex, vivo) in sig.items():
            if c in self.geral:
                vivo_g |= vivo
                g_p += 0.0 if pm != pm else pm
                g_e += 0.0 if ep != ep else ep
            else:
                pr_p += 0.0 if pm != pm else pm
                pr_e += 0.0 if ep != ep else ep
        res = (g_p - pr_p) if vivo_g else math.nan
        sig[RESIDUO] = (res, (g_e - pr_e) if vivo_g else math.nan, 0.0, vivo_g)
        self.res15.add(res)
        self.res60.add(res)
        r15, r60 = self.res15.media(), self.res60.mediana()

        silencio = not any(v[3] for c, v in sig.items() if c != RESIDUO)
        if silencio:
            if not self.silencio_ant:
                self.silencios.append([fim - 60, fim])          # trecho de falta de energia (regra do silêncio)
            else:
                self.silencios[-1][1] = fim
        if self.silencio_ant and not silencio:
            self.supr_ate = self.i + RECUPERACAO_MIN - 1
        self.silencio_ant = silencio
        sup = silencio or self.i <= self.supr_ate

        tabs = {}
        for c in self.canais:
            pm, ep, ex, vivo = sig[c]
            tabs[c] = self.at[c].passo(pm, ep, ex, h_sin, h_cos, fds, h_int, r15, r60, res)
        t1 = time.perf_counter()
        self.stats["seg_atributos"] += t1 - t0
        self.stats["minutos"] += 1

        novos = []
        dec = {}
        for c in self.canais:
            d = self._cascata(c, sig[c][3], tabs[c], sup, m)
            dec[c] = d
            if d is not None and d.alarme:
                a = self._alerta(c, d, m, fim)
                if a:
                    novos.append(a)
        self.ultimo_minuto = {"minuto": m, "ts": fim, "suprimido": sup, "silencio": silencio, "decisoes": dec}
        return novos

    def _cascata(self, c: str, vivo: bool, tab: np.ndarray, sup: bool, m: int) -> Decisao | None:
        e = self.est[c]
        P = self.params
        th_r, k_r = self.regra
        if vivo:
            t = time.perf_counter()
            no = self.norm["ocsvm"][c]
            so = (self.sess["ocsvm"][c](tab[None, :]) - no[0]) / no[1] if self.sess else math.nan
            nr = self.norm["regra"][c]
            sr = (float(tab[1]) - nr[0]) / nr[1]
            self.stats["seg_estagio1"] += time.perf_counter() - t
            self.stats["decisoes"] += 1
        else:
            so = sr = math.nan
        r_bruto = (sr > th_r) and not sup
        e.run_r = e.run_r + 1 if r_bruto else 0
        r = e.run_r >= k_r
        if P.tau == -math.inf:
            vig = True
        elif P.tau == math.inf:
            vig = False
        else:
            if r or so > P.tau:
                e.ult_gatilho = self.i
            vig = self.i - e.ult_gatilho < P.V
        s2 = None
        if vig and vivo and self.i >= self.L - 1 and self.sess:
            t = time.perf_counter()
            x = np.stack(self.at[c].seq)[None, :, :]
            n2 = self.norm["lstm_ae"][c]
            s2 = (self.sess["lstm_ae"][c](x) - n2[0]) / n2[1]
            self.stats["seg_estagio2"] += time.perf_counter() - t
            self.stats["escaladas"] += 1
        m_bruto = ((so > P.theta_saida) or (vig and s2 is not None and s2 > P.theta2)) and not sup
        e.run_m = e.run_m + 1 if m_bruto else 0
        alarme = r or e.run_m >= P.k
        return Decisao(c, so, sr, s2, vig, alarme)

    def _alerta(self, c: str, d: Decisao, m: int, fim: int) -> dict | None:
        e = self.est[c]
        novo = self.i - e.ult_alarme > JUNTAR_MIN + 1
        e.ult_alarme = self.i
        if not novo:
            return None
        self.stats["alertas"] += 1
        if c == RESIDUO:
            medidor, canal = "residuo", None
        elif "_c" in c and c.split("_c")[0] in self.multi:
            medidor, canal = c.split("_c")[0], int(c.split("_c")[1])
        else:
            medidor, canal = c, 1
        th_r = self.regra[0]
        estagio = "regra" if d.s_regra > th_r else ("lstm_ae" if d.s_lstm is not None and d.s_lstm > self.params.theta2
                                                    else "ocsvm")
        score = {"regra": d.s_regra, "lstm_ae": d.s_lstm, "ocsvm": d.s_ocsvm}[estagio]
        return {"ts": _iso(fim), "casa": self.casa, "medidor_id": medidor, "canal": canal, "tipo": "anomalia",
                "estagio": estagio, "score": round(float(score), 3), "orcamento": self.params.orcamento,
                "mensagem": f"Consumo fora do padrão em {c} (decidido por {estagio}).", "acao": None}


# ------------------------------------------------------------------------------------------------ pacote

def empacotar(dir_baselines: Path, dir_cascata: Path, perfil: str, semente: int, saida: Path,
              orcamento_padrao: float = 0.05) -> Path:
    """Junta num diretório tudo o que o Pi precisa para uma casa: .onnx, normalização, limiares e orçamentos."""
    import csv
    import shutil
    db = Path(dir_baselines) / perfil / f"semente_{semente}"
    dc = Path(dir_cascata) / perfil / f"semente_{semente}"
    saida = Path(saida)
    casa = json.loads((db / "casa.json").read_text(encoding="utf-8"))
    cfgs = {m: json.loads((db / m / "config.json").read_text(encoding="utf-8")) for m in ("ocsvm", "regra", "lstm_ae")}
    canais = list(cfgs["ocsvm"]["canais"])
    multi = sorted({c.split("_c")[0] for c in canais if "_c" in c and c != RESIDUO})
    for m in ("ocsvm", "lstm_ae"):
        (saida / m).mkdir(parents=True, exist_ok=True)
        for c in canais:
            shutil.copy2(db / m / f"{c}.onnx", saida / m / f"{c}.onnx")
    orc = {}
    with open(dc / "orcamentos.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            val = lambda x: None if x in ("", "nan", "None") else float(x)
            orc[r["orcamento"]] = {"tau": val(r["tau"]), "theta_saida": val(r["theta_saida"]),
                                   "theta2": val(r["theta2"]), "k": int(float(r["k"])),
                                   "f1_calibracao": val(r["f1_calibracao"])}
    norm = {m: {c: [v["mediana"], v["escala"]] for c, v in cfgs[m]["canais"].items()} for m in cfgs}
    L = next(iter(cfgs["lstm_ae"]["canais"].values()))["hiperparametros"]["L_minutos"]
    doc = {
        "casa": perfil, "origem": {"perfil": perfil, "semente": semente, "baselines": str(db), "cascata": str(dc)},
        "canais": canais, "geral": casa["geral"], "medidores_varios_canais": multi,
        "limiar_ligado_w": casa["limiar_ligado_w"], "p_ligado_por_hora": casa["p_ligado_por_hora"],
        "atributos_tab": {c: nomes_tab(c in casa["geral"]) for c in canais},
        "atributos_seq": {c: nomes_seq(c in casa["geral"]) for c in canais},
        "modelos": {"ocsvm": {"normalizacao": norm["ocsvm"]},
                    "regra": {"normalizacao": norm["regra"], "theta": cfgs["regra"]["theta"],
                              "k": cfgs["regra"]["persistencia_k"]},
                    "lstm_ae": {"normalizacao": norm["lstm_ae"], "L": L}},
        "cascata": orc, "orcamento_padrao": orcamento_padrao, "vigilancia_min": 30,
        "versoes": casa.get("versoes", {}),
    }
    (saida / "casa_borda.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return saida
