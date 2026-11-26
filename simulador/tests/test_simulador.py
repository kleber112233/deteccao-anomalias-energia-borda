"""Testes do simulador. Rodar com:  python -m pytest -q"""
import datetime as dt
import json
import sys
from pathlib import Path
import numpy as np
import pytest
from casasim import Simulador, dados
from casasim.aparelhos import Ctx, gerar
from casasim.clima import Clima
from casasim.comportamento import Uso
from casasim.falhas import TIPOS
from casasim.mqtt import PROIBIDAS, Publicador
from casasim.sensores import Sensor
from casasim.tempo_real import ExecucaoTempoReal
from casasim.util import N

PERFIS = ["perfil1", "perfil2", "perfil3"]


# ------------------------------------------------------------------ catálogo e cenários
def test_catalogo_normalizado_completo():
    cat = dados.catalogo()
    assert len(cat["aparelhos"]) == 229 and len(cat["sensores"]) == 80
    for a in cat["aparelhos"].values():
        assert a["potencia_w"] and a["potencia_w"] > 0, a["id"]
        assert a["potencia_origem"] in cat["meta"]["origens"], a["id"]
        assert a["classe"] and a["tensoes"], a["id"]
        if a["potencia_origem"] == "assumido":          # toda suposição tem justificativa escrita
            assert any(n.startswith("ASSUMIDO") for n in a["notas"]) or cat["tipos"][a["tipo"]]["suposicoes"], a["id"]
        if a["confianca"] == "baixa":
            assert a.get("revisao_confianca_baixa"), a["id"]


@pytest.mark.parametrize("perfil,canais,custo", [("perfil1", 5, 330.53), ("perfil2", 15, 1353.11), ("perfil3", 31, 7758.26)])
def test_cenarios_carregam_e_sao_compativeis(perfil, canais, custo):
    cen = dados.carregar_cenario(perfil)
    v = dados.validar(cen)
    assert v["ok"], v["erros"]
    assert v["n_canais"] == canais and v["custo_medidores"] == pytest.approx(custo, abs=0.01)
    assert cen.canal_geral is not None


def test_validacao_pega_tomada_de_10a_com_carga_grande():
    bruto = json.loads(json.dumps(dados.carregar_cenario("perfil1").bruto))
    for a in bruto["aparelhos"]:
        if a["aparelho_id"].startswith("chuveiro"):
            a["medido_por"] = "T3"
    bruto["medidores"][3]["mede"].append("Banheiro: chuveiro_eletrico")     # T3 = Tapo P110 de 10 A
    v = dados.validar(dados.montar_cenario(bruto))
    assert not v["ok"] and any("10 A" in e for e in v["erros"])


# ------------------------------------------------------------------ reprodutibilidade e física
def test_mesma_semente_mesmo_resultado():
    a = Simulador("perfil1", semente=7, inicio="2026-03-02").simular_dia()
    b = Simulador("perfil1", semente=7, inicio="2026-03-02").simular_dia()
    c = Simulador("perfil1", semente=8, inicio="2026-03-02").simular_dia()
    assert np.array_equal(a.geral, b.geral)
    assert all(np.array_equal(a.mensagens[k]["potencia_w"], b.mensagens[k]["potencia_w"]) for k in a.mensagens)
    assert not np.array_equal(a.geral, c.geral)


@pytest.mark.parametrize("perfil", PERFIS)
def test_medidor_geral_fecha_com_a_soma(perfil):
    sim = Simulador(perfil, semente=1, inicio="2026-01-05", faltas_naturais=False)
    dia = sim.simular_dia()
    soma = sum(float(p.sum()) for p in dia.pot.values()) + float(dia.base_w.sum())
    assert float(dia.geral.sum()) == pytest.approx(soma, rel=1e-4)
    medido = sum(dia.mensagens[g.chave]["energia_wh"][-1] for g in sim.c.canais_gerais) / 1000
    assert medido == pytest.approx(float(dia.geral.sum()) / 3.6e6, rel=0.04)      # erro de ganho do medidor < 3 sigma
    sem_ganho = sum(dia.mensagens[g.chave]["energia_wh"][-1] / sim.sensores[g.chave].ganho for g in sim.c.canais_gerais) / 1000
    assert sem_ganho == pytest.approx(float(dia.geral.sum()) / 3.6e6, rel=1e-3)  # fases somam exatamente o total


def test_geladeira_bate_com_a_etiqueta_do_pbe():
    cen = dados.carregar_cenario("perfil1")
    inst = cen.instancias["cozinha.geladeira"]
    clima = Clima(0).dia(dt.date(2026, 4, 15))
    clima.t_int[:] = 24.0                                        # condição equivalente à média dos ensaios (16 e 32 °C)
    st, total = {}, 0.0
    for d in range(6):
        ctx = Ctx(clima, np.zeros(1440), np.random.default_rng(d), 800000 + d)
        total += gerar(inst, [], ctx, st).sum() / 3.6e6
    kwh_mes = total / 6 * 30.42
    assert kwh_mes == pytest.approx(inst.spec["consumo_referencia"]["valor"], rel=0.08)


def test_lavadora_gasta_o_kwh_por_ciclo_do_pbe():
    inst = dados.carregar_cenario("perfil2").instancias["area_de_servico.maquina_lavar"]
    ctx = Ctx(Clima(0).dia(dt.date(2026, 1, 5)), np.zeros(1440), np.random.default_rng(0), 1)
    p = gerar(inst, [Uso(inst.id, 36000, 1)], ctx, {})
    assert (p.sum() - inst.spec["standby_w"] * N) / 3.6e6 == pytest.approx(inst.modelo["kwh_ciclo"], rel=0.06)


def test_uso_que_passa_da_meia_noite_continua_no_dia_seguinte():
    inst = dados.carregar_cenario("perfil1").instancias["sala.tv"]
    ctx = Ctx(Clima(0).dia(dt.date(2026, 1, 5)), np.zeros(1440), np.random.default_rng(0), 1)
    st = {}
    p1 = gerar(inst, [Uso(inst.id, N - 600, 1800)], ctx, st)
    p2 = gerar(inst, [], ctx, st)
    assert p1[-1] > 10 and p2[1100] > 10 and p2[1300] < 1


# ------------------------------------------------------------------ sensores
def _canal(cen, chave):
    return cen.canais[chave]


def test_sensor_periodico_respeita_intervalo_e_perde_pico_curto():
    cen = dados.carregar_cenario("perfil1")
    s = Sensor(_canal(cen, "t1"), semente=3)                    # tomada Tuya: leitura a cada 30 s
    p = np.full(N, 100.0, dtype=np.float32)
    k = s.fase + 10                                             # pico de 2 s entre duas leituras
    p[k:k + 2] = 3000.0
    m = s.medir(p, np.ones(1440), [], 1)
    assert np.all(np.diff(m["t"]) == 30)
    assert m["potencia_w"].max() < 110                          # o pico não aparece na potência...
    assert m["energia_wh"][-1] == pytest.approx(p.sum() * s.ganho / 3600, rel=1e-3)   # ...mas entra no contador de energia
    assert abs(s.ganho - 1) <= 0.03


def test_sensor_por_evento_envia_na_variacao():
    cen = dados.carregar_cenario("perfil2")
    s = Sensor(_canal(cen, "r1"), semente=3)                    # Shelly 1PM: 1 W e 5%
    p = np.full(N, 200.0, dtype=np.float32)
    p[5000:6000] = 204.0                                        # +2%: não dispara
    p[10000:10500] = 800.0                                      # dispara na subida e na descida
    m = s.medir(p, np.ones(1440), [], 1)
    assert 10000 in m["t"] and 10500 in m["t"] and 5000 not in m["t"]
    assert len(m["t"]) <= 1440 + 4                              # só o envio de minuto além dos eventos


def test_medidor_some_durante_falta_de_energia():
    sim = Simulador("perfil1", semente=1, inicio="2026-01-05", faltas_naturais=False)
    sim.injetor.nova("falta_energia", "rede", dt.datetime(2026, 1, 5, 19, 0), 1800)
    dia = sim.simular_dia()
    a, b = 19 * 3600, 19 * 3600 + 1800
    assert float(dia.geral[a:b].max()) == 0.0
    for m in dia.mensagens.values():
        assert not np.any((m["t"] >= a) & (m["t"] < b))
    linha = [g for g in dia.gabarito if g["tipo"] == "falta_energia"][0]
    assert linha["alerta_de_aparelho"] is False
    df = sim.telemetria(dia, rotulos=True)
    assert df["anomalia"].sum() == 0                            # falta de energia não vira rótulo de anomalia de aparelho


# ------------------------------------------------------------------ falhas e gabarito
@pytest.mark.parametrize("tipo", TIPOS)
def test_cada_tipo_de_falha_altera_o_sinal_e_entra_no_gabarito(tipo):
    base = Simulador("perfil2", semente=5, inicio="2026-01-07", faltas_naturais=False).simular_dia()
    sim = Simulador("perfil2", semente=5, inicio="2026-01-07", faltas_naturais=False)
    alvo = {"magnitude": "cozinha.geladeira", "queda": "cozinha.geladeira", "pico": "cozinha.geladeira", "fora_de_horario": "area_de_servico.ferro_passar",
            "duracao_excessiva": "area_de_servico.ferro_passar", "consumo_nao_explicado": "geral", "falta_energia": "rede"}[tipo]
    hora = 2 if tipo == "fora_de_horario" else 10
    f = sim.injetor.nova(tipo, alvo, dt.datetime(2026, 1, 7, hora, 0))
    dia = sim.simular_dia()
    assert not np.array_equal(dia.geral, base.geral)
    linha = [g for g in dia.gabarito if g["falha_id"] == f.id][0]
    assert linha["efetiva"] and linha["tipo"] == tipo
    if alvo not in ("geral", "rede"):                           # os outros aparelhos não mudam
        outros = [i for i in dia.pot if i != alvo]
        assert all(np.array_equal(dia.pot[i], base.pot[i]) for i in outros)


def test_gabarito_nunca_vai_para_o_mqtt():
    sim = Simulador("perfil1", semente=2, inicio="2026-01-05", falhas_por_semana=7, dias_previstos=2)
    pub = Publicador()
    sim.executar(2, publicador=pub)
    permitidas = {"ts", "medidor_id", "canal", "potencia_w", "energia_wh", "tensao_v", "corrente_a", "estado"}
    assert pub.enviadas > 1000
    for topico, pl in pub.ultimas:
        assert set(pl) <= permitidas and {"ts", "medidor_id", "canal", "potencia_w", "energia_wh"} <= set(pl)
        assert topico.startswith("casa/perfil1/") and topico.endswith("/telemetria")
    with pytest.raises(ValueError):
        pub.publicar("casa/perfil1/sala/t3/telemetria", {"ts": "x", "anomalia": 1})
    assert "anomalia" in PROIBIDAS


def test_exporta_dataset_rotulado(tmp_path):
    sim = Simulador("perfil1", semente=4, inicio="2026-01-05", falhas_por_semana=14, dias_previstos=3)
    res = sim.executar(3, tmp_path)
    import pandas as pd
    rot = pd.read_csv(tmp_path / "dataset_rotulado.csv")
    tel = pd.read_csv(tmp_path / "telemetria.csv")
    gab = pd.read_csv(tmp_path / "gabarito_falhas.csv")
    assert len(rot) == len(tel) == res["n_mensagens"]
    assert "anomalia" in rot.columns and "anomalia" not in tel.columns
    assert rot["anomalia"].sum() > 0 and len(gab) >= 1
    assert (tmp_path / "verdade_1min.csv").exists() and (tmp_path / "resumo.json").exists()
    assert set(rot.loc[rot.anomalia == 1, "falha_id"]) <= set(gab.falha_id)


# ------------------------------------------------------------------ tempo real e API
def test_tempo_real_falha_e_comando_de_rele():
    ex = ExecucaoTempoReal(Simulador("perfil2", semente=3, inicio="2026-01-07"), 60, hora_inicial="19:30")
    ex.avancar(300)
    antes = ex.estado()
    ex.injetar("consumo_nao_explicado", "geral", 30, {"potencia_w": 900})
    ex.avancar(120)
    depois = ex.estado()
    assert depois["total_real_w"] - antes["total_real_w"] > 500
    assert ex.comando("t2", "desligar") and not ex.comando("q", "desligar")
    ex.avancar(120)
    e = ex.estado()
    assert e["aparelhos"]["sala.tv"] == 0 and e["canais"]["t2"]["cortado"]
    assert ex.pub.ultimas[-1][1]["ts"].endswith("-03:00")
    ex.avancar(6 * 3600)                                         # vira o dia sem erro
    assert ex.estado()["agora"].startswith("2026-01-08")


def test_api_web():
    from fastapi.testclient import TestClient
    from casasim.web.app import app
    c = TestClient(app)
    assert c.get("/").status_code == 200
    cat = c.get("/api/catalogo").json()
    assert len(cat["aparelhos"]) == 229
    cen = c.get("/api/cenario/perfil1").json()
    assert cen["validacao"]["ok"]
    assert c.post("/api/validar", json={"cenario": cen["bruto"], "personas": cen["personas"]}).json()["ok"]
    assert c.post("/api/falha", json={"tipo": "pico", "alvo": "cozinha.geladeira"}).status_code == 409
    assert c.post("/api/iniciar", json={"cenario": "perfil1", "velocidade": 600, "hora": "19:00"}).json()["ok"]
    assert c.post("/api/falha", json={"tipo": "pico", "alvo": "cozinha.geladeira"}).status_code == 200
    assert c.get("/api/estado").json()["casa"] == "perfil1"
    with c.websocket_connect("/ws") as ws:
        assert "agora" in ws.receive_json()
    c.post("/api/parar", json={})


def test_medidor_geral_bifasico_informa_cada_fase():
    sim = Simulador("perfil2", semente=1, inicio="2026-01-05", faltas_naturais=False)
    assert [c.fase for c in sim.c.canais_gerais] == ["A", "B"]
    f = sim.injetor.nova("consumo_nao_explicado", "geral", dt.datetime(2026, 1, 5, 10), 3600, {"potencia_w": 800})
    dia = sim.simular_dia()
    ma, mb = dia.mensagens["q_c1"], dia.mensagens["q_c2"]
    sel = lambda m: (m["t"] > 10 * 3600 + 120) & (m["t"] < 11 * 3600 - 60)
    base = Simulador("perfil2", semente=1, inicio="2026-01-05", faltas_naturais=False).simular_dia()
    assert ma["potencia_w"][sel(ma)].mean() - base.mensagens["q_c1"]["potencia_w"][sel(ma)].mean() > 600   # o extra aparece na fase A
    assert abs(mb["potencia_w"][sel(mb)].mean() - base.mensagens["q_c2"]["potencia_w"][sel(mb)].mean()) < 50
    assert all(abs(v - 127) < 10 for v in ma["tensao_v"][:50])
    assert sim.c.canal_geral.chave == "q_c1" and [g for g in dia.gabarito if g["falha_id"] == f.id][0]["canal_direto"] == "q_c1"


def test_ventilador_nao_e_tudo_ou_nada():
    """Com limiar probabilístico, dias de temperatura parecida não decidem todos igual."""
    sim = Simulador("perfil1", semente=5, inicio="2026-01-05", faltas_naturais=False)
    ligou = []
    for _ in range(40):
        d = sim.simular_dia()
        ligou.append(any(u.inst == "quarto_casal.ventilador" for u in d.usos))
    assert 0.1 < sum(ligou) / len(ligou) < 0.95


# ---------------------------------------------------------------- etapa 1: datasets, carga e registro ao vivo
def test_plano_balanceado_reparte_os_tipos():
    from casasim.falhas import TIPOS
    sim = Simulador("perfil2", semente=7, inicio="2026-02-02")
    fs = sim.injetor.plano_balanceado(dt.date(2026, 2, 2), 28, 7.0)
    cont = {t: sum(f.tipo == t for f in fs) for t in TIPOS}
    assert len(fs) == 28 and max(cont.values()) - min(cont.values()) <= 1
    assert all(dt.date(2026, 2, 2) <= f.inicio.date() < dt.date(2026, 3, 2) for f in fs)


def test_gerar_datasets_separa_treino_limpo_e_esconde_gabarito(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ferramentas"))
    import gerar_datasets
    from casasim.datasets import ROTULOS, carregar
    assert gerar_datasets.main(["--perfis", "perfil1", "--sementes", "1", "--dias", "10", "--falhas-por-semana", "7", "--saida", str(tmp_path)]) == 0
    pasta = tmp_path / "perfil1" / "semente_1"
    tr = carregar(pasta, "treino", com_rotulos=True)
    te = carregar(pasta, "teste", com_rotulos=True)
    assert tr["anomalia"].sum() == 0 or set(tr.loc[tr["anomalia"], "falha_id"].str[0]) == {"R"}   # só faltas naturais da rede
    assert te["anomalia"].sum() > 0
    assert not set(ROTULOS) & set(carregar(pasta, "teste").columns)
    m = json.loads((tmp_path / "manifesto.json").read_text(encoding="utf-8"))
    assert m["conjuntos"]["perfil1/semente_1"]["linhas"]["treino"] == len(tr)
    assert all(len(a["sha256"]) == 64 for a in m["arquivos"])


def test_gerador_de_carga_respeita_rampa_e_nao_vaza_gabarito(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ferramentas"))
    import gerar_datasets
    from casasim.carga import GeradorCarga
    gerar_datasets.main(["--perfis", "perfil1", "--sementes", "1", "--dias", "5", "--saida", str(tmp_path)])
    pub = Publicador()
    relogio = {"t": 0.0}
    g = GeradorCarga(tmp_path / "perfil1" / "semente_1", pub, intervalo_s=1.0, rampa="0:1,0.5:3", registro=tmp_path / "c.csv")

    def dormir(s):
        relogio["t"] += 0.05
    r = g.executar(60, relogio=lambda: relogio["t"], dormir=dormir)
    n = g.canais_por_casa
    assert abs(r["enviadas"] - (30 * n + 30 * 3 * n)) <= 3 * n
    topicos = {t.split("/")[1] for t, _ in pub.ultimas}
    assert topicos <= {"carga1", "carga2", "carga3"} and "carga3" in topicos
    assert (tmp_path / "c.csv").exists()


def test_registro_ao_vivo_guarda_falha_alerta_e_gabarito(tmp_path):
    reg = tmp_path / "aovivo.jsonl"
    ex = ExecucaoTempoReal(Simulador("perfil2", semente=3, inicio="2026-01-07"), 60, hora_inicial="23:00", registro=reg)
    alvo = next(i for i, x in ex.sim.c.instancias.items() if x.canal)
    f = ex.injetar("pico", alvo, 5)
    ex._alerta({"tipo": "anomalia", "medidor_id": "x"})
    ex.avancar(2 * 3600)
    ex.parar()
    ev = [json.loads(l) for l in reg.read_text(encoding="utf-8").splitlines()]
    nomes = [e["evento"] for e in ev]
    assert nomes[0] == "sessao_iniciada" and nomes[-1] == "sessao_encerrada"
    assert next(e for e in ev if e["evento"] == "alerta_recebido")["falhas_ativas"] == [f.id]
    dia = next(e for e in ev if e["evento"] == "dia_concluido")
    assert f.id in {g["falha_id"] for g in dia["gabarito"]}
    assert all(dt.datetime.fromisoformat(e["relogio_real"]).tzinfo is not None for e in ev)
