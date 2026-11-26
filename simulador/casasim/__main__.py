"""Linha de comando:  python -m casasim simular|web|validar ..."""
from __future__ import annotations
import argparse
import os
import json
import time


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="casasim", description="Simulador de consumo de energia de uma casa brasileira (TCC).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("simular", help="modo acelerado: gera o dataset rotulado")
    s.add_argument("--cenario", default="perfil1"); s.add_argument("--dias", type=int, default=30)
    s.add_argument("--inicio", default="2026-01-05"); s.add_argument("--semente", type=int, default=42)
    s.add_argument("--falhas-por-semana", type=float, default=0.0); s.add_argument("--saida", default=None)
    s.add_argument("--formato", choices=["csv", "parquet"], default="csv")
    s.add_argument("--mqtt", default=None, help="host do broker; publica todas as mensagens sem esperar o relógio")
    s.add_argument("--intervalo-sensor", type=int, default=None, help="força o intervalo de envio (s) de todos os medidores")
    r = sub.add_parser("tempo-real", help="publica no MQTT no ritmo do relógio (sem painel)")
    r.add_argument("--cenario", default="perfil1"); r.add_argument("--inicio", default="2026-01-05"); r.add_argument("--hora", default="06:00")
    r.add_argument("--semente", type=int, default=42); r.add_argument("--velocidade", type=float, default=1.0)
    r.add_argument("--mqtt", default="localhost"); r.add_argument("--porta", type=int, default=1883)
    r.add_argument("--registro", default=None, help="JSONL das falhas/alertas (padrão: registros/aovivo_<cenario>_<data>.jsonl)")
    w = sub.add_parser("web", help="abre o painel (montagem, dashboard, planta, falhas)")
    w.add_argument("--porta", type=int, default=8000); w.add_argument("--host", default="127.0.0.1")
    g = sub.add_parser("carga", help="gerador de carga para E3/E4: reenvia um dataset congelado em N casas virtuais")
    g.add_argument("dataset", help="pasta perfilN/semente_S do dataset congelado")
    g.add_argument("--mqtt", default="localhost"); g.add_argument("--porta", type=int, default=1883)
    g.add_argument("--intervalo", type=float, default=10.0, help="segundos entre mensagens de cada canal virtual")
    g.add_argument("--rampa", default="0:1", help='"minuto:casas,..." ex. "0:1,2:5,4:10"')
    g.add_argument("--duracao", type=float, default=600, help="segundos")
    g.add_argument("--registro", default=None, help="CSV por segundo (padrão: registros/carga_<data>.csv)")
    g.add_argument("--prefixo", default="carga", help="nome das casas virtuais (padrão: carga)")
    g.add_argument("--processos", type=int, default=1, help="geradores em paralelo (um processo cada; divide a rampa)")
    g.add_argument("--fiel", action="store_true", help="cada casa reenvia o dataset na ordem e com os intervalos originais")
    v = sub.add_parser("validar", help="confere a montagem de um cenário")
    v.add_argument("cenario")
    a = ap.parse_args(argv)

    if a.cmd == "simular":
        from .motor import Simulador
        from .mqtt import Publicador
        sim = Simulador(a.cenario, a.semente, a.inicio, a.falhas_por_semana, a.dias, intervalo_sensor_s=a.intervalo_sensor)
        pub = Publicador(a.mqtt, casa=sim.c.casa) if a.mqtt else None
        t = time.time()
        res = sim.executar(a.dias, a.saida, a.formato, pub)
        res.pop("por_dia"); res.pop("kwh_por_aparelho")
        print(json.dumps(res, ensure_ascii=False, indent=1))
        print(f"{a.dias} dias simulados em {time.time() - t:.1f} s" + (f"; arquivos em {a.saida}" if a.saida else ""))
    elif a.cmd == "tempo-real":
        from .motor import Simulador
        from .mqtt import Publicador
        from .tempo_real import ExecucaoTempoReal
        sim = Simulador(a.cenario, a.semente, a.inicio)
        pub = Publicador(a.mqtt, a.porta, sim.c.casa)
        print("MQTT:", "conectado" if pub.ativo else f"sem broker ({pub.erro})")
        reg = a.registro or f"registros/aovivo_{sim.c.nome}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        ex = ExecucaoTempoReal(sim, a.velocidade, pub, a.hora, registro=reg)
        print("registro:", reg)
        ex.iniciar()
        try:
            while True:
                time.sleep(5)
                e = ex.estado()
                print(e["agora"], f"{e['total_real_w']:.0f} W", f"{e['mqtt']['enviadas']} mensagens")
        except KeyboardInterrupt:
            ex.parar()
    elif a.cmd == "carga":
        from .carga import GeradorCarga, executar_em_processos
        from .mqtt import Publicador
        if a.processos > 1 or a.fiel:
            reg = a.registro or f"registros/carga_{time.strftime('%Y%m%d_%H%M%S')}.csv"
            print(f"{a.processos} geradores em paralelo; rampa total {a.rampa}", flush=True)
            for r in executar_em_processos(a.dataset, a.mqtt, a.porta, a.intervalo, a.rampa, a.duracao, a.prefixo,
                                           a.processos, reg, fiel=a.fiel):
                print(json.dumps(r, ensure_ascii=False), flush=True)
            return
        pub = Publicador(a.mqtt, a.porta, client_id=f"casasim-carga-{a.prefixo}-{os.getpid()}", assinar=False)
        print("MQTT:", "conectado" if pub.ativo else f"sem broker ({pub.erro}); as mensagens ficam só na memória")
        reg = a.registro or f"registros/carga_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        ger = GeradorCarga(a.dataset, pub, a.intervalo, a.rampa, prefixo=a.prefixo, registro=reg)
        print(f"{ger.canais_por_casa} canais por casa; rampa {ger.rampa}")
        try:
            print(json.dumps(ger.executar(a.duracao), ensure_ascii=False))
        finally:
            pub.fechar()
    elif a.cmd == "web":
        import uvicorn
        uvicorn.run("casasim.web.app:app", host=a.host, port=a.porta, log_level="warning")
    else:
        from .dados import carregar_cenario, validar
        print(json.dumps(validar(carregar_cenario(a.cenario)), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
