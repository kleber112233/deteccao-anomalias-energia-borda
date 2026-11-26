"""Motor do simulador: junta clima, rede, moradores, aparelhos, falhas e medidores, um dia por vez."""
from __future__ import annotations
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
from . import __name__ as _pkg  # noqa: F401
from .aparelhos import Ctx, RESISTIVOS, gerar
from .clima import Clima, ClimaDia
from .comportamento import Comportamento, Uso
from .dados import Cenario, carregar_cenario
from .falhas import InjetorFalhas
from .rede import Rede
from .sensores import Sensor
from .util import N, epoch_meia_noite, iso, rng_de


@dataclass
class Dia:
    data: dt.date
    t0: int                                   # epoch da meia-noite local
    clima: ClimaDia
    v_pu: np.ndarray
    usos: list[Uso]
    info: dict
    pot_base: dict[str, np.ndarray]           # potência real sem falhas, por aparelho (W, 1 s)
    faltas_rede: list[tuple[int, int]]
    base_w: np.ndarray                        # carga de base não medida
    pot: dict[str, np.ndarray] = field(default_factory=dict)      # com falhas, cortes e faltas
    geral: np.ndarray | None = None
    faltas: list[tuple[int, int]] = field(default_factory=list)
    mensagens: dict[str, dict] = field(default_factory=dict)      # por canal
    gabarito: list[dict] = field(default_factory=list)


class Simulador:
    """Simula a casa de um cenário.

    >>> sim = Simulador("perfil1", semente=42, inicio="2026-01-05")
    >>> dia = sim.simular_dia()
    """

    def __init__(self, cenario: str | Cenario = "perfil1", semente: int = 42, inicio: str | dt.date = "2026-01-05",
                 falhas_por_semana: float = 0.0, dias_previstos: int = 30, faltas_naturais: bool = True,
                 intervalo_sensor_s: int | None = None):
        self.c = cenario if isinstance(cenario, Cenario) else carregar_cenario(cenario)
        self.semente = int(semente)
        self.data = dt.date.fromisoformat(inicio) if isinstance(inicio, str) else inicio
        self.inicio = self.data
        self.clima = Clima(self.semente)
        self.rede = Rede(self.semente, faltas_por_ano=5.0 if faltas_naturais else 0.0)
        self.comp = Comportamento(self.c, self.semente)
        self.injetor = InjetorFalhas(self.c, self.semente)
        if falhas_por_semana > 0:
            self.injetor.plano_aleatorio(self.data, dias_previstos, falhas_por_semana)
        self.estado: dict[str, dict] = {i: {} for i in self.c.instancias}
        self.sensores: dict[str, Sensor] = {}
        for ch, canal in self.c.canais.items():
            ins = [self.c.instancias[i] for i in canal.instancias]
            v = max((i.tensao for i in ins), default=max(self.c.tensoes) if canal.geral and not canal.fase and len(self.c.tensoes) > 1 else 127)
            fp = float(np.mean([i.spec["fator_potencia"] for i in ins])) if ins else 0.92
            self.sensores[ch] = Sensor(canal, self.semente, v, fp, intervalo_sensor_s)
        self.cortes: dict[str, list[list]] = {}        # canal -> [[data_hora_ini, data_hora_fim|None], ...] (relé desligado)

    # ------------------------------------------------------------------
    def simular_dia(self) -> Dia:
        data, o = self.data, self.data.toordinal()
        for s in self.sensores.values():               # fecha o contador de energia do dia anterior
            s.e0 = s.e_fim
        clima = self.clima.dia(data)
        v_pu, faltas = self.rede.dia(data)
        usos, info = self.comp.dia(data, clima)
        v2 = np.repeat(v_pu.astype(np.float32) ** 2, 60)
        pot = {}
        for iid, inst in self.c.instancias.items():
            ctx = Ctx(clima, info["atividade"], rng_de(self.semente, "aparelho", iid, o), o)
            p = gerar(inst, [u for u in usos if u.inst == iid], ctx, self.estado[iid])
            if inst.classe in RESISTIVOS:
                p = p * v2
            pot[iid] = p
        rb = rng_de(self.semente, "base", o)
        base = float(self.c.personas["habitos"].get("carga_base_w", 20)) * (1 + np.clip(np.repeat(rb.normal(0, 0.05, 1440), 60), -0.15, 0.15)).astype(np.float32)
        dia = Dia(data, epoch_meia_noite(data), clima, v_pu, usos, info, pot, faltas, base)
        self.finalizar(dia)
        self.data = data + dt.timedelta(days=1)
        return dia

    def finalizar(self, dia: Dia) -> Dia:
        """(Re)aplica falhas, cortes de relé e faltas e refaz as medições. Pode ser chamado de novo depois de injetar uma falha."""
        pot, extra, faltas_inj, linhas = self.injetor.aplicar(dia.data, dia.pot_base, dia.usos, dia.clima, dia.info["atividade"])
        t00 = dt.datetime.combine(dia.data, dt.time())
        desligado: dict[str, list[tuple[int, int]]] = {}
        for ch, lista in self.cortes.items():
            for ini, fim in lista:
                a = int((ini - t00).total_seconds())
                b = int((fim - t00).total_seconds()) if fim else N
                if b <= 0 or a >= N:
                    continue
                a, b = max(0, a), min(N, b)
                desligado.setdefault(ch, []).append((a, b))
                for iid in self.c.canais[ch].instancias:
                    if pot[iid] is dia.pot_base[iid]:
                        pot[iid] = pot[iid].copy()
                    pot[iid][a:b] = 0.0
        faltas = sorted(dia.faltas_rede + faltas_inj)
        base = dia.base_w + extra
        if faltas:
            base = base.copy()
            for a, b in faltas:
                base[a:b] = 0.0
                for iid in pot:
                    if pot[iid] is dia.pot_base[iid]:
                        pot[iid] = pot[iid].copy()
                    pot[iid][a:b] = 0.0
        geral = base.astype(np.float32).copy()
        for p in pot.values():
            geral += p
        dia.pot, dia.geral, dia.faltas, dia.gabarito = pot, geral, faltas, linhas
        for fr in dia.faltas_rede:                     # faltas "naturais" da rede também entram no gabarito
            ts = lambda s: (t00 + dt.timedelta(seconds=int(s))).isoformat(sep=" ")
            dia.gabarito.append(dict(falha_id=f"R{dia.data.toordinal()}_{fr[0]}", tipo="falta_energia", alvo="rede", comodo="", canal_direto="",
                                     inicio=ts(fr[0]), fim=ts(fr[1]), efeito_inicio=ts(fr[0]), efeito_fim=ts(fr[1]), efetiva=True,
                                     alerta_de_aparelho=False, origem="rede", params="{}", dia=dia.data.isoformat(), _ef=fr))
        o = dia.data.toordinal()
        for ch, s in self.sensores.items():
            canal = self.c.canais[ch]
            if canal.geral and canal.fase:                     # medidor geral por fase
                real = dia.base_w * 0.5 + (extra if canal.fase == "A" else 0)   # carga de base dividida; consumo não explicado na fase A
                for iid, pw in pot.items():
                    f = self.c.instancias[iid].fase
                    if f == "AB":
                        real = real + 0.5 * pw
                    elif f == canal.fase:
                        real = real + pw
                if faltas:
                    real = real.copy()
                    for a, b in faltas:
                        real[a:b] = 0.0
                real = real.astype(np.float32)
            elif canal.geral:
                real = geral
            else:
                real = np.sum([pot[i] for i in canal.instancias], axis=0) if canal.instancias else np.zeros(N, np.float32)
            dia.mensagens[ch] = s.medir(real, dia.v_pu, faltas, o, desligado.get(ch))
        return dia

    # ------------------------------------------------------------------ relés (comandos)
    def comando(self, canal: str, acao: str, quando: dt.datetime) -> bool:
        c = self.c.canais.get(canal)
        if c is None or not c.sensor.get("tem_rele") or c.geral:
            return False
        lista = self.cortes.setdefault(canal, [])
        aberto = lista and lista[-1][1] is None
        if acao == "desligar" and not aberto:
            lista.append([quando, None])
        elif acao == "ligar" and aberto:
            lista[-1][1] = quando
        return True

    # ------------------------------------------------------------------ saídas
    def payload(self, canal: str, dia: Dia, k: int) -> dict:
        """Mensagem MQTT nº k do canal (contrato em docs/CONTRATO_MQTT.md). Não contém nenhum rótulo de falha."""
        c, m = self.c.canais[canal], dia.mensagens[canal]
        s = c.sensor
        d = dict(ts=iso(dia.t0 + int(m["t"][k])), medidor_id=c.medidor, canal=c.numero,
                 potencia_w=float(m["potencia_w"][k]), energia_wh=float(m["energia_wh"][k]))
        if s.get("mede_tensao"):
            d["tensao_v"] = float(m["tensao_v"][k])
        if s.get("mede_corrente"):
            d["corrente_a"] = float(m["corrente_a"][k])
        if s.get("tem_rele"):
            d["estado"] = "ligado" if bool(m["ligado"][k]) else "desligado"
        return d

    def telemetria(self, dia: Dia, rotulos: bool = False):
        """DataFrame com todas as mensagens do dia. Com rotulos=True acrescenta as colunas do gabarito (uso offline)."""
        import pandas as pd
        partes = []
        for ch, m in dia.mensagens.items():
            c = self.c.canais[ch]
            n = len(m["t"])
            df = pd.DataFrame(dict(ts=dia.t0 + m["t"], casa=self.c.casa, comodo=c.comodo, medidor_id=c.medidor, canal=c.numero,
                                   potencia_w=m["potencia_w"], energia_wh=m["energia_wh"],
                                   tensao_v=m["tensao_v"] if c.sensor.get("mede_tensao") else np.full(n, np.nan),
                                   corrente_a=m["corrente_a"] if c.sensor.get("mede_corrente") else np.full(n, np.nan),
                                   estado=np.where(m["ligado"], "ligado", "desligado") if c.sensor.get("tem_rele") else ""))
            if rotulos:
                an = np.zeros(n, np.int8); fid = np.full(n, "", dtype=object); ft = np.full(n, "", dtype=object); direto = np.zeros(n, np.int8)
                for g in dia.gabarito:
                    if not g["efetiva"] or not g["alerta_de_aparelho"]:
                        continue
                    if ch == g["canal_direto"] or c.geral:
                        a, b = g["_ef"]
                        sel = (m["t"] >= a) & (m["t"] < b)
                        an[sel] = 1; fid[sel] = g["falha_id"]; ft[sel] = g["tipo"]
                        if ch == g["canal_direto"]:
                            direto[sel] = 1
                df["anomalia"], df["falha_id"], df["falha_tipo"], df["canal_direto"] = an, fid, ft, direto
            partes.append(df)
        out = pd.concat(partes, ignore_index=True).sort_values(["ts", "medidor_id", "canal"], kind="stable").reset_index(drop=True)
        out.insert(1, "data_hora", pd.to_datetime(out["ts"], unit="s", utc=True).dt.tz_convert("America/Sao_Paulo").dt.strftime("%Y-%m-%d %H:%M:%S"))
        return out

    def verdade_minuto(self, dia: Dia):
        """Potência real média por minuto de cada aparelho (gabarito físico, só para arquivo)."""
        import pandas as pd
        d = {i: p.reshape(1440, 60).mean(axis=1).round(2) for i, p in dia.pot.items()}
        df = pd.DataFrame(d)
        df.insert(0, "_geral", dia.geral.reshape(1440, 60).mean(axis=1).round(2))
        df.insert(1, "_temperatura_externa", dia.clima.t_ext.round(2))
        df.insert(0, "ts", dia.t0 + np.arange(1440) * 60)
        return df

    def executar(self, dias: int, saida: str | Path | None = None, formato: str = "csv", publicador=None, ao_dia=None) -> dict:
        """Modo acelerado: simula `dias` dias e grava o dataset rotulado. Devolve o resumo."""
        import pandas as pd
        pasta = Path(saida) if saida else None
        if pasta:
            pasta.mkdir(parents=True, exist_ok=True)
        energia = {i: 0.0 for i in self.c.instancias}
        tele, verd, gab, total, n_msgs = [], [], [], 0.0, 0
        por_dia = []
        for _ in range(dias):
            dia = self.simular_dia()
            for i, p in dia.pot.items():
                energia[i] += float(p.sum()) / 3.6e6
            e_dia = float(dia.geral.sum()) / 3.6e6
            total += e_dia
            por_dia.append(dict(data=dia.data.isoformat(), kwh=round(e_dia, 3), tmax=round(dia.clima.tmax, 1)))
            gab += [{k: v for k, v in g.items() if k != "_ef"} for g in dia.gabarito]
            if pasta or publicador:
                df = self.telemetria(dia, rotulos=True)
                n_msgs += len(df)
                if pasta:
                    tele.append(df); verd.append(self.verdade_minuto(dia))
                if publicador:
                    for ch in dia.mensagens:
                        top = self.c.canais[ch].topico(self.c.casa)
                        for k in range(len(dia.mensagens[ch]["t"])):
                            publicador.publicar(top, self.payload(ch, dia, k))
            if ao_dia:
                ao_dia(dia)
        tipos: dict[str, float] = {}
        for i, e in energia.items():
            t = self.c.instancias[i].tipo
            tipos[t] = tipos.get(t, 0.0) + e
        medido = sum(e for i, e in energia.items() if self.c.instancias[i].canal)
        resumo = dict(cenario=self.c.nome, casa=self.c.casa, semente=self.semente, inicio=self.inicio.isoformat(), dias=dias,
                      kwh_total=round(total, 2), kwh_dia_medio=round(total / dias, 3), kwh_mes_equivalente=round(total / dias * 30.42, 1),
                      fracao_medida_por_canal_proprio=round(medido / total, 3) if total else 0,
                      kwh_por_tipo={k: round(v, 2) for k, v in sorted(tipos.items(), key=lambda x: -x[1])},
                      kwh_por_aparelho={k: round(v, 2) for k, v in sorted(energia.items(), key=lambda x: -x[1])},
                      n_falhas=len(self.injetor.falhas), n_linhas_gabarito=len(gab), n_mensagens=n_msgs, por_dia=por_dia)
        if pasta:
            t, v = pd.concat(tele, ignore_index=True), pd.concat(verd, ignore_index=True)
            col_rot = ["anomalia", "falha_id", "falha_tipo", "canal_direto"]
            if formato == "parquet":
                t.to_parquet(pasta / "dataset_rotulado.parquet", index=False)
                t.drop(columns=col_rot).to_parquet(pasta / "telemetria.parquet", index=False)
                v.to_parquet(pasta / "verdade_1min.parquet", index=False)
            else:
                t.to_csv(pasta / "dataset_rotulado.csv", index=False)
                t.drop(columns=col_rot).to_csv(pasta / "telemetria.csv", index=False)
                v.to_csv(pasta / "verdade_1min.csv", index=False)
            pd.DataFrame(gab).to_csv(pasta / "gabarito_falhas.csv", index=False)
            (pasta / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
        return resumo
