"""Linha de comando.

    python -m detector baselines --dados ..\\datasets\\v1 --saida ..\\resultados\\baselines_v1
    python -m detector baselines --perfis perfil1 --sementes 1 --modelos regra if     (rodada curta)
    python -m detector consolidar --saida ..\\resultados\\baselines_v1
    python -m detector ambiente                                                      (versões e hardware)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .modelos import MODELOS

AQUI = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="detector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("baselines", help="treina, calibra e testa os baselines")
    b.add_argument("--dados", default=str(AQUI.parent / "datasets" / "v1"))
    b.add_argument("--saida", default=str(AQUI.parent / "resultados" / "baselines_v1"))
    b.add_argument("--perfis", nargs="+", default=["perfil1", "perfil2", "perfil3"])
    b.add_argument("--sementes", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    b.add_argument("--modelos", nargs="+", default=list(MODELOS), choices=list(MODELOS))
    b.add_argument("--sem-onnx", action="store_true", help="não exporta nem confere o ONNX")
    b.add_argument("--epocas-max", type=int, default=None, help="limita as épocas das redes (só para teste rápido)")
    b.add_argument("--threads", type=int, default=None, help="threads do PyTorch")
    b.add_argument("--processos", type=int, default=1,
                   help="casas rodando ao mesmo tempo (cada uma com 1 thread); 1 = uma casa por vez")
    b.add_argument("--desenvolvimento", action="store_true",
                   help="não lê o teste; métricas na calibração (para escolhas de projeto)")
    c = sub.add_parser("consolidar", help="junta os resultados em tabelas")
    c.add_argument("--saida", default=str(AQUI.parent / "resultados" / "baselines_v1"))
    k = sub.add_parser("cascata", help="cascata OCSVM + regra → LSTM-AE com os modelos oficiais")
    k.add_argument("--dados", default=str(AQUI.parent / "datasets" / "v1"))
    k.add_argument("--baselines", default=str(AQUI.parent / "resultados" / "baselines_v1"))
    k.add_argument("--saida", default=str(AQUI.parent / "resultados" / "cascata_v1"))
    k.add_argument("--perfis", nargs="+", default=["perfil1", "perfil2", "perfil3"])
    k.add_argument("--sementes", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    k.add_argument("--processos", type=int, default=1)
    k.add_argument("--desenvolvimento", action="store_true", help="não lê o teste; métricas na calibração")
    k.add_argument("--filtro", default="ocsvm", help="EXPLORATÓRIO: modelo do estágio 1 (padrão ocsvm)")
    k.add_argument("--sem-regra", action="store_true", help="EXPLORATÓRIO: estágio 1 sem a regra")
    k.add_argument("--confirmador", default="lstm_ae", help="EXPLORATÓRIO: modelo do estágio 2 (padrão lstm_ae)")
    k.add_argument("--cache", default=None, help="pasta para guardar os scores (reaproveitados entre variantes)")
    e = sub.add_parser("empacotar", help="junta o que o Pi precisa para uma casa (modelos, limiares, orçamentos)")
    e.add_argument("perfil")
    e.add_argument("semente", type=int)
    e.add_argument("--baselines", default=str(AQUI.parent / "resultados" / "baselines_v1"))
    e.add_argument("--cascata", default=str(AQUI.parent / "resultados" / "cascata_v1"))
    e.add_argument("--orcamento", type=float, default=0.05, help="orçamento padrão de escalada ao LSTM-AE")
    e.add_argument("--saida", default=None, help="padrão: TCC/pi/pacotes/<perfil>_s<semente>")
    v = sub.add_parser("servico", help="serviço MQTT do Pi")
    v.add_argument("--pacote", nargs="+", default=[])
    v.add_argument("--carga", default=None, help="E3/E4: pacote-modelo para as casas virtuais do gerador de carga")
    v.add_argument("--prefixo", default="carga", help="nome das casas virtuais (padrão: carga)")
    v.add_argument("--controlador", action="store_true", help="E4: ajusta o orçamento pela carga (atraso)")
    v.add_argument("--atraso-max", type=float, default=2.0, help="E4: atraso p95 tolerado, em segundos")
    v.add_argument("--sem-aquecer", action="store_true", help="E3: casas de carga começam frias (LSTM-AE só depois de 1 h)")
    v.add_argument("--broker", default="localhost")
    v.add_argument("--porta", type=int, default=1883)
    v.add_argument("--orcamento", type=float, default=None)
    v.add_argument("--registro", default=None, help="JSONL com alertas e estado")
    r = sub.add_parser("reproduzir", help="passa uma partição gravada pela versão ao vivo (sem MQTT)")
    r.add_argument("--pacote", required=True)
    r.add_argument("--dados", required=True, help="pasta perfilN/semente_S")
    r.add_argument("--particao", default="teste")
    r.add_argument("--orcamento", type=float, nargs="+", default=[None])
    c2 = sub.add_parser("campanha", help="cenários com dados novos (simulador) na versão ao vivo")
    c2.add_argument("--pacotes", default=str(AQUI.parent / "pi" / "pacotes"))
    c2.add_argument("--saida", default=str(AQUI.parent / "resultados" / "campanha_v1"))
    c2.add_argument("--perfis", nargs="+", default=["perfil1", "perfil2", "perfil3"])
    c2.add_argument("--sementes", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    c2.add_argument("--dias", type=int, default=28)
    c2.add_argument("--cenarios", nargs="+", default=None)
    c2.add_argument("--processos", type=int, default=1)
    e5 = sub.add_parser("e5", help="analisa uma sessão ao vivo (registro do simulador)")
    e5.add_argument("registro", nargs="+")
    e5.add_argument("--saida", default=None, help="pasta para os CSVs (padrão: ao lado do registro)")
    e5.add_argument("--desde", default=None, help="relógio simulado em que o detector foi ligado, ex. '2026-01-06 05:00'")
    cu = sub.add_parser("custo", help="E2: latência por inferência de cada modelo (rodar no Pi)")
    cu.add_argument("--casa", required=True, help="pasta resultados/baselines_v1/perfilN/semente_S")
    cu.add_argument("--dados", required=True, help="pasta datasets/v1/perfilN/semente_S")
    cu.add_argument("--saida", default="e2_resultado.json")
    cu.add_argument("--repeticoes", type=int, default=2000)
    e3 = sub.add_parser("e3", help="analisa o teste de carga (E3/E4): pasta do Pi + pasta do PC")
    e3.add_argument("pasta_pi")
    e3.add_argument("pasta_pc")
    e3.add_argument("--saida", default=None)
    sub.add_parser("ambiente", help="mostra versões e hardware")
    a = ap.parse_args(argv)

    if a.cmd == "e3":
        from .e3 import analisar
        r = analisar(a.pasta_pi, a.pasta_pc, a.saida)
        print(json.dumps(r["resumo"], ensure_ascii=False, indent=1))
        print(f"tabelas em {r['saida']}")
        return 0
    if a.cmd == "custo":
        from .custo import medir
        r = medir(a.casa, a.dados, repeticoes=a.repeticoes)
        Path(a.saida).write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
        for m, v in r["modelos"].items():
            print(f"{m:8s} mediana={v['us_mediana']:8.1f} us  p99={v['us_p99']:8.1f} us  onnx={v['kb_por_canal']:7.1f} KB/canal")
        print(f"atributos (vetorizado): {r['ms_atributos_por_minuto_casa_vetorizado']:.3f} ms/min  "
              f"memória do processo: {r['mb_processo']} MB  Pi depois: {r['pi_depois']}")
        return 0

    if a.cmd == "ambiente":
        import os
        from .experimento import _versoes
        v = _versoes()
        v["nucleos_logicos"] = os.cpu_count()
        try:
            import psutil
            v["memoria_gb"] = round(psutil.virtual_memory().total / 2**30, 1)
        except ImportError:
            pass
        try:
            import torch
            v["cuda"] = torch.cuda.is_available()
            v["torch_threads"] = torch.get_num_threads()
        except ImportError:
            pass
        print(json.dumps(v, indent=1, ensure_ascii=False))
        return 0

    if a.cmd == "empacotar":
        from .aovivo import empacotar
        saida = Path(a.saida) if a.saida else AQUI.parent / "pi" / "pacotes" / f"{a.perfil}_s{a.semente}"
        p = empacotar(Path(a.baselines), Path(a.cascata), a.perfil, a.semente, saida, a.orcamento)
        n = sum(1 for _ in p.rglob("*.onnx"))
        print(f"pacote pronto em {p} ({n} modelos .onnx, orçamento padrão {a.orcamento})")
        return 0
    if a.cmd == "servico":
        from .servico import Servico
        if not a.pacote and not a.carga:
            ap.error("servico: informe --pacote e/ou --carga")
        Servico(a.pacote, a.broker, a.porta, a.orcamento, a.registro, carga=a.carga, prefixo=a.prefixo,
                controlador=a.controlador, atraso_max=a.atraso_max, aquecer=not a.sem_aquecer).rodar()
        return 0
    if a.cmd == "reproduzir":
        from .servico import reproduzir
        for b in a.orcamento:
            print(json.dumps(reproduzir(a.pacote, a.dados, a.particao, b), ensure_ascii=False), flush=True)
        return 0
    if a.cmd == "e5":
        from .e5 import analisar
        import pandas as pd
        for reg in a.registro:
            r = analisar(reg, desde=a.desde)
            out = Path(a.saida) if a.saida else Path(reg).with_suffix("")
            out.mkdir(parents=True, exist_ok=True)
            r["eventos"].to_csv(out / "e5_eventos.csv", index=False)
            r["alertas"].to_csv(out / "e5_alertas.csv", index=False)
            if len(r["por_tipo"]):
                r["por_tipo"].to_csv(out / "e5_por_tipo.csv", index=False)
            (out / "e5_resumo.json").write_text(json.dumps(r["resumo"], indent=1, ensure_ascii=False, default=float))
            print(json.dumps(r["resumo"], ensure_ascii=False, default=float))
            with pd.option_context("display.width", 200, "display.max_columns", 20):
                print(r["eventos"].drop(columns=["canais_alerta"]).to_string(index=False))
        return 0
    if a.cmd == "campanha":
        from .campanha import CENARIOS, consolidar as consolidar_campanha, rodar_casa as rc, rodar_casa_isolada
        cen = a.cenarios or CENARIOS
        casas = sorted([(p, s) for p in a.perfis for s in a.sementes], reverse=True)
        tarefas = [(Path(a.pacotes), p, s, a.dias, Path(a.saida), cen) for p, s in casas]
        t0 = time.perf_counter()
        if a.processos > 1:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            with ProcessPoolExecutor(max_workers=a.processos) as ex:
                for f in as_completed([ex.submit(rodar_casa_isolada, t) for t in tarefas]):
                    print(f.result(), flush=True)
        else:
            for t in tarefas:
                rc(*t, log=lambda m: print(m, flush=True))
        consolidar_campanha(Path(a.saida))
        print(f"pronto em {(time.perf_counter() - t0) / 60:.1f} min; resultados em {a.saida}", flush=True)
        return 0
    if a.cmd == "cascata":
        from .cascata import consolidar_cascata, rodar_casa_cascata, rodar_casa_cascata_isolada
        Path(a.saida).mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        casas = sorted([(p, s) for p in a.perfis for s in a.sementes], reverse=True)
        tarefas = [(Path(a.dados), Path(a.baselines), p, s, Path(a.saida), not a.desenvolvimento) for p, s in casas]
        kw = dict(filtro=a.filtro, com_regra=not a.sem_regra, confirmador=a.confirmador,
                  cache=Path(a.cache) if a.cache else None)
        if a.processos > 1:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            from functools import partial
            with ProcessPoolExecutor(max_workers=a.processos) as ex:
                for f in as_completed([ex.submit(partial(rodar_casa_cascata_isolada, **kw), t) for t in tarefas]):
                    print(f.result(), flush=True)
        else:
            for t in tarefas:
                rodar_casa_cascata(*t, log=lambda m: print(m, flush=True), **kw)
        if not a.desenvolvimento:
            tab = consolidar_cascata(Path(a.saida))["cascata"]
            import pandas as pd
            with pd.option_context("display.width", 200, "display.max_columns", 30):
                print(tab[tab["perfil"] == "todos"][["orcamento", "escalados_mean", "f1_mean", "f1_std", "revocacao_mean",
                                                    "fp_por_dia_mean", "revocacao_estagio1_mean",
                                                    "custo_relativo_ao_lstm_mean"]].round(3).to_string(index=False))
        print(f"pronto em {(time.perf_counter() - t0) / 60:.1f} min; resultados em {a.saida}", flush=True)
        return 0

    from .experimento import consolidar, rodar_casa
    if a.cmd == "consolidar":
        t = consolidar(Path(a.saida))
        import pandas as pd
        with pd.option_context("display.width", 200, "display.max_columns", 30):
            print(t["perfil_modelo"][["perfil", "modelo", "sementes", "auc_pr_evento_mean", "f1_mean", "f1_std",
                                      "precisao_mean", "revocacao_mean", "fp_por_dia_mean",
                                      "atraso_mediana_min_mean"]].round(3).to_string(index=False))
        return 0

    opcoes = {}
    for rede in ("ae", "lstm_ae"):
        opcoes[rede] = {k: v for k, v in {"epocas_max": a.epocas_max, "threads": a.threads}.items() if v is not None}
    Path(a.saida).mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    casas = [(p, s) for p in a.perfis for s in a.sementes]
    if a.processos > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        from .experimento import rodar_casa_isolada
        casas.sort(key=lambda c: c[0], reverse=True)            # casas maiores (perfil 3) primeiro
        tarefas = [(Path(a.dados), p, s, a.modelos, Path(a.saida), not a.sem_onnx, opcoes, not a.desenvolvimento)
                   for p, s in casas]
        with ProcessPoolExecutor(max_workers=a.processos) as ex:
            for f in as_completed([ex.submit(rodar_casa_isolada, t) for t in tarefas]):
                print(f.result(), flush=True)
    else:
        for perfil, s in casas:
            rodar_casa(Path(a.dados), perfil, s, a.modelos, Path(a.saida), onnx=not a.sem_onnx, opcoes=opcoes,
                       log=lambda m: print(m, flush=True), avaliar_teste=not a.desenvolvimento)
    if not a.desenvolvimento:
        consolidar(Path(a.saida))
    print(f"pronto em {(time.perf_counter() - t0) / 60:.1f} min; resultados em {a.saida}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
