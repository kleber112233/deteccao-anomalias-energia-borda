"""Carrega o catálogo normalizado, os cenários (casas) e as personas; valida a montagem."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from .util import slug

BASE = Path(__file__).resolve().parents[1]
PASTA_CENARIOS = BASE / "cenarios"
TIPOS_220 = {"chuveiro_eletrico", "ar_condicionado", "carregador_veicular", "forno_eletrico", "secadora", "lava_loucas"}


def _json(caminho: Path):
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def catalogo() -> dict:
    return _json(BASE / "catalogos" / "catalogo_simulador.json")


def personas_padrao() -> dict:
    return _json(BASE / "dados" / "personas.json")


def tarifas() -> dict:
    return _json(BASE / "dados" / "tarifas.json")


def clima_dados() -> dict:
    return _json(BASE / "dados" / "clima_marilia_inmet.json")


def listar_cenarios() -> list[str]:
    return sorted(p.stem for p in PASTA_CENARIOS.glob("*.json"))


@dataclass
class Instancia:
    """Um aparelho colocado num cômodo da casa."""
    id: str
    comodo: str
    tipo: str
    aparelho_id: str
    spec: dict
    quantidade: int
    tensao: int
    potencia_w: float
    canal: str | None = None          # chave do canal que mede este aparelho (None = só o medidor geral)
    fase: str = "A"                   # fase do circuito: 'A', 'B' ou 'AB' (aparelho 220 V entre fases)

    @property
    def classe(self) -> str:
        return self.spec["classe"]

    @property
    def modelo(self) -> dict:
        return self.spec.get("funcionamento") or {}


@dataclass
class Canal:
    """Um fluxo de medição: um canal de um medidor do acervo."""
    chave: str                         # ex.: 't1' ou 'c_c2'
    medidor: str                       # rótulo em minúsculas, usado no tópico MQTT
    numero: int                        # nº do canal dentro do medidor (1..n)
    modelo_id: str
    sensor: dict
    comodo: str                        # slug do cômodo, ou 'quadro'
    onde: str
    geral: bool = False
    instancias: list[str] = field(default_factory=list)
    preco_brl: float = 0.0
    fase: str | None = None            # 'A' ou 'B' nos medidores gerais por fase; None = casa toda

    def topico(self, casa: str, sufixo: str = "telemetria") -> str:
        return f"casa/{casa}/{self.comodo}/{self.medidor}/{sufixo}"


@dataclass
class Cenario:
    nome: str
    casa: str                          # identificador usado no tópico MQTT (ex.: 'perfil1')
    bruto: dict
    tensoes: list[int]
    comodos: list[str]
    instancias: dict[str, Instancia]
    canais: dict[str, Canal]
    personas: dict

    @property
    def canal_geral(self) -> Canal | None:
        return next((c for c in self.canais.values() if c.geral), None)

    @property
    def canais_gerais(self) -> list[Canal]:
        return [c for c in self.canais.values() if c.geral]


def _tensao_instancia(spec: dict, tensoes_casa: list[int]) -> int | None:
    sup = [v for v in spec["tensoes"] if v in tensoes_casa]
    if not sup:
        return None
    if 220 in sup and (spec["tipo"] in TIPOS_220 or 127 not in sup):
        return 220
    return 127 if 127 in sup else sup[0]


def montar_cenario(bruto: dict, nome: str = "personalizado", personas: dict | None = None) -> Cenario:
    cat = catalogo()
    lig = (bruto.get("ligacao") or "").lower()
    tensoes = [127] if "monof" in lig and "220" not in lig else [127, 220]
    casa = slug(str(bruto.get("casa") or (f"perfil{bruto['perfil']}" if bruto.get("perfil") else nome)))
    inst: dict[str, Instancia] = {}
    por_ponto: dict[tuple[str, str], list[str]] = {}
    for a in bruto["aparelhos"]:
        spec = cat["aparelhos"].get(a["aparelho_id"])
        if spec is None:
            raise ValueError(f"aparelho fora do catálogo: {a['aparelho_id']}")
        base = f"{slug(a['comodo'])}.{spec['tipo']}"
        iid, k = base, 2
        while iid in inst:
            iid, k = f"{base}.{k}", k + 1
        v = _tensao_instancia(spec, tensoes) or spec["tensoes"][0]
        p = (spec.get("potencia_por_tensao_w") or {}).get(str(v)) or spec["potencia_w"]
        ordem_comodo = list(bruto["comodos"]).index(a["comodo"]) if a["comodo"] in bruto["comodos"] else 0
        fase = "AB" if v == 220 else ("A" if ordem_comodo % 2 == 0 else "B")      # ASSUMIDO: circuitos 127 V alternam de fase por cômodo
        inst[iid] = Instancia(iid, a["comodo"], spec["tipo"], a["aparelho_id"], spec, int(a.get("quantidade", 1)), v, float(p), None, fase)
        por_ponto.setdefault((a["comodo"], spec["tipo"]), []).append(iid)

    canais: dict[str, Canal] = {}
    for m in bruto.get("medidores", []):
        sensor = cat["sensores"].get(m["modelo_id"])
        if sensor is None:
            raise ValueError(f"medidor fora do acervo: {m['modelo_id']}")
        rot = slug(m["rotulo"])
        if m["mede"] == ["casa toda"]:
            if sensor.get("canais", 1) >= 2 and 220 in tensoes:      # uma pinça por fase: um canal por fase
                for n, fase in enumerate("AB", 1):
                    canais[f"{rot}_c{n}"] = Canal(f"{rot}_c{n}", rot, n, m["modelo_id"], sensor, "quadro", m.get("onde", ""), True, [],
                                                  (m.get("preco_brl") or 0) if n == 1 else 0, fase)
            else:
                canais[rot] = Canal(rot, rot, 1, m["modelo_id"], sensor, "quadro", m.get("onde", ""), True, [], m.get("preco_brl") or 0)
            continue
        grupos = []
        for alvo in m["mede"]:
            com, tipo = [x.strip() for x in alvo.split(":")]
            grupos.append((com, por_ponto.get((com, tipo), [])))
        if sensor.get("canais", 1) > 1:            # medidor de vários circuitos: um canal por item
            partes = [([g[0]], g[1]) for g in grupos]
        else:                                      # tomada/relé: tudo somado num canal só
            partes = [(sorted({g[0] for g in grupos}), [i for g in grupos for i in g[1]])]
        for n, (coms, ids) in enumerate(partes, 1):
            chave = rot if len(partes) == 1 else f"{rot}_c{n}"
            comodo = slug(coms[0]) if len(coms) == 1 and "quadro" not in m.get("onde", "").lower() else "quadro"
            canais[chave] = Canal(chave, rot, n, m["modelo_id"], sensor, comodo, m.get("onde", ""), False, ids,
                                  (m.get("preco_brl") or 0) if n == 1 else 0)
            for i in ids:
                inst[i].canal = chave
    if personas is None:
        ref = bruto.get("moradores")
        todas = personas_padrao()
        if isinstance(ref, dict):
            personas = ref
        else:
            chave = ref.split("#")[1] if isinstance(ref, str) and "#" in ref else f"perfil{bruto.get('perfil', 1)}"
            personas = todas.get(chave) or todas["perfil1"]
    return Cenario(nome, casa, bruto, tensoes, list(bruto["comodos"]), inst, canais, personas)


def carregar_cenario(nome: str, personas: dict | None = None) -> Cenario:
    """Aceita 'perfil1', 'casa_perfil1', o nome de um arquivo em cenarios/ ou um caminho."""
    p = Path(nome)
    if not p.exists():
        for cand in (f"{nome}.json", f"casa_{nome}.json"):
            if (PASTA_CENARIOS / cand).exists():
                p = PASTA_CENARIOS / cand
                break
        else:
            raise FileNotFoundError(f"cenário não encontrado: {nome}")
    return montar_cenario(_json(p), p.stem, personas)


def validar(cen: Cenario) -> dict:
    """Confere a montagem: tensão, corrente da tomada × carga, medidor geral, custo."""
    erros, avisos, infos = [], [], []
    for i in cen.instancias.values():
        if _tensao_instancia(i.spec, cen.tensoes) is None:
            erros.append(f"{i.comodo}: {i.spec['marca']} {i.spec['modelo']} só funciona em {i.spec['tensoes']} V e a casa tem {cen.tensoes} V.")
        if i.canal is None and i.tipo != "lampada":
            infos.append(f"{i.comodo}: {i.tipo} sem medidor próprio (aparece só no medidor geral).")
    if cen.canal_geral is None:
        avisos.append("Casa sem medidor geral: o consumo não explicado e os aparelhos sem medidor ficam invisíveis.")
    for c in cen.canais.values():
        if c.geral:
            continue
        if not c.instancias:
            avisos.append(f"Medidor {c.medidor.upper()} (canal {c.numero}) não mede nenhum aparelho.")
            continue
        s = c.sensor
        corrente = sum(float(cen.instancias[i].spec["corrente_a"].get(str(cen.instancias[i].tensao), 0)) * (cen.instancias[i].quantidade if cen.instancias[i].tipo == "lampada" else 1) for i in c.instancias)
        potencia = sum(cen.instancias[i].potencia_w * (cen.instancias[i].quantidade if cen.instancias[i].tipo == "lampada" else 1) for i in c.instancias)
        nomes = ", ".join(cen.instancias[i].tipo for i in c.instancias)
        if s.get("corrente_max_a") and corrente > s["corrente_max_a"]:
            erros.append(f"Medidor {c.medidor.upper()} ({s['modelo']}): carga de {corrente:.1f} A ({nomes}) passa do limite de {s['corrente_max_a']} A.")
        elif s.get("corrente_max_a") and corrente > 0.8 * s["corrente_max_a"]:
            avisos.append(f"Medidor {c.medidor.upper()}: carga de {corrente:.1f} A usa mais de 80% do limite de {s['corrente_max_a']} A.")
        if s.get("potencia_max_w") and potencia > s["potencia_max_w"] and s["tipo"].startswith("tomada"):
            erros.append(f"Medidor {c.medidor.upper()} ({s['modelo']}): {potencia:.0f} W ({nomes}) passa do limite de {s['potencia_max_w']} W.")
        if s.get("firmware") == "zigbee2mqtt":
            avisos.append(f"Medidor {c.medidor.upper()} é Zigbee: exige adaptador USB no Raspberry Pi.")
    custo_med = round(sum(c.preco_brl for c in cen.canais.values()), 2)
    custo_ap = round(sum((i.spec.get("preco_brl") or 0) * i.quantidade for i in cen.instancias.values()), 2)
    return dict(ok=not erros, erros=erros, avisos=avisos, infos=infos, custo_medidores=custo_med, custo_aparelhos=custo_ap,
                n_aparelhos=sum(i.quantidade for i in cen.instancias.values()), n_canais=len(cen.canais),
                medidos=sum(1 for i in cen.instancias.values() if i.canal))
