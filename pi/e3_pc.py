"""E3/E4 — roteiro do PC (rodar no notebook, com o venv do simulador, na pasta TCC\\simulador):

    .\\.venv\\Scripts\\python ..\\pi\\e3_pc.py --pi 192.168.0.57          (1ª rodada: uma mensagem por canal a cada 10 s)
    .\\.venv\\Scripts\\python ..\\pi\\e3_pc.py --pi 192.168.0.57 --fiel   (2ª rodada: cadência original do dataset)

Antes, no Pi: `bash e3_pi.sh` (deixa o detector em modo de carga ouvindo o MQTT). Este roteiro faz, para cada
rodada: manda um comando ao detector (marca, zera as casas de carga, fixa o orçamento, liga/desliga o controlador),
roda a rampa do gerador de carga (casas virtuais perfil3, 31 canais cada, uma mensagem por canal a cada 10 s) e
espera 1 min. Rodadas da 1ª rodada (~1 h 50 min no total):
  E3_b1    orçamento 100 % (LSTM-AE em todo minuto-canal)
  E3_b005  orçamento 5 % (padrão da cascata)
  E3_b0    orçamento 0 (só estágio 1)
  E4_ctrl  começa em 100 % com o controlador de carga ligado (desce o orçamento se o atraso p95 passar de 2 s)
Com --fiel (~1 h 10 min, escolha do Kleber): 4.000 casas desde o início em todas; E3f_b1 (8 min), E3f_b005 (30 min)
e E4f_ctrl (controlador, atraso máx. 30 s, 30 min). E3f_b0 só se pedido em --rodadas.
Saída: `registros/e3/<rodada>_pK.csv` (um por gerador, por segundo) e `registros/e3/roteiro.json` (horários).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulador"))   # casasim sem precisar instalar
from casasim.carga import executar_em_processos
from casasim.mqtt import Publicador

TOPICO_COMANDO = "casa/sistema/detector/comando"
RAMPA = "0:50,2:100,4:200,6:400,8:600,10:800,12:1000,14:1300,16:1600,18:2000,20:2500,22:3000"
# modo fiel (2ª rodada): casas com a cadência real do perfil 3 (~0,77 msg/s por casa). Sobe até 4.000 casas em 6 min e
# MANTÉM até o fim (40 min), para as casas "envelhecerem" (nos primeiros ~30 min de vida a casa escala muito mais,
# porque as janelas dos atributos ainda estão incompletas) e medir o regime.
RAMPA_FIEL = "0:4000"     # versão curta (pedido do Kleber): 4.000 casas desde o início; a rampa já foi medida na 1ª rodada
RODADAS_FIEL = {          # duração própria: b = 100 % e b = 0 não dependem da "idade" da casa; b = 5 % e o E4 sim
    "E3f_b1": {"orcamento": 1.0, "controlador": False, "_min": 8},
    "E3f_b005": {"orcamento": 0.05, "controlador": False, "_min": 30},
    "E4f_ctrl": {"orcamento": 1.0, "controlador": True, "atraso_max": 30.0, "_min": 30},
    "E3f_b0": {"orcamento": 0.0, "controlador": False, "_min": 8},       # fora do padrão (já validado na 1ª rodada)
    # E6 (CPU do Pi limitada a 1,5 GHz por software; rodar só com --rodadas E6_b1 E6_ctrl):
    "E6_b1": {"orcamento": 1.0, "controlador": False, "_min": 6},
    "E6_ctrl": {"orcamento": 1.0, "controlador": True, "atraso_max": 30.0, "_min": 22},
}
RODADAS = {
    "E3_b1": {"orcamento": 1.0, "controlador": False},
    "E3_b005": {"orcamento": 0.05, "controlador": False},
    "E3_b0": {"orcamento": 0.0, "controlador": False},
    "E4_ctrl": {"orcamento": 1.0, "controlador": True, "atraso_max": 2.0},
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pi", required=True, help="IP do Pi (broker MQTT)")
    ap.add_argument("--dataset", default="../datasets/v1/perfil3/semente_1")
    ap.add_argument("--fiel", action="store_true", help="2ª rodada: casas reenviam o dataset com a cadência original")
    ap.add_argument("--rampa", default=None, help='"minuto:casas,..." (padrão depende do modo)')
    ap.add_argument("--duracao", type=float, default=None, help="segundos de cada rodada (padrão: até o fim da rampa + 2 min)")
    ap.add_argument("--intervalo", type=float, default=10.0, help="segundos entre mensagens de cada canal")
    ap.add_argument("--processos", type=int, default=8, help="geradores em paralelo")
    ap.add_argument("--rodadas", nargs="+", default=None, choices=list(RODADAS) + list(RODADAS_FIEL))
    ap.add_argument("--pausa", type=float, default=60.0, help="segundos parados entre rodadas")
    ap.add_argument("--saida", default="registros/e3")
    a = ap.parse_args(argv)
    a.rampa = a.rampa or (RAMPA_FIEL if a.fiel else RAMPA)
    tabela = RODADAS_FIEL if a.fiel else RODADAS
    a.rodadas = a.rodadas or ([r for r in tabela if r != "E3f_b0" and not r.startswith("E6")] if a.fiel else list(tabela))
    dur_padrao = max(float(x.split(":")[0]) for x in a.rampa.split(",")) * 60 + 120
    if a.fiel and a.saida == "registros/e3":
        a.saida = "registros/e3_fiel"
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    pub = Publicador(a.pi, 1883, client_id=f"casasim-roteiro-{int(time.time())}", assinar=False)
    if not pub.ativo:
        raise SystemExit(f"sem conexão com o broker em {a.pi}: {pub.erro}")
    log = {"pi": a.pi, "dataset": a.dataset, "rampa": a.rampa, "intervalo_s": None if a.fiel else a.intervalo,
           "modo": "fiel" if a.fiel else "intervalo", "processos": a.processos, "rodadas": []}
    for i, nome in enumerate(a.rodadas, 1):
        conf = dict({**RODADAS, **RODADAS_FIEL}[nome])
        dur = a.duracao or (conf.pop("_min", None) or 0) * 60 or dur_padrao
        conf.pop("_min", None)
        cmd = {"marca": nome, "reset": True, **conf}
        pub.publicar(TOPICO_COMANDO, cmd, qos=1)
        print(f"\n=== {nome} ({i}/{len(a.rodadas)}) {time.strftime('%H:%M:%S')} comando: {json.dumps(cmd)}", flush=True)
        time.sleep(5)
        t0 = time.time()
        res = executar_em_processos(a.dataset, a.pi, 1883, a.intervalo, a.rampa, dur, prefixo=f"carga{i}x",
                                    processos=a.processos, registro=str(saida / f"{nome}.csv"), fiel=a.fiel)
        r = {"rodada": nome, "comando": cmd, "inicio": t0, "fim": time.time(),
             "enviadas": sum(x["enviadas"] for x in res), "geradores": res}
        log["rodadas"].append(r)
        (saida / "roteiro.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"=== {nome} terminou: {r['enviadas']} mensagens enviadas em {r['fim'] - t0:.0f} s", flush=True)
        time.sleep(a.pausa)
    pub.publicar(TOPICO_COMANDO, {"marca": "fim", "reset": True}, qos=1)
    time.sleep(1)
    pub.fechar()
    print(f"\nPRONTO. Arquivos em {saida.resolve()}", flush=True)


if __name__ == "__main__":
    main()
