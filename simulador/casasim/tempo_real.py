"""Modo tempo real: toca o dia simulado no relógio (com fator de velocidade) e aceita falhas e comandos ao vivo."""
from __future__ import annotations
import datetime as dt
import json
import threading
import time
from pathlib import Path

import numpy as np
from .dados import validar
from .falhas import DESCRICAO
from .motor import Simulador
from .mqtt import Publicador
from .tarifa import preco_kwh
from .util import N, hhmm


def _agora_real() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


class RegistroAoVivo:
    """Arquivo JSON Lines com tudo o que acontece numa sessão ao vivo (gabarito do experimento E5).

    Cada linha tem `evento`, `relogio_real` (hora do computador, com fuso) e `relogio_sim` (hora da casa simulada).
    Eventos: sessao_iniciada, falha_injetada, comando_recebido, alerta_recebido, velocidade, dia_concluido, sessao_encerrada.
    Nada disto vai para o MQTT: o detector no Pi não pode ver este arquivo durante o experimento.
    """

    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.caminho, "a", encoding="utf-8")
        self._trava = threading.Lock()

    def escrever(self, evento: str, relogio_sim: dt.datetime | None, **dados) -> None:
        linha = dict(evento=evento, relogio_real=_agora_real(), relogio_sim=relogio_sim.isoformat(sep=" ") if relogio_sim else None, **dados)
        with self._trava:
            self._fh.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()

    def fechar(self) -> None:
        with self._trava:
            if not self._fh.closed:
                self._fh.close()


class ExecucaoTempoReal:
    def __init__(self, sim: Simulador, velocidade: float = 60.0, publicador: Publicador | None = None, hora_inicial: str = "06:00",
                 bandeira: str | None = None, registro: str | Path | None = None):
        self.sim, self.vel, self.pub = sim, float(velocidade), publicador or Publicador()
        self.pub.ao_comando, self.pub.ao_alerta = self._cmd_mqtt, self._alerta
        self.trava = threading.RLock()
        self.dia = sim.simular_dia()
        self.t = float(hhmm(hora_inicial) or 0)
        self.ptr = {ch: int(np.searchsorted(m["t"], self.t, "right")) for ch, m in self.dia.mensagens.items()}
        self.ultima: dict[str, dict] = {}
        self.kwh_dias_anteriores, self.dias_completos = 0.0, 0
        self.alertas: list[dict] = []
        self.bandeira = bandeira
        self.rodando = False
        self._th: threading.Thread | None = None
        self.registro = RegistroAoVivo(registro) if registro else None
        self._reg("sessao_iniciada", cenario=sim.c.nome, casa=sim.c.casa, semente=sim.semente, velocidade=self.vel,
                  hora_inicial=hora_inicial, canais={ch: dict(medidor=c.medidor, canal=c.numero, comodo=c.comodo, aparelhos=c.instancias)
                                                     for ch, c in sim.c.canais.items()})

    def _reg(self, evento: str, **dados) -> None:
        if self.registro is not None:
            self.registro.escrever(evento, self.agora(), **dados)

    def mudar_velocidade(self, v: float) -> None:
        with self.trava:
            self.vel = max(0.0, min(3600.0, float(v)))
            self._reg("velocidade", velocidade=self.vel)

    # ------------------------------------------------------------------ relógio
    def agora(self) -> dt.datetime:
        return dt.datetime.combine(self.dia.data, dt.time()) + dt.timedelta(seconds=int(self.t))

    def iniciar(self) -> None:
        self.rodando = True
        self._th = threading.Thread(target=self._laco, daemon=True)
        self._th.start()

    def parar(self) -> None:
        self.rodando = False
        if self._th:
            self._th.join(timeout=2)
        self.pub.fechar()
        if self.registro is not None:
            self._reg("sessao_encerrada", mensagens_enviadas=self.pub.enviadas, dias_completos=self.dias_completos)
            self.registro.fechar()

    def _laco(self) -> None:
        ant = time.monotonic()
        while self.rodando:
            time.sleep(0.2)
            ag = time.monotonic()
            self.avancar((ag - ant) * self.vel)
            ant = ag

    def avancar(self, segundos: float) -> None:
        """Avança o relógio simulado e publica as mensagens que venceram (também usado nos testes)."""
        with self.trava:
            self.t += segundos
            while True:
                self._emitir(min(self.t, N))
                if self.t < N:
                    break
                if self.registro is not None:
                    self.registro.escrever("dia_concluido", dt.datetime.combine(self.dia.data, dt.time()) + dt.timedelta(seconds=N),
                                           data=self.dia.data.isoformat(), kwh=round(float(self.dia.geral.sum()) / 3.6e6, 3),
                                           gabarito=[{k: v for k, v in g.items() if k != "_ef"} for g in self.dia.gabarito])
                self.kwh_dias_anteriores += float(self.dia.geral.sum()) / 3.6e6
                self.dias_completos += 1
                self.t -= N
                self.dia = self.sim.simular_dia()
                self.ptr = {ch: 0 for ch in self.dia.mensagens}

    def _emitir(self, ate: float) -> None:
        for ch, m in self.dia.mensagens.items():
            k, n = self.ptr[ch], len(m["t"])
            while k < n and m["t"][k] <= ate:
                pl = self.sim.payload(ch, self.dia, k)
                self.pub.publicar(self.sim.c.canais[ch].topico(self.sim.c.casa), pl)
                self.ultima[ch] = pl
                k += 1
            self.ptr[ch] = k

    def _ressincronizar(self) -> None:
        self.sim.finalizar(self.dia)
        self.ptr = {ch: int(np.searchsorted(m["t"], self.t, "right")) for ch, m in self.dia.mensagens.items()}

    # ------------------------------------------------------------------ ações
    def injetar(self, tipo: str, alvo: str, duracao_min: float | None = None, params: dict | None = None):
        with self.trava:
            f = self.sim.injetor.nova(tipo, alvo, self.agora(), int(duracao_min * 60) if duracao_min else None, params, origem="painel")
            self._ressincronizar()
            self._reg("falha_injetada", falha_id=f.id, tipo=f.tipo, alvo=f.alvo, inicio_sim=f.inicio.isoformat(sep=" "),
                      fim_sim=f.fim.isoformat(sep=" "), duracao_s=f.duracao_s, params=f.params, origem=f.origem, velocidade=self.vel,
                      duracao_real_s=round(f.duracao_s / self.vel, 2) if self.vel else None)
            return f

    def comando(self, canal: str, acao: str, origem: str = "painel") -> bool:
        with self.trava:
            ok = self.sim.comando(canal, acao, self.agora())
            self._reg("comando_recebido", canal=canal, acao=acao, origem=origem, aceito=bool(ok))
            if ok:
                self._ressincronizar()
            return ok

    def _cmd_mqtt(self, medidor: str, dados: dict) -> None:
        acao = str(dados.get("acao", "")).lower()
        for ch, c in self.sim.c.canais.items():
            if c.medidor == medidor and int(dados.get("canal", c.numero)) == c.numero and acao in ("ligar", "desligar"):
                self.comando(ch, acao, origem="mqtt")

    def _alerta(self, dados: dict) -> None:
        with self.trava:
            ag = self.agora()
            ativas = [f.id for f in self.sim.injetor.falhas if f.inicio <= ag < f.fim]
        self._reg("alerta_recebido", alerta=dados, falhas_ativas=ativas)
        self.alertas.append(dict(dados, recebido_em=self.agora().isoformat(sep=" ")))
        del self.alertas[:-50]

    # ------------------------------------------------------------------ painel
    def estado(self) -> dict:
        with self.trava:
            c, d, s = self.sim.c, self.dia, min(N - 1, int(self.t))
            ag = self.agora()
            ap, comodos = {}, {}
            for iid, p in d.pot.items():
                w = float(p[s])
                ap[iid] = round(w, 1)
                com = c.instancias[iid].comodo
                comodos[com] = comodos.get(com, 0.0) + w
            canais = {}
            for ch, canal in c.canais.items():
                u = self.ultima.get(ch, {})
                cortado = any(fim is None for _, fim in self.sim.cortes.get(ch, []))
                canais[ch] = dict(medidor=canal.medidor.upper(), numero=canal.numero, comodo=canal.comodo, onde=canal.onde, geral=canal.geral,
                                  modelo=canal.sensor["modelo"], firmware=canal.sensor.get("firmware"), modo=canal.sensor.get("modo"),
                                  intervalo_s=self.sim.sensores[ch].intervalo, tem_rele=bool(canal.sensor.get("tem_rele")) and not canal.geral,
                                  cortado=cortado, aparelhos=canal.instancias, potencia_w=u.get("potencia_w"), energia_wh=u.get("energia_wh"),
                                  ts=u.get("ts"), tensao_v=u.get("tensao_v"))
            gerais = c.canais_gerais
            kwh_hoje = float(d.geral[:s + 1].sum()) / 3.6e6
            medido_hoje = None
            if gerais and all(g.chave in self.ultima for g in gerais):
                medido_hoje = sum(self.ultima[g.chave]["energia_wh"] - self.sim.sensores[g.chave].e0 for g in gerais) / 1000
            preco = preco_kwh(self.bandeira)
            dias = self.dias_completos + (s + 1) / N
            kwh_total = self.kwh_dias_anteriores + kwh_hoje
            curva = d.geral[: (s // 300) * 300].reshape(-1, 300).mean(axis=1).round(0).tolist() if s >= 300 else []
            falhas = [dict(id=f.id, tipo=f.tipo, alvo=f.alvo, inicio=f.inicio.isoformat(sep=" "), fim=f.fim.isoformat(sep=" "),
                           ativa=f.inicio <= ag < f.fim, origem=f.origem) for f in self.sim.injetor.falhas if f.fim > ag - dt.timedelta(hours=6)]
            return dict(agora=ag.isoformat(sep=" "), dia_semana=["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"][ag.weekday()],
                        velocidade=self.vel, cenario=c.nome, casa=c.casa, familia=c.personas.get("familia"),
                        total_medido_w=round(sum(canais[g.chave]["potencia_w"] or 0 for g in gerais), 1) if gerais else None, total_real_w=round(float(d.geral[s]), 1),
                        base_w=round(float(d.base_w[s]), 1), aparelhos=ap, comodos={k: round(v, 1) for k, v in comodos.items()}, canais=canais,
                        kwh_hoje=round(kwh_hoje, 3), kwh_hoje_medido=round(medido_hoje, 3) if medido_hoje is not None else None,
                        custo_hoje=round(kwh_hoje * preco, 2), preco_kwh=round(preco, 4), bandeira=self.bandeira or "verde",
                        kwh_mes_projetado=round(kwh_total / dias * 30.42, 1), custo_mes_projetado=round(kwh_total / dias * 30.42 * preco, 2),
                        temperatura_c=round(float(d.clima.t_ext[s // 60]), 1), tensao_pu=round(float(d.v_pu[s // 60]), 3),
                        sem_energia=any(a <= s < b for a, b in d.faltas), curva_5min_w=curva, falhas=falhas, alertas=self.alertas[-10:],
                        mqtt=dict(ativo=self.pub.ativo, erro=self.pub.erro, enviadas=self.pub.enviadas),
                        moradores=[dict(nome=p.cfg["nome"], em_casa=any(a <= s < b for a, b in p.em_casa), dormindo=not (p.acorda <= s < p.dorme))
                                   for p in d.info["pessoas"]])


def descricoes_falhas() -> dict:
    return dict(DESCRICAO)
