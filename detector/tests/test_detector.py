"""Testes do detector (rodar com `python -m pytest -q` dentro de TCC/detector)."""
from __future__ import annotations

import inspect
import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from detector import atributos, avaliacao as av, dados, modelos
from detector.atributos import RESIDUO, Extrator, estados_ligado, nomes_seq, nomes_tab, sinais_por_minuto
from detector.dados import Telemetria, carregar_telemetria, chaves_dos_canais


# ------------------------------------------------------------------------------------------------ dados

def test_chaves_dos_canais_seguem_o_gabarito():
    df = pd.DataFrame({"medidor_id": ["q", "q", "t1", "c1", "c1", "c1"], "canal": [1, 2, 1, 1, 2, 3]})
    assert chaves_dos_canais(df).tolist() == ["q_c1", "q_c2", "t1", "c1_c1", "c1_c2", "c1_c3"]


def test_detector_nao_le_gabarito(casa):
    tel = carregar_telemetria(casa, "teste")
    assert set(tel.canais) == {"q", "t1"} and tel.geral == ["q"]
    for mod in (dados, atributos, modelos):
        assert "gabarito_falhas" not in inspect.getsource(mod)


def test_contexto_da_particao_anterior(casa):
    tel = carregar_telemetria(casa, "calibracao", horas_contexto=24)
    assert min(v[0] for v in tel.ts.values()) < tel.inicio <= tel.inicio + 86400 - 3600 * 24 + 60


# ------------------------------------------------------------------------------------------- atributos

def _canal_sintetico(spike=False):
    g0 = 1_000_020
    seg = np.arange(0, 3600)
    p = np.full(len(seg), 100.0)
    if spike:
        p[1805:1807] = 3100.0                    # pico de 2 s entre duas leituras de 30 s
    ts = g0 + seg[::30]
    e = 500 + np.cumsum(p)[::30] / 3600.0
    return g0, ts, p[::30], e


def test_pico_curto_aparece_na_energia_e_nao_na_potencia():
    g0, ts, p, e = _canal_sintetico(spike=False)
    sem = sinais_por_minuto(ts, p, e, g0, 60)
    g0, ts, p, e = _canal_sintetico(spike=True)
    com = sinais_por_minuto(ts, p, e, g0, 60)
    assert np.allclose(np.nan_to_num(sem["p_med"]), np.nan_to_num(com["p_med"]))   # potência não viu
    m = int(np.nanargmax(com["exc"]))
    assert 29 <= m <= 31 and com["exc"][m] > 150                                    # a energia viu (6000 J / 30 s)
    assert np.nanmax(np.abs(sem["exc"][2:])) < 5


def test_estados_ligado():
    on = np.array([0, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0, 1], dtype=bool)
    run, desde, part = estados_ligado(on)
    assert run.tolist() == [0, 1, 2, 3, 4, 5, 6, 7, 8, 0, 0, 1]   # buraco de 1 min não encerra; de 5 min encerra
    assert desde.tolist()[:4] == [atributos.TETO_MIN, 0, 0, 1]
    assert part.tolist() == [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]


def test_atributos_sao_causais(casa):
    tel = carregar_telemetria(casa, "calibracao")
    ext = Extrator().ajustar(carregar_telemetria(casa, "treino"))
    A = ext.transformar(tel)
    corte = int(A.t_fim[A.m0 + 600])                                   # instante de uma decisão
    futuro = Telemetria(tel.canais, tel.geral,
                        {c: v.copy() for c, v in tel.ts.items()},
                        {c: np.where(tel.ts[c] >= corte, tel.p[c] * 5 + 300, tel.p[c]) for c in tel.canais},
                        {c: np.where(tel.ts[c] >= corte, tel.e[c] + 10_000, tel.e[c]) for c in tel.canais},
                        tel.inicio, tel.fim)
    B = ext.transformar(futuro)
    ate = A.m0 + 600
    for c in A.canais:
        assert np.array_equal(A.tab[c][: ate + 1], B.tab[c][: ate + 1]), c
        assert np.array_equal(A.seq[c][: ate + 1], B.seq[c][: ate + 1]), c
        assert not np.array_equal(A.tab[c][ate + 2:], B.tab[c][ate + 2:]), c     # e o futuro mudou mesmo


def test_formas_e_residuo(casa):
    ext = Extrator().ajustar(carregar_telemetria(casa, "treino"))
    A = ext.transformar(carregar_telemetria(casa, "teste"))
    assert A.canais == ["q", "t1", RESIDUO]
    assert A.tab["q"].shape[1] == len(nomes_tab(True)) and A.tab["t1"].shape[1] == len(nomes_tab(False))
    assert A.seq["t1"].shape[1] == len(nomes_seq(False)) and A.seq[RESIDUO].shape[1] == len(nomes_seq(False))
    # resíduo = q − t1 ≈ carga de base (50 W de dia, 80 W à noite); coluna 4 = p_mediana60 em log
    base = np.expm1(A.tab[RESIDUO][A.m0:, nomes_tab(False).index("p_mediana60")])
    assert 45 < np.median(base) < 85
    assert all(len(v) == 24 and 0 < min(v) and max(v) < 1 for v in ext.p_on_hora.values())


# ------------------------------------------------------------------------------------------- avaliação

def _ev(fid, ini, fim, canais, direto="t1", tipo="queda"):
    return av.Evento(fid, tipo, "x", direto, ini, fim, frozenset(canais))


def test_casamento_de_eventos_e_precisao_por_evento():
    evs = [_ev("A", 10_000, 20_000, {"t1", "q"}), _ev("B", 50_000, 60_000, {"t2", "q"}, direto="t2")]
    al = pd.DataFrame({"canal": ["t1", "t1", "q", "t3", "t2"],
                       "ini": [10_600, 12_000, 30_000, 10_700, 70_000],
                       "fim": [10_900, 12_100, 30_100, 10_800, 70_100], "score_max": 1.0})
    r = av.ponto(al, evs, dias=1.0)
    assert r["_vp"].tolist() == [True, True, False, False, False]   # t3 não enxerga A; t2 chegou tarde demais
    assert r["revocacao"] == 0.5
    assert r["precisao"] == pytest.approx(1 / (1 + 3))               # 1 evento detectado, 3 alertas falsos
    det = r["_det"][0]
    assert det[0] and det[1] == pytest.approx(10.0) and det[2]      # atraso de 10 min, localizado no t1
    assert r["fp_por_dia"] == 3


def test_persistencia_e_alertas():
    s = np.array([0, 2, 2, 0, 2, 2, 2, 2, 0, 0], dtype=float)
    t = 60 * (np.arange(10) + 1)
    sup = np.zeros(10, dtype=bool)
    a1 = av.alertas({"c": s}, t, 1.0, sup, k=1)
    assert len(a1) == 1                                   # buraco de 1 min é juntado
    a3 = av.alertas({"c": s}, t, 1.0, sup, k=3)
    assert len(a3) == 1 and a3["ini"].iloc[0] == t[6]     # só depois de 3 min seguidos
    sup[4:8] = True
    assert len(av.alertas({"c": s}, t, 1.0, sup, k=3)) == 0


def test_supressao_depois_da_falta():
    sem = np.zeros(100, dtype=bool)
    sem[10:20] = True
    s = av.supressao(sem, recuperacao=30)
    assert s[10:50].all() and not s[50:].any() and not s[:10].any()


def test_auc_pr_e_escolha_do_limiar():
    cv = pd.DataFrame({"k": 1, "theta": [3.0, 2.0, 1.0, 0.5], "precisao": [1.0, 0.8, 0.5, 0.2],
                       "revocacao": [0.25, 0.5, 0.75, 1.0], "f1": [0.4, 0.615, 0.6, 0.333],
                       "alertas": [1, 3, 8, 30]})
    assert av.auc_pr_evento(cv, 1) == pytest.approx(0.25 * 1 + 0.25 * 0.8 + 0.25 * 0.5 + 0.25 * 0.2)
    assert av.escolher_limiar(cv) == (2.0, 1)


# --------------------------------------------------------------------------------------------- modelos

@pytest.mark.parametrize("nome", ["regra", "if", "ocsvm", "ae", "lstm_ae"])
def test_onnx_da_o_mesmo_score(nome):
    if nome in ("ae", "lstm_ae"):
        pytest.importorskip("torch")
    ort = pytest.importorskip("onnxruntime")
    rng = np.random.default_rng(0)
    forma = (1200, 30, 6) if nome == "lstm_ae" else (3000, 17)
    X = rng.normal(size=forma).astype(np.float32)
    kw = {"epocas_max": 2, "L": 30} if nome == "lstm_ae" else {"epocas_max": 2} if nome == "ae" else {}
    m = modelos.criar(nome, semente=1, **kw).ajustar(X[:-200], X[-200:])
    o = m.para_onnx()
    assert [x.name for x in o.graph.output] == ["score"]
    sess = ort.InferenceSession(o.SerializeToString(), providers=["CPUExecutionProvider"])
    b = sess.run(["score"], {"x": X})[0]
    a = m.pontuar(X)
    assert b.shape == (len(X),)
    assert np.max(np.abs(a - b)) < 1e-4 * (1 + np.max(np.abs(a)))
    assert np.corrcoef(a, b)[0, 1] > 0.99999


def test_score_maior_e_mais_anomalo():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(4000, 5)).astype(np.float32)
    fora = np.full((5, 5), 6.0, dtype=np.float32)
    for nome in ("if", "ocsvm"):
        m = modelos.criar(nome, semente=1).ajustar(X)
        assert m.pontuar(fora).min() > np.quantile(m.pontuar(X), 0.99)


# ------------------------------------------------------------------------------------------ ponta a ponta

def test_ponta_a_ponta_detecta_geladeira_parada(casa, tmp_path, monkeypatch):
    from detector import experimento
    monkeypatch.setattr(experimento, "DIAS_VAL", 3)
    linhas = experimento.rodar_casa(casa.parents[1], "perfilX", 1, ["regra", "if", "ocsvm"], tmp_path, onnx=True,
                                    log=lambda *_: None)
    por = {l["modelo"]: l for l in linhas}
    assert por["ocsvm"]["eventos"] == 1
    assert por["ocsvm"]["revocacao"] == 1.0                # a geladeira parada 4 h é detectada (θ vindo da calibração)
    for l in linhas:
        assert l["onnx_decisoes_iguais"] > 0.999
        assert 0 <= l["auc_pr_evento"] <= 1
    cfg = json.loads((tmp_path / "perfilX" / "semente_1" / "ocsvm" / "config.json").read_text())
    assert set(cfg["canais"]) == {"q", "t1", RESIDUO}
    assert (tmp_path / "perfilX" / "semente_1" / "ocsvm" / "t1.onnx").exists()
    t = experimento.consolidar(tmp_path)
    assert set(t["perfil_modelo"]["modelo"]) == {"regra", "if", "ocsvm"}


# ---------------------------------------------------------------------------------------------- cascata

def test_vigilancia_e_orcamento():
    from detector import cascata as cz
    m = np.zeros(20, dtype=bool)
    m[5] = True
    assert np.flatnonzero(cz.vigilancia(m, 3)).tolist() == [5, 6, 7]          # causal: só depois do gatilho
    rng = np.random.default_rng(0)
    so = {c: rng.normal(size=5000) for c in ("a", "b")}
    r = {c: np.zeros(5000, dtype=bool) for c in so}
    sup = np.zeros(5000, dtype=bool)
    assert cz.tau_do_orcamento(so, r, sup, 1.0) == (-np.inf, 1.0)
    assert cz.tau_do_orcamento(so, r, sup, 0.0) == (np.inf, 0.0)
    fr = [cz.tau_do_orcamento(so, r, sup, b, V=5)[1] for b in (0.5, 0.2, 0.05)]
    assert fr[0] <= 0.5 and fr[1] <= 0.2 and fr[2] <= 0.05 and fr[0] > fr[1] > fr[2] > 0.02


def test_decisao_da_cascata():
    from detector import cascata as cz
    n = 50
    so = {"c": np.zeros(n)}
    s2 = {"c": np.zeros(n)}
    r = {"c": np.zeros(n, dtype=bool)}
    sup = np.zeros(n, dtype=bool)
    so["c"][10] = 2.0                     # OCSVM suspeita no minuto 10 → vigilância de 10 a 14 (V = 5)
    s2["c"][[12, 30]] = 5.0               # o LSTM-AE vê algo em 12 (vigiado) e em 30 (não vigiado)
    r["c"][40] = True                     # a regra dispara em 40
    al, vig = cz._decidir(so, r, s2, sup, tau=1.0, th_saida=np.inf, th2=1.0, k=1, V=5)
    assert np.flatnonzero(al["c"]).tolist() == [12, 40]                     # 30 não foi escalado; regra alerta direto
    assert vig["c"][40:45].all()                                            # a regra também escala
    al, _ = cz._decidir(so, r, s2, sup, tau=np.inf, th_saida=1.5, th2=1.0, k=1, V=5)
    assert np.flatnonzero(al["c"]).tolist() == [10, 40]                     # orçamento 0: só estágio 1


@pytest.fixture(scope="module")
def sintetica_treinada(casa, tmp_path_factory):
    """Baselines (regra, OCSVM, LSTM-AE curto) e cascata da casa sintética, uma vez só para os testes abaixo."""
    pytest.importorskip("torch")
    from detector import cascata as cz, experimento
    raiz = tmp_path_factory.mktemp("treinada")
    antes = experimento.DIAS_VAL
    experimento.DIAS_VAL = 3
    try:
        experimento.rodar_casa(casa.parents[1], "perfilX", 1, ["regra", "ocsvm", "lstm_ae"], raiz / "baselines",
                               onnx=True, opcoes={"lstm_ae": {"epocas_max": 2, "L": 60}}, log=lambda *_: None)
    finally:
        experimento.DIAS_VAL = antes
    df = cz.rodar_casa_cascata(casa.parents[1], raiz / "baselines", "perfilX", 1, raiz / "cascata",
                               orcamentos=(1.0, 0.1, 0.0), log=lambda *_: None)
    return raiz, df


def test_cascata_ponta_a_ponta_reproduz_os_modelos_oficiais(sintetica_treinada):
    from detector import cascata as cz
    raiz, df = sintetica_treinada
    assert df["orcamento"].tolist() == [1.0, 0.1, 0.0]
    assert df["escalados"].iloc[0] == 1.0 and df["escalados"].iloc[2] == 0.0
    conf = json.loads((raiz / "cascata" / "perfilX" / "semente_1" / "conferencia.json").read_text())
    for m, v in conf["modelos_sozinhos"].items():                           # mesmos .onnx → mesmo F1 da rodada oficial
        assert v["f1"] == pytest.approx(v["f1_oficial"], abs=1e-9), m
    t = cz.consolidar_cascata(raiz / "cascata")
    assert set(t["cascata"]["orcamento"]) == {1.0, 0.1, 0.0}


@pytest.mark.parametrize("orcamento", [1.0, 0.1, 0.0])
def test_ao_vivo_igual_ao_notebook(casa, sintetica_treinada, tmp_path, orcamento):
    """A versão do Pi, mensagem por mensagem, dá os mesmos atributos e os mesmos alarmes que a do notebook."""
    from detector import cascata as cz
    from detector.aovivo import CasaAoVivo, empacotar
    raiz, _ = sintetica_treinada
    pac = empacotar(raiz / "baselines", raiz / "cascata", "perfilX", 1, tmp_path / "pac", orcamento)
    ext = Extrator().ajustar(carregar_telemetria(casa, "treino"))
    tel = carregar_telemetria(casa, "calibracao")
    A = ext.transformar(tel)
    viva = CasaAoVivo(pac)
    tabs, seqs, alarmes = ({c: [] for c in A.canais} for _ in range(3))
    passo = {c: viva.at[c].passo for c in A.canais}

    def espiao(c):
        def f(*a):
            x = passo[c](*a)
            tabs[c].append(x)
            seqs[c].append(viva.at[c].seq[-1])
            return x
        return f
    for c in A.canais:
        viva.at[c].passo = espiao(c)
    casc = viva._cascata
    viva._cascata = lambda c, *a: (lambda d: alarmes[c].append(d.alarme) or d)(casc(c, *a))
    msgs = sorted((int(t), c, float(p), float(e)) for c in tel.canais for t, p, e in zip(tel.ts[c], tel.p[c], tel.e[c]))
    for t, c, p, e in msgs:
        viva.recebe_chave(c, t, p, e)
    viva.finalizar(tel.fim)
    assert viva.stats["minutos"] == A.M
    for c in A.canais:
        assert np.allclose(np.array(tabs[c]), A.tab[c], atol=1e-3), c          # o desvio-padrão do pandas difere ~1e-4
        assert np.array_equal(np.stack(seqs[c]), A.seq[c]), c                  # a entrada do LSTM-AE é idêntica
    cfg = json.loads((pac / "casa_borda.json").read_text())
    S = {m: cz.scores_oficiais(raiz / "baselines" / "perfilX" / "semente_1", m, {"calibracao": A}, ["calibracao"])[0]
         ["calibracao"] for m in ("ocsvm", "regra", "lstm_ae")}
    sup = av.supressao(A.sem_sinal)[A.m0:]
    th_r, k_r = cfg["modelos"]["regra"]["theta"], cfg["modelos"]["regra"]["k"]
    r = {c: av.persistente((np.nan_to_num(x, nan=-np.inf) > th_r) & ~sup, k_r) for c, x in S["regra"].items()}
    P = viva.params
    off, _ = cz._decidir(S["ocsvm"], r, S["lstm_ae"], sup, P.tau, P.theta_saida, P.theta2, P.k, P.V)
    for c in A.canais:
        on = np.array(alarmes[c])[A.m0:]
        assert np.array_equal(on[60:], off[c][60:]), c                       # depois de 1 h (persistências zeradas)


def test_mensagem_mqtt_e_chave_do_canal(sintetica_treinada, tmp_path):
    from detector.aovivo import CasaAoVivo, empacotar, ts_epoch
    raiz, _ = sintetica_treinada
    viva = CasaAoVivo(empacotar(raiz / "baselines", raiz / "cascata", "perfilX", 1, tmp_path / "p", 0.1))
    assert ts_epoch("2026-01-05T00:00:00-03:00") == 1767582000
    viva.recebe("t1", 1, "2026-01-05T00:00:00-03:00", 100.0, 10.0)
    viva.recebe("xx", 1, "2026-01-05T00:00:30-03:00", 1.0, 1.0)
    viva.recebe("t1", 1, "2026-01-04T23:59:00-03:00", 100.0, 10.0)
    assert viva.stats["desconhecidas"] == 1 and viva.stats["fora_de_ordem"] == 1
    assert viva.chave("q", 1) == "q"


def test_servico_modo_de_carga_e_controlador(sintetica_treinada, tmp_path):
    """E3/E4: casas virtuais com estado próprio e sessões ONNX compartilhadas; o controlador desce o orçamento
    quando o pior atraso do último minuto passa do limite e só sobe depois de 3 minutos calmos."""
    import time as _t
    from types import SimpleNamespace
    from detector.aovivo import empacotar
    from detector.servico import Servico
    raiz, _ = sintetica_treinada
    pac = empacotar(raiz / "baselines", raiz / "cascata", "perfilX", 1, tmp_path / "p", 0.1)
    sv = Servico([], "x", carga=str(pac), controlador=True, atraso_max=1.0)
    assert sv.orcamento == 0.1

    def msg(casa, atraso, p=100.0, e=10.0):
        ts = datetime.fromtimestamp(_t.time() - atraso).astimezone().isoformat(timespec="milliseconds")
        pl = json.dumps({"ts": ts, "medidor_id": "t1", "canal": 1, "potencia_w": p, "energia_wh": e}).encode()
        sv._ao_receber(None, None, SimpleNamespace(topic=f"casa/{casa}/cozinha/t1/telemetria", payload=pl))

    for _ in range(5):
        msg("carga1", 0.1); msg("carga2", 0.1)
    msg("outra", 0.1)                                                         # fora do prefixo: ignorada
    assert set(sv.casas) == {"carga1", "carga2"} and sv.erros == 0
    c1, c2 = sv.casas["carga1"], sv.casas["carga2"]
    assert c1.sess is c2.sess is sv.modelo.sess and c1.sinais is not c2.sinais and c1.casa == "carga1"
    assert c1.stats["mensagens"] == c2.stats["mensagens"] == 5
    assert all(len(a.seq) == c1.L for a in c1.at.values()) and c1.i >= c1.L - 1     # aquecida: LSTM-AE desde já
    e = sv.estado_carga()
    assert e["casas"] == 2 and e["atraso_p50_s"] == pytest.approx(0.1, abs=0.05) and e["orcamento_proximo"] == 0.1
    for _ in range(20):
        msg("carga1", 5.0)
    e = sv.estado_carga()                                    # atraso 5 s ≫ 1 s: desce um nível (pacote: 0 / 0,1 / 1)
    assert e["orcamento_proximo"] == 0.0 and c1.params.orcamento == 0.0 and c2.params.orcamento == 0.0
    orc = []                                                  # espera 1 min (6 janelas) e sobe depois de 3 min calmos
    for _ in range(30):
        msg("carga1", 0.1)
        orc.append(sv.estado_carga()["orcamento_proximo"])
    assert orc[:23] == [0.0] * 23 and orc[23] == 0.1
    for _ in range(6):                                         # sobe e a carga volta: desce e passa a exigir 6 min
        msg("carga1", 5.0)
        sv.estado_carga()
    assert sv.orcamento == 0.0 and sv.calmas_exigidas == 36
    r = sv.comando({"marca": "E3 b=1", "reset": True, "orcamento": 1.0, "controlador": False})   # roteiro do PC
    assert r["casas"] == 0 and sv.orcamento == 1.0 and not sv.controlador and sv.base_atraso is None
    msg("carga9", 0.1)
    assert sv.casas["carga9"].params.orcamento == 1.0


# ------------------------------------------------------------------------------- campanha e E5 (sessão ao vivo)

def test_baixar_orcamento_zera_a_vigilancia(sintetica_treinada, tmp_path):
    """E4: ao baixar o orçamento (τ maior), a vigilância aberta com o τ antigo é descartada; ao subir, é mantida."""
    from detector.aovivo import CasaAoVivo, empacotar
    raiz, _ = sintetica_treinada
    c = CasaAoVivo(empacotar(raiz / "baselines", raiz / "cascata", "perfilX", 1, tmp_path / "p", 0.1))
    for e in c.est.values():
        e.ult_gatilho = 5
    c.definir_orcamento(1.0)                                   # τ = −∞ (menor): mantém
    assert all(e.ult_gatilho == 5 for e in c.est.values())
    c.definir_orcamento(0.1)                                   # τ finito (maior que −∞): zera
    assert all(e.ult_gatilho == -10**9 for e in c.est.values())


def test_perturbacoes_da_campanha():
    from detector.campanha import perturbar
    rng = np.random.default_rng(0)
    n = 20000
    df = pd.DataFrame({"ts": np.arange(n) * 30 + 1_767_582_000, "chave": np.where(np.arange(n) % 2, "t1", "q"),
                       "potencia_w": 100.0, "energia_wh": np.arange(n) * 0.8})
    assert abs(len(perturbar(df, "perda_20", ["q"], rng)) / n - 0.8) < 0.02
    assert len(perturbar(df, "duplicadas", ["q"], rng)) > n
    fo = perturbar(df, "fora_de_ordem", ["q"], rng)
    assert len(fo) == n and (np.diff(fo["ts"].to_numpy()) < 0).sum() > 100
    off = perturbar(df, "medidor_off", ["q"], rng)
    assert (off["chave"] == "q").sum() == n // 2 and (off["chave"] == "t1").sum() < n // 2     # só o próprio some
    dg = perturbar(df, "deriva_geral_5", ["q"], rng)
    assert np.allclose(dg.loc[dg["chave"] == "q", "potencia_w"], 105.0)
    assert np.allclose(dg.loc[dg["chave"] == "t1", "potencia_w"], 100.0)


def test_e5_le_sessao_e_casa_alertas(tmp_path):
    from detector.e5 import analisar
    g = {"falha_id": "F0001", "tipo": "fora_de_horario", "alvo": "cozinha.micro_ondas", "canal_direto": "t2",
         "inicio": "2026-01-06 05:17:15", "fim": "2026-01-06 05:23:15", "efeito_inicio": "2026-01-06 05:17:15",
         "efeito_fim": "2026-01-06 05:23:15", "efetiva": True, "alerta_de_aparelho": True}
    linhas = [
        {"evento": "sessao_iniciada", "relogio_real": "2026-11-23T02:06:05-03:00", "relogio_sim": "2026-01-05 17:30:00",
         "velocidade": 60.0, "canais": {"q": {}, "t2": {}}},
        {"evento": "falha_injetada", "relogio_real": "2026-11-23T02:17:52-03:00", "relogio_sim": "2026-01-06 05:17:15",
         "falha_id": "F0001", "tipo": "fora_de_horario", "alvo": "cozinha.micro_ondas"},
        {"evento": "alerta_recebido", "relogio_real": "2026-11-23T02:18:02-03:00", "relogio_sim": "2026-01-06 05:27:05",
         "alerta": {"ts": "2026-01-06T05:27:00-03:00", "medidor_id": "t2", "canal": 1, "estagio": "ocsvm", "score": 1.1}},
        {"evento": "alerta_recebido", "relogio_real": "2026-11-23T02:30:00-03:00", "relogio_sim": "2026-01-06 15:00:05",
         "alerta": {"ts": "2026-01-06T15:00:00-03:00", "medidor_id": "q", "canal": 1, "estagio": "ocsvm", "score": 1.2}},
        {"evento": "dia_concluido", "relogio_real": "2026-11-23T02:40:00-03:00", "relogio_sim": "2026-01-07 00:00:00",
         "gabarito": [g]},
    ]
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(json.dumps(l) for l in linhas))
    r = analisar(f)
    assert r["resumo"]["eventos"] == 1 and r["resumo"]["detectados"] == 1 and r["resumo"]["alertas_falsos"] == 1
    ev = r["eventos"].iloc[0]
    assert ev["estagio"] == "ocsvm" and ev["localizado"] and abs(ev["atraso_sim_min"] - 9.75) < 1e-9
    assert abs(ev["latencia_real_s"] - 10.0) < 1e-6
    assert abs(r["resumo"]["latencia_sistema_mediana_s"] - 5 / 60) < 1e-9        # 5 s simulados a 60×
