"""Gerador de carga para os experimentos de capacidade (E3/E4).

Reproduz no MQTT a telemetria gravada de um dataset congelado (partição de teste, SEM o gabarito), multiplicada
em N casas virtuais (carga1, carga2, ...). Cada canal virtual envia uma mensagem a cada `intervalo_s` segundos de
relógio, com `ts` = hora real do envio, para medir até quantos canais/mensagens por segundo o Raspberry Pi aguenta.

Rampa: lista "minuto:casas", ex. "0:1,2:5,4:10,6:20" = 1 casa no início, 5 casas a partir do minuto 2, etc.
Registro: CSV com uma linha por segundo (casas ativas, canais ativos, mensagens enviadas, atraso do laço).
"""
from __future__ import annotations
import csv
import datetime as dt
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .datasets import carregar
from .mqtt import Publicador


def ler_rampa(texto: str) -> list[tuple[float, int]]:
    passos = []
    for item in texto.split(","):
        m, n = item.strip().split(":")
        passos.append((float(m) * 60.0, int(n)))
    passos.sort()
    if not passos or passos[0][0] > 0:
        passos.insert(0, (0.0, passos[0][1] if passos else 1))
    return passos


def casas_em(rampa: list[tuple[float, int]], t: float) -> int:
    n = rampa[0][1]
    for t0, k in rampa:
        if t >= t0:
            n = k
    return n


@dataclass
class Fluxo:
    comodo: str
    medidor: str
    canal: int
    campos: dict            # nome -> array de valores gravados (sem gabarito)


class GeradorCarga:
    def __init__(self, pasta_dataset: str | Path, publicador: Publicador, intervalo_s: float = 10.0, rampa: str = "0:1",
                 particao: str = "teste", prefixo: str = "carga", registro: str | Path | None = None, inicio_mensagem: int = 0):
        df = carregar(pasta_dataset, particao, com_rotulos=False)
        df = df.sort_values("ts")
        self.fluxos: list[Fluxo] = []
        for (comodo, med, can), g in df.groupby(["comodo", "medidor_id", "canal"], sort=True):
            campos = {"potencia_w": g["potencia_w"].to_numpy(float), "energia_wh": g["energia_wh"].to_numpy(float)}
            for opc in ("tensao_v", "corrente_a"):
                v = g[opc].to_numpy(float)
                if not np.isnan(v).all():
                    campos[opc] = v
            if "estado" in g and (g["estado"] != "").any():
                campos["estado"] = g["estado"].to_numpy(str)
            self.fluxos.append(Fluxo(comodo, med, int(can), campos))
        self.pub, self.intervalo, self.rampa = publicador, float(intervalo_s), ler_rampa(rampa)
        self.prefixo, self.registro = prefixo, Path(registro) if registro else None
        self.inicio_msg = int(inicio_mensagem)
        self.linhas: list[dict] = []

    @property
    def canais_por_casa(self) -> int:
        return len(self.fluxos)

    def payload(self, f: Fluxo, k: int) -> dict:
        i = k % len(f.campos["potencia_w"])
        d = dict(ts=dt.datetime.now().astimezone().isoformat(timespec="milliseconds"), medidor_id=f.medidor, canal=f.canal)
        for nome, v in f.campos.items():
            d[nome] = str(v[i]) if nome == "estado" else float(v[i])
        return d

    def executar(self, duracao_s: float, relogio=time.monotonic, dormir=time.sleep) -> dict:
        """Envia durante `duracao_s` segundos. As mensagens de cada canal são espalhadas dentro do intervalo
        (fase fixa por canal), como dispositivos reais que não sincronizam entre si."""
        t0 = relogio()
        prox: dict[tuple[int, int], float] = {}
        cont: dict[tuple[int, int], int] = {}
        rng = np.random.default_rng(0)
        enviadas_total, seg_atual, env_seg, atraso_max = 0, 0, 0, 0.0
        while True:
            agora = relogio() - t0
            if agora >= duracao_s:
                break
            n_casas = casas_em(self.rampa, agora)
            for c in range(1, n_casas + 1):
                for j, f in enumerate(self.fluxos):
                    chave = (c, j)
                    if chave not in prox:
                        prox[chave] = agora + float(rng.uniform(0, self.intervalo))
                        cont[chave] = self.inicio_msg + int(rng.integers(0, len(f.campos["potencia_w"])))
                    if prox[chave] <= agora:
                        atraso_max = max(atraso_max, agora - prox[chave])
                        self.pub.publicar(f"casa/{self.prefixo}{c}/{f.comodo}/{f.medidor}/telemetria", self.payload(f, cont[chave]))
                        cont[chave] += 1
                        prox[chave] += self.intervalo
                        enviadas_total += 1; env_seg += 1
            s = int(agora)
            if s != seg_atual:
                self.linhas.append(dict(segundo=seg_atual, casas=n_casas, canais=n_casas * len(self.fluxos), enviadas=env_seg,
                                        taxa_alvo_msg_s=round(n_casas * len(self.fluxos) / self.intervalo, 2), atraso_max_s=round(atraso_max, 3)))
                seg_atual, env_seg, atraso_max = s, 0, 0.0
            dormir(0.005)
        if self.registro:
            self.registro.parent.mkdir(parents=True, exist_ok=True)
            with open(self.registro, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(self.linhas[0]) if self.linhas else ["segundo"])
                w.writeheader(); w.writerows(self.linhas)
        return dict(enviadas=enviadas_total, segundos=round(relogio() - t0, 1), canais_por_casa=len(self.fluxos),
                    casas_max=max(k for _, k in self.rampa), intervalo_s=self.intervalo, registro=str(self.registro) if self.registro else None)


class GeradorFiel:
    """Modo FIEL (E3/E4, 2ª rodada): cada casa virtual reenvia o dataset na ordem e com os intervalos ORIGINAIS entre
    as mensagens (todos os canais da casa alinhados, como na casa simulada), começando num ponto sorteado da partição;
    `ts` = hora real do envio. Ao contrário do modo por intervalo (`GeradorCarga`), a casa virtual tem o
    comportamento de uma casa de verdade, então a fração escalada pela cascata é a do uso normal."""

    def __init__(self, pasta_dataset: str | Path, publicador: Publicador, rampa: str = "0:1", particao: str = "teste",
                 prefixo: str = "carga", registro: str | Path | None = None, semente: int = 0):
        df = carregar(pasta_dataset, particao, com_rotulos=False).sort_values("ts", kind="stable").reset_index(drop=True)
        self.ts = (df["ts"].to_numpy(np.int64) - int(df["ts"].iloc[0])).astype(float)
        self.sufixo = (("/" + df["comodo"].astype(str) + "/" + df["medidor_id"].astype(str) + "/telemetria")
                       .to_numpy(object))
        self.med = df["medidor_id"].astype(str).to_numpy(object)
        self.can = df["canal"].to_numpy(np.int64)
        self.pot = df["potencia_w"].to_numpy(float)
        self.ene = df["energia_wh"].to_numpy(float)
        self.opc = {o: df[o].to_numpy(float) for o in ("tensao_v", "corrente_a") if o in df and not df[o].isna().all()}
        self.est = (df["estado"].fillna("").astype(str).to_numpy(object)
                    if "estado" in df and (df["estado"].fillna("") != "").any() else None)
        self.canais_por_casa = int(df.groupby(["medidor_id", "canal"]).ngroups)
        self.pub, self.rampa, self.prefixo = publicador, ler_rampa(rampa), prefixo
        self.registro = Path(registro) if registro else None
        self.rng = np.random.default_rng(semente)
        self.linhas_seg: list[dict] = []
        # casas começam em pontos sorteados até 2/3 da partição (sobra muito mais que a duração de uma rodada)
        self.max_inicio = int(np.searchsorted(self.ts, self.ts[-1] * 2 / 3))

    def executar(self, duracao_s: float, relogio=time.monotonic, dormir=time.sleep) -> dict:
        t0 = relogio()
        casas: list[list] = []                  # [ponteiro, t_inicio_relogio, ts0_dataset]
        enviadas_total, seg_atual, env_seg, atraso_max = 0, 0, 0, 0.0
        n = len(self.ts)
        while True:
            agora = relogio() - t0
            if agora >= duracao_s:
                break
            alvo = casas_em(self.rampa, agora)
            while len(casas) < alvo:
                i0 = int(self.rng.integers(0, self.max_inicio))
                casas.append([i0, agora, self.ts[i0]])
            for c, st in enumerate(casas, 1):
                p, tini, ts0 = st
                while p < n and tini + (self.ts[p] - ts0) <= agora:
                    atraso_max = max(atraso_max, agora - (tini + self.ts[p] - ts0))
                    d = {"ts": dt.datetime.now().astimezone().isoformat(timespec="milliseconds"),
                         "medidor_id": self.med[p], "canal": int(self.can[p]), "potencia_w": float(self.pot[p]),
                         "energia_wh": float(self.ene[p])}
                    for o, v in self.opc.items():
                        if v[p] == v[p]:
                            d[o] = float(v[p])
                    if self.est is not None and self.est[p]:
                        d["estado"] = self.est[p]
                    self.pub.publicar(f"casa/{self.prefixo}{c}{self.sufixo[p]}", d)
                    p += 1
                    enviadas_total += 1
                    env_seg += 1
                st[0] = p
            s = int(agora)
            if s != seg_atual:
                self.linhas_seg.append(dict(segundo=seg_atual, casas=len(casas), canais=len(casas) * self.canais_por_casa,
                                            enviadas=env_seg, taxa_alvo_msg_s="", atraso_max_s=round(atraso_max, 3)))
                seg_atual, env_seg, atraso_max = s, 0, 0.0
            dormir(0.005)
        if self.registro:
            self.registro.parent.mkdir(parents=True, exist_ok=True)
            with open(self.registro, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(self.linhas_seg[0]) if self.linhas_seg else ["segundo"])
                w.writeheader(); w.writerows(self.linhas_seg)
        return dict(enviadas=enviadas_total, segundos=round(relogio() - t0, 1), canais_por_casa=self.canais_por_casa,
                    casas_max=max(k for _, k in self.rampa), modo="fiel",
                    registro=str(self.registro) if self.registro else None)


def dividir_rampa(texto: str, partes: int, k: int) -> str:
    """Parte k (0..partes-1) de uma rampa: cada passo de N casas vira N//partes (+1 nas primeiras N%partes)."""
    return ",".join(f"{t / 60.0:g}:{n // partes + (1 if k < n % partes else 0)}" for t, n in ler_rampa(texto))


def _um_processo(args: tuple) -> dict:
    pasta, host, porta, intervalo, rampa, duracao, prefixo, registro = args[:8]
    fiel = len(args) > 8 and args[8]
    import os
    # client_id único: dois clientes MQTT com o mesmo id derrubam um ao outro no broker (mensagens perdidas)
    pub = Publicador(host, porta, client_id=f"casasim-carga-{prefixo}-{os.getpid()}", assinar=False)
    try:
        if fiel:
            ger = GeradorFiel(pasta, pub, rampa, prefixo=prefixo, registro=registro, semente=__import__('zlib').crc32(prefixo.encode()))
        else:
            ger = GeradorCarga(pasta, pub, intervalo, rampa, prefixo=prefixo, registro=registro)
        r = ger.executar(duracao)
        r["prefixo"], r["mqtt"] = prefixo, bool(pub.ativo)
        return r
    finally:
        pub.fechar()


def executar_em_processos(pasta: str, host: str, porta: int, intervalo: float, rampa: str, duracao: float,
                          prefixo: str = "carga", processos: int = 1, registro: str | None = None,
                          fiel: bool = False) -> list[dict]:
    """Vários geradores em paralelo (um processo cada), para passar do limite de um processo Python.
    O processo k usa o prefixo `{prefixo}{k}-` (casas carga1-1, carga1-2, ..., carga2-1, ...) e a sua parte da rampa;
    cada um grava o seu CSV (`_p{k}` no nome)."""
    if processos <= 1:
        return [_um_processo((pasta, host, porta, intervalo, rampa, duracao, prefixo, registro, fiel))]
    from concurrent.futures import ProcessPoolExecutor
    tarefas = []
    for k in range(processos):
        reg = None
        if registro:
            r = Path(registro)
            reg = str(r.with_name(f"{r.stem}_p{k + 1}{r.suffix}"))
        tarefas.append((pasta, host, porta, intervalo, dividir_rampa(rampa, processos, k), duracao,
                        f"{prefixo}{k + 1}-", reg, fiel))
    with ProcessPoolExecutor(max_workers=processos) as ex:
        return list(ex.map(_um_processo, tarefas))
