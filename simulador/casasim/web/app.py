"""App web (FastAPI + WebSocket): modo de montagem, dashboard, planta 2D e painel de falhas."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from .. import dados
from ..comportamento import tipo_comodo
from ..falhas import DESCRICAO, TIPOS, InjetorFalhas
from ..motor import Simulador
from ..mqtt import Publicador
from ..tempo_real import ExecucaoTempoReal
from ..util import slug

app = FastAPI(title="casasim")
ESTATICO = Path(__file__).parent / "static"
EXEC: dict = {"ex": None}
app.mount("/static", StaticFiles(directory=str(ESTATICO)), name="static")


def _ex() -> ExecucaoTempoReal:
    if EXEC["ex"] is None:
        raise HTTPException(409, "simulação parada: inicie pelo painel")
    return EXEC["ex"]


@app.get("/", response_class=HTMLResponse)
def raiz():
    return (ESTATICO / "index.html").read_text(encoding="utf-8")


@app.get("/api/catalogo")
def api_catalogo():
    c = dados.catalogo()
    ap = [dict(id=a["id"], tipo=a["tipo"], nome=f"{a['marca']} {a['modelo']}", variante=a["variante"], potencia_w=a["potencia_w"],
               tensoes=a["tensoes"], preco_brl=a["preco_brl"], perfil=a["perfil_sugerido"], confianca=a["confianca"],
               origem=a["potencia_origem"]) for a in c["aparelhos"].values()]
    se = [dict(id=s["id"], tipo=s["tipo"], nome=f"{s['marca']} {s['modelo']}", preco_brl=s["preco_brl"], corrente_max_a=s["corrente_max_a"],
               potencia_max_w=s["potencia_max_w"], firmware=s["firmware"], modo=s["modo"], intervalo_s=s["intervalo_s"], canais=s["canais"],
               tem_rele=s["tem_rele"], erro_pct=s["erro_ganho_pct"], perfil=s["perfil_sugerido"]) for s in c["sensores"].values()]
    return dict(aparelhos=ap, sensores=se, tipos_falha=TIPOS, descricao_falhas=DESCRICAO, tarifas=dados.tarifas())


@app.get("/api/cenarios")
def api_cenarios():
    return dados.listar_cenarios()


def _resposta_cenario(cen) -> dict:
    return dict(nome=cen.nome, bruto=cen.bruto, personas=cen.personas, validacao=dados.validar(cen),
                instancias=[dict(id=i.id, comodo=i.comodo, tipo=i.tipo, nome=f"{i.spec['marca']} {i.spec['modelo']}", quantidade=i.quantidade,
                                 potencia_w=i.potencia_w, tensao=i.tensao, canal=i.canal) for i in cen.instancias.values()],
                comodos=[dict(nome=c, tipo=tipo_comodo(c)) for c in cen.comodos],
                alvos_falha={t: InjetorFalhas(cen).alvos(t) for t in TIPOS})


@app.get("/api/cenario/{nome}")
def api_cenario(nome: str):
    try:
        return _resposta_cenario(dados.carregar_cenario(nome))
    except FileNotFoundError:
        raise HTTPException(404, "cenário não encontrado")


def _montar(corpo: dict):
    bruto = dict(corpo["cenario"])
    geral = [m for m in bruto.get("medidores", []) if m.get("mede") == ["casa toda"]]
    for m in bruto.get("medidores", []):                    # 'mede' é derivado do campo medido_por de cada aparelho
        if m not in geral:
            m["mede"] = sorted({f"{a['comodo']}: {dados.catalogo()['aparelhos'][a['aparelho_id']]['tipo']}"
                                for a in bruto["aparelhos"] if a.get("medido_por") == m["rotulo"]})
    try:
        return bruto, dados.montar_cenario(bruto, corpo.get("nome", "personalizado"), corpo.get("personas"))
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e))


@app.post("/api/validar")
def api_validar(corpo: dict):
    _, cen = _montar(corpo)
    return dados.validar(cen)


@app.post("/api/salvar")
def api_salvar(corpo: dict):
    bruto, cen = _montar(corpo)
    nome = slug(corpo.get("nome") or "personalizado")
    if nome.startswith("casa_perfil"):
        raise HTTPException(422, "use outro nome: os três perfis originais não são sobrescritos")
    bruto.update(nome=corpo.get("nome"), casa=nome, moradores=cen.personas)
    v = dados.validar(cen)
    bruto["resumo"] = dict(custo_med=v["custo_medidores"], custo_ap=v["custo_aparelhos"], n_ap=v["n_aparelhos"], fluxos=v["n_canais"], medidos=v["medidos"])
    (dados.PASTA_CENARIOS / f"{nome}.json").write_text(json.dumps(bruto, ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(nome=nome, validacao=v)


@app.post("/api/iniciar")
def api_iniciar(corpo: dict):
    if EXEC["ex"] is not None:
        EXEC["ex"].parar()
    try:
        sim = Simulador(corpo.get("cenario", "perfil1"), int(corpo.get("semente", 42)), corpo.get("data", "2026-01-05"))
    except FileNotFoundError:
        raise HTTPException(404, "cenário não encontrado")
    pub = Publicador(corpo.get("mqtt_host") or None, int(corpo.get("mqtt_porta", 1883)), sim.c.casa)
    reg = None
    if corpo.get("registrar", True):
        import time as _t
        reg = Path(__file__).resolve().parents[2] / "registros" / f"aovivo_{sim.c.nome}_{_t.strftime('%Y%m%d_%H%M%S')}.jsonl"
    ex = ExecucaoTempoReal(sim, float(corpo.get("velocidade", 60)), pub, corpo.get("hora", "17:30"), corpo.get("bandeira"), registro=reg)
    ex.iniciar()
    EXEC["ex"] = ex
    return dict(ok=True, mqtt=dict(ativo=pub.ativo, erro=pub.erro), registro=str(reg) if reg else None)


@app.post("/api/parar")
def api_parar():
    if EXEC["ex"] is not None:
        EXEC["ex"].parar()
        EXEC["ex"] = None
    return dict(ok=True)


@app.post("/api/velocidade")
def api_velocidade(corpo: dict):
    _ex().mudar_velocidade(corpo["velocidade"])
    return dict(ok=True)


@app.post("/api/bandeira")
def api_bandeira(corpo: dict):
    _ex().bandeira = corpo.get("bandeira")
    return dict(ok=True)


@app.post("/api/falha")
def api_falha(corpo: dict):
    ex = _ex()
    if corpo.get("tipo") not in TIPOS:
        raise HTTPException(422, "tipo de falha inválido")
    alvo = corpo.get("alvo") or {"consumo_nao_explicado": "geral", "falta_energia": "rede"}.get(corpo["tipo"])
    if alvo not in ("geral", "rede") and alvo not in ex.sim.c.instancias:
        raise HTTPException(422, "alvo inválido")
    f = ex.injetar(corpo["tipo"], alvo, corpo.get("duracao_min"), corpo.get("params"))
    return dict(id=f.id, tipo=f.tipo, alvo=f.alvo, inicio=f.inicio.isoformat(sep=" "), fim=f.fim.isoformat(sep=" "), params=f.params)


@app.post("/api/comando")
def api_comando(corpo: dict):
    if not _ex().comando(corpo.get("canal", ""), corpo.get("acao", "")):
        raise HTTPException(422, "este medidor não tem relé")
    return dict(ok=True)


@app.get("/api/estado")
def api_estado():
    return _ex().estado()


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    try:
        while True:
            ex = EXEC["ex"]
            await sock.send_text(json.dumps(ex.estado() if ex else {"parado": True}, ensure_ascii=False))
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError):
        pass
