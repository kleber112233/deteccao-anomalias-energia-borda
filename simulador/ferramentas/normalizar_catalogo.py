"""Etapa A — gera catalogos/catalogo_simulador.json a partir do catálogo bruto.

Uso:  python ferramentas/normalizar_catalogo.py

Regras:
- nada é inventado como se fosse medido: todo campo traz a "origem"
  (pbe | fabricante | loja | derivado | assumido) e, quando assumido, a justificativa
  fica em tipos[tipo]["suposicoes"] ou em "notas" do item;
- os valores conferidos na API pública do PBE/Inmetro em 17/11/2026 estão em PBE_* abaixo
  (programa, modelo e nº de registro em catalogos/pbe_conferencia.json).
"""
from __future__ import annotations
import json, re, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CAT = BASE / "catalogos"

# ---------------------------------------------------------------------------
# Dados conferidos na API do PBE/Inmetro (17/11/2026)
# ---------------------------------------------------------------------------
# Refrigeradores (programa 293): kWh/dia a 16 °C, kWh/dia a 32 °C, kWh/mês médio, registro
PBE_REFRIG = {
 "geladeira-consul-crd37mb": (0.6, 1.3, 29.3, "005217/2016"),
 "geladeira-consul-cra30mb": (0.3, 0.7, 16.7, "005222/2016"),
 "geladeira-consul-crm44mb": (0.4, 1.0, 24.9, "005218/2016"),
 "freezer-consul-cvu20mb": (0.7, 1.3, 29.1, "005220/2016"),
 "freezer-consul-cha22mb": (0.5, 0.8, 24.5, "005219/2016"),
 "freezer-consul-cvu26mb": (0.5, 1.1, 32.0, "005220/2016"),
 "freezer-consul-cvu30mb": (0.6, 1.1, 27.1, "005220/2016"),
 "freezer-consul-chb53mb": (0.7, 1.0, 36.2, "005219/2016"),
 "geladeira-electrolux-dci39t": (None, None, 21.3, "014063/2025"),
 "geladeira-electrolux-dc35a": (0.7, 1.2, 28.5, "005402/2016"),
 "geladeira-electrolux-if44": (0.5, 1.2, 25.9, "005404/2016"),
 "geladeira-electrolux-im7": (None, None, 39.1, "005404/2016"),
 "geladeira-brastemp-bro85mb": (0.5, 1.2, 31.3, "005218/2016"),
 "geladeira-electrolux-es40s": (0.5, 1.2, 26.2, "018893/2024"),
 "smart-geladeira-samsung-rt53dg6650s9": (0.6, 1.2, 28.0, "011206/2025"),
 "smart-geladeira-lg-side-by-side-gc-l257slp1": (0.8, 1.6, 36.3, "013224/2025"),
 "freezer-electrolux-hb200": (None, None, 18.6, "011658/2025"),
 "freezer-electrolux-he150": (None, None, 21.6, "000816/2022"),
 "freezer-electrolux-fei27t": (0.4, 1.3, 25.4, "005399/2016"),
 "freezer-brastemp-bvr28pb": (0.9, 1.5, 35.7, "005221/2016"),
}
# Lavadoras (programa 322), versão 127 V: kWh/ciclo água fria, kWh/ciclo água quente, tempo do ciclo de ensaio (min), registro
PBE_LAVA = {
 "lavadora-colormaq-lcs10-tanquinho-10kg": (0.11, None, 66, "002320/2023"),
 "lavadora-colormaq-lca13-13kg": (0.41, None, 230, "002789/2023"),
 "lavadora-consul-cwb09bb-9kg": (0.25, None, 188, "000727/2023"),
 "lavadora-brastemp-bwr12bb-12kg-agua-quente": (0.37, 3.70, 220, "000727/2023"),
 "lavadora-philco-plr14a-14kg": (0.34, None, 225, "006404/2024"),
 "lava-seca-philco-pls10b-11-7kg": (0.22, 1.01, 197, "003306/2023"),
 "lavadora-brastemp-bwk16ab-16kg": (0.49, None, 300, "000727/2023"),
 "lava-seca-electrolux-lsp11-11-7kg": (0.34, 1.70, 230, "000992/2023 (inativo)"),
 "lava-seca-brastemp-bno14ab-14-8kg": (0.30, 2.14, 257, "001715/2023"),
 "smart-lavaseca-lg-vc5-cv3012wc5a-sem-wifi": (0.23, 1.52, 273, "003187/2023"),
 "smart-lavaseca-samsung-wd13fg6b34beaz": (0.30, 1.54, 290, "000406/2023"),
 "smart-lavaseca-lg-vc4-cv5012wc4": (0.23, 1.51, 269, "003187/2023"),
}
# Condicionadores de ar (programa 166): potência a 35 °C carga total, 35 °C carga parcial,
# 29 °C carga parcial (W), espera (W), IDRS, kWh/ano, registro
PBE_AR = {
 "ac-janela-consul-ccb07fb-mecanico": (748, None, None, 1, 3.11, 584.0, "003901/2012"),
 "ac-janela-consul-ccn07fb": (748, None, None, 1, 3.11, 584.0, "003901/2012"),
 "ac-janela-springer-midea-qck078rb": (805.2, None, None, 3, 3.10, 586.1, "001260/2015 (QCK078BB)"),
 "ac-janela-springer-midea-mck128bb-12000": (1192.1, None, None, 3, 3.12, 932.0, "001262/2015"),
 "ac-split-midea-airvolution-lite-9000": (1000, 465, 298.8, 4, 4.60, 473.9, "006337/2023"),
 "ac-split-elgin-eco-inverter-iii-9000": (834, 310, 198, 2, 7.00, 327.0, "006724/2014 (HJFI09C2WG)"),
 "ac-split-agratto-one-top-12000-onoff-127v": (1256, None, None, 1, 3.50, 829.0, "009646/2022"),
 "ac-split-midea-ai-ecomaster-9000-inverter": (688.5, 282.3, 176.2, 6, 7.60, 286.9, "006337/2023"),
 "ac-split-lg-dual-inverter-voice-9000": (750, 289, 196.5, 4, 7.00, 311.2, "004733/2023"),
 "smart-ac-midea-ai-ecomaster-9000-qf-42ezvqc09m5": (696.4, 277.5, 176.2, 6, 7.60, 287.0, "006337/2023"),
 "ac-split-samsung-windfree-ai-pro-12000": (1150, 360, 237, 2, 7.00, 416.0, "012321/2024 (linha AR60H12D1C; a linha D1A do mesmo registro traz 760/255/176 W)"),
 "smart-ac-lg-dual-inverter-ai-voice-12000-s3-q12ja33j": (1060, 340, 230, 4, 7.70, 377.4, "004733/2023"),
 "smart-ac-samsung-windfree-connect-ai-12000-f-ar12dyfaawk": (1170, 395, 287, 2, 6.00, 488.0, "012321/2024"),
 "smart-ac-samsung-windfree-pro-energy-9000-f-ar09cvfaawk": (633, 193, 136, 2, 9.00, 273.0, "008048/2022"),
 "ac-split-lg-ai-dual-inverter-voice-12000-110v": (1115, 394, 280, 5, 6.30, 461.7, "004733/2023"),
 "ac-split-lg-ai-dual-inverter-voice-18000": (1600, 573, 388, 3, 7.00, 622.6, "004733/2023"),
 "ac-split-midea-ai-ecomaster-18000-quente-frio": (1508.8, 550, 346.9, 4, 7.60, 573.7, "006337/2023"),
 "smart-ac-lg-artcool-ai-dual-inverter-18000-s3-w18klr7a": (1790, 663, 460, 4, 6.20, 742.4, "004733/2023"),
}
# Ventiladores de mesa/coluna (programa 184): potência baixa, média, alta (W), registro
PBE_VENT = {
 "vent-coluna-eos-evc60-turbo-vento": (83.9, 89.7, 93.4, "007054/2020"),
 "vent-mesa-britania-bvt320p-30cm": (48.7, 55.0, 62.7, "006775/2020"),
 "vent-mesa-arno-vf42-40cm": (89, 106, 128, "001690/2022"),
 "vent-mesa-philco-pvt492pa-40cm": (111.0, 120.8, 131.4, "003221/2024"),
 "vent-mesa-arno-xtreme-ve70-40cm": (78, 106.5, 127, "007938/2023"),
 "vent-mesa-arno-xtreme-force-breeze-vb50-50cm": (79.1, 109.5, 132.6, "004070/2020"),
 "vent-coluna-arno-vd5c-ultra-silence": (89, 107, 131, "007022/2019"),
}
# Ventiladores de teto (programa 323): kWh/mês em alta, média, baixa (1 h/dia => W = kWh*1000/30), registro
PBE_TETO = {
 "vent-teto-britania-cancun-bvt01b": (1.54, 1.14, 0.89, "012074/2022"),
 "vent-teto-ventisol-fenix-premium": (1.94, 1.78, None, "010932/2022"),
 "vent-teto-eos-evx110b-turbo-vento": (1.15, 0.53, 0.13, "017252/2024"),
 "vent-teto-arno-ultimate-vx10": (0.88, 0.45, 0.13, "012287/2022"),
}

# ---------------------------------------------------------------------------
# Suposições por tipo (texto vai para o JSON e depois para o artigo)
# ---------------------------------------------------------------------------
TIPOS = {
 "geladeira": dict(classe="refrigeracao", fp=0.85, suposicoes=[
   "Energia diária em função da temperatura do cômodo interpolada/extrapolada linearmente entre os dois pontos do ensaio PBE (16 °C e 32 °C).",
   "Quando o PBE só publica o kWh/mês, a razão E32/E16 = 2,3 (mediana dos modelos do catálogo com os dois pontos) reparte a energia.",
   "Potência do compressor não é publicada: assumida por volume (60 W + 0,12 W/L, limitada a 70–160 W), coerente com os três modelos do catálogo que informam (94, 108 e 124 W).",
   "Período liga/desliga de 45 min (faixa típica de 30–60 min) e pico de partida de 4× por 1,5 s.",
   "Frost free: resistência de degelo de 180 W por 18 min a cada 12 h; compressor inverter modula de forma contínua entre 35% e 100% da potência."]),
 "freezer": dict(classe="refrigeracao", fp=0.85, suposicoes=["Mesmas suposições de geladeira."]),
 "purificador_agua": dict(classe="refrigeracao", fp=0.8, suposicoes=[
   "Tratado como pequeno sistema de refrigeração: energia mensal da ENCE, compressor/placa de 70–75 W (valor de dois modelos do catálogo), período de 20 min, razão E32/E16 = 1,5."]),
 "ar_condicionado": dict(classe="ar", fp=0.95, suposicoes=[
   "Inverter: potência modulada entre a carga parcial a 29 °C e a carga total a 35 °C do ensaio PBE, conforme a diferença entre temperatura externa e setpoint; os primeiros 12 min ficam em carga total (pull-down).",
   "Sem os pontos parciais no PBE: parcial 35 °C = 0,37 × total e parcial 29 °C = 0,25 × total (médias dos modelos conferidos).",
   "On/off (janela e split convencional): compressor em potência total com ciclo de 12 min e fração ligada dada pela carga térmica; ventilador de 40 W com o compressor parado.",
   "Sem potência publicada: P = BTU/h × 0,293 / 3,2 (EER típico)."]),
 "chuveiro_eletrico": dict(classe="chuveiro", fp=1.0, suposicoes=[
   "Eletrônico: potência contínua entre 30% e 100% escolhida pela temperatura do dia. Multitemperaturas: degraus de 33/55/78/100% (o fabricante não informa a potência de cada degrau)."]),
 "ferro_passar": dict(classe="termostato", fp=1.0, suposicoes=["Pré-aquecimento de 2 min em potência total; depois termostato com 35% do tempo ligado em ciclos de 45 s."], params=dict(preaquecimento_min=2, fracao_ligado=0.35, periodo_s=45)),
 "air_fryer": dict(classe="termostato", fp=1.0, suposicoes=["Pré-aquecimento de 3 min; depois 65% ligado em ciclos de 60 s; ventilador de 40 W contínuo."], params=dict(preaquecimento_min=3, fracao_ligado=0.65, periodo_s=60, base_w=40)),
 "forno_eletrico": dict(classe="termostato", fp=1.0, suposicoes=["Pré-aquecimento de 10 min; depois 45% ligado em ciclos de 120 s."], params=dict(preaquecimento_min=10, fracao_ligado=0.45, periodo_s=120)),
 "aquecedor": dict(classe="termostato", fp=1.0, suposicoes=["Pré-aquecimento de 15 min; depois 60% ligado em ciclos de 300 s (halógeno: contínuo)."], params=dict(preaquecimento_min=15, fracao_ligado=0.6, periodo_s=300)),
 "secadora": dict(classe="termostato", fp=0.98, suposicoes=["Ciclo de 90 min com resistência 75% do tempo ligada (ciclos de 180 s) e motor de 150 W."], params=dict(preaquecimento_min=5, fracao_ligado=0.75, periodo_s=180, base_w=150)),
 "secador_cabelo": dict(classe="constante", fp=1.0, suposicoes=["Uso em potência total ou meia potência (2 níveis)."], params=dict(niveis=[0.5, 1.0])),
 "cafeteira": dict(classe="cafeteira", fp=1.0, suposicoes=["Filtro: 8 min em potência total e depois placa de aquecimento a 15% por até 40 min. Cápsula: 40 s de aquecimento + 30 s de extração por café, espera de 0,3 W."]),
 "micro_ondas": dict(classe="micro_ondas", fp=0.9, suposicoes=["Potência de entrada = potência nominal do PBE; níveis de potência menores são obtidos com o magnetron ligando e desligando em ciclos de 30 s.", "Espera = 0,01 kWh/dia do PBE = 0,42 W."]),
 "lampada": dict(classe="constante", fp=0.7, suposicoes=["Potência constante igual à nominal."]),
 "tv": dict(classe="eletronico", fp=0.9, suposicoes=[
   "Potência ligada derivada da ENCE: P = (kWh/mês × 1000/30 − 19 h × espera) / 5 h, assumindo o padrão de 5 h/dia ligada e 19 h em espera (premissa a conferir na portaria do Inmetro).",
   "Variação de ±15% com o conteúdo exibido."], params=dict(variacao=0.15)),
 "monitor": dict(classe="eletronico", fp=0.6, suposicoes=["Quando a ficha só traz o máximo, uso típico = 60% do máximo."], params=dict(variacao=0.05)),
 "notebook": dict(classe="eletronico", fp=0.6, suposicoes=["Consumo típico = 35% da potência do carregador; durante a recarga (45 min após ligar na tomada) = 80%. Espera de 0,5 W."], params=dict(variacao=0.2)),
 "computador_desktop": dict(classe="eletronico", fp=0.9, suposicoes=["Consumo típico estimado pela fonte: 25% (até 100 W), 20% (até 200 W) ou 13% (ATX); PC gamer em jogo = 45% da fonte. Espera de 2 W."], params=dict(variacao=0.2)),
 "videogame": dict(classe="eletronico", fp=0.9, suposicoes=["Potência em jogo do fabricante/medições públicas; menus e streaming = 40% disso. PS5: 200 W em jogo (assumido)."], params=dict(variacao=0.15)),
 "roteador": dict(classe="constante", fp=0.6, suposicoes=["Ligado 24 h no consumo típico; quando só há o máximo da fonte, típico = 60%."]),
 "ventilador": dict(classe="ventilador", fp=0.9, suposicoes=["Três velocidades com as potências do ensaio PBE; sem o ensaio, 60/80/100% da potência da etiqueta (kWh/mês × 1000 / 30 h, pois a ENCE equivale a 1 h/dia)."]),
 "maquina_lavar": dict(classe="lavadora", fp=0.8, suposicoes=[
   "Energia por ciclo do PBE (água fria). O tempo do ensaio PBE (3–5 h) não representa o programa do dia a dia: o simulador usa 40% desse tempo, limitado a 45–120 min.",
   "Etapas: encher 10%, lavar 45%, molho 10%, enxaguar 20%, centrifugar 15% do tempo, com 2/45/1/20/32% da energia.",
   "Lava e seca: a secagem não é coberta pelo PBE; assumida como resistência nominal 60% ligada por 120 min."]),
 "lava_loucas": dict(classe="lava_loucas", fp=0.98, suposicoes=["Ciclo de 110 min; energia do fabricante repartida em pré-lavagem 3%, aquecimento 42%, lavagem 6%, enxágue quente 40% e secagem 9%."]),
 "liquidificador": dict(classe="motor_curto", fp=0.8, suposicoes=["A potência declarada é a máxima; em uso = 60%. Uso de 60–120 s."], params=dict(fator=0.6, duracao_s=90, pico_fator=1.6)),
 "motor_portao": dict(classe="motor_curto", fp=0.75, suposicoes=["Acionamento de 15 s por abertura ou fechamento; central eletrônica com 3 W de espera. Sem potência elétrica publicada: potência de eixo / 0,55."], params=dict(fator=1.0, duracao_s=15, pico_fator=2.5)),
 "bomba_dagua": dict(classe="motor_demanda", fp=0.8, suposicoes=["Quando o catálogo traz potência de eixo (cv/HP), potência elétrica = eixo / 0,60. Liga com o uso de água (banhos e torneiras)."], params=dict(pico_fator=3.0)),
 "bomba_piscina": dict(classe="motor_programado", fp=0.8, suposicoes=["Potência elétrica = eixo / 0,65. Funciona por programação diária (filtragem). Velocidade variável: 30% da potência máxima na filtragem."], params=dict(pico_fator=3.0)),
 "carregador_veicular": dict(classe="carga_ve", fp=0.99, suposicoes=["Potência constante até repor a energia do dia (rendimento de 90%), com rampa de 15 min no fim."]),
}
RESISTIVOS = {"chuveiro_eletrico", "ferro_passar", "air_fryer", "forno_eletrico", "aquecedor", "secador_cabelo", "cafeteira"}

def num(x):
    return float(str(x).replace(".", "").replace(",", ".")) if x is not None else None

def tensoes(t):
    t = (t or "").lower()
    if "380" in t: return [380]
    r = []
    if "127" in t or "110" in t or "bivolt" in t: r.append(127)
    if "220" in t or "bivolt" in t: r.append(220)
    return r or [127, 220]

def pot_por_tensao(obs):
    m = re.search(r"([\d.]{3,6}) W \((?:127|110) ?V\) ?/ ?([\d.]{3,6}) W \(220 ?V\)", obs or "")
    return {"127": num(m.group(1)), "220": num(m.group(2))} if m else None

def litros(var):
    m = re.search(r"(\d{3}) L", var or "")
    return int(m.group(1)) if m else None

def normalizar(a):
    t, i = a["tipo"], a["id"]
    var, obs = a.get("variante") or "", a.get("observacoes") or ""
    low = (var + " " + (a.get("funcionamento") or "")).lower()
    P, SB, KWH = a.get("potencia_nominal_w"), a.get("potencia_standby_w"), a.get("consumo_mensal_kwh")
    o_cat = {"inmetro": "pbe", "fabricante": "fabricante"}.get((a.get("fonte_consumo") or "").split()[0].lower() if a.get("fonte_consumo") else "", "loja")
    if a["confianca"] == "alta" and o_cat == "loja": o_cat = "fabricante"
    r = dict(id=i, tipo=t, subtipo=a.get("subtipo") or "", marca=a["marca"], modelo=a["modelo"], variante=var,
             comodo_tipico=a["comodo_tipico"], tensoes=tensoes(a.get("tensao")), preco_brl=a.get("preco_brl"),
             perfil_sugerido=a.get("perfil_sugerido"), confianca=a["confianca"], classe=TIPOS[t]["classe"],
             fator_potencia=TIPOS[t]["fp"], notas=[])
    pot, po, sb, so, ref, m = P, (o_cat if P else None), SB, ("pbe" if (SB is not None and a["confianca"] == "alta") else "loja") if SB is not None else None, None, {}
    def assume(v, nota):
        r["notas"].append("ASSUMIDO: " + nota); return v
    ppt = pot_por_tensao(obs)
    if ppt: r["potencia_por_tensao_w"] = ppt

    if t in ("geladeira", "freezer", "purificador_agua"):
        pbe = PBE_REFRIG.get(i)
        e16 = e32 = None
        if pbe:
            e16, e32, kwh, reg = pbe
            if KWH and abs(KWH - kwh) > 0.5:
                r["notas"].append(f"CORRIGIDO: catálogo trazia {KWH} kWh/mês; o registro PBE {reg} informa {kwh} kWh/mês.")
            KWH = kwh; ref_o = "pbe"; r["registro_pbe"] = reg
        else: ref_o = o_cat
        if KWH is None:
            KWH = assume(8.0 if t == "purificador_agua" else 30.0, "sem consumo publicado; usado valor típico do tipo.") ; ref_o = "assumido"
        ref = dict(valor=KWH, unidade="kWh/mes", condicao="ENCE (média dos ensaios a 16 °C e 32 °C)", origem=ref_o)
        razao = 1.5 if t == "purificador_agua" else 2.3
        if e16 is None:
            e24 = KWH / 30.42; e16 = round(2 * e24 / (1 + razao), 3); e32 = round(razao * e16, 3); eo = "derivado"
        else: eo = "pbe"
        vol = litros(var)
        if t == "purificador_agua":
            pc = P or 72; pco = o_cat if P else "assumido"; per = 20
        else:
            pc = P or round(min(160, max(70, 60 + 0.12 * (vol or 350)))); pco = o_cat if P else "assumido"; per = 45
        inv = "inverter" in low and "não" not in low.split("inverter")[0][-12:] and i != "geladeira-electrolux-re21"
        ff = "frost free" in low
        m = dict(kwh_dia_16c=e16, kwh_dia_32c=e32, origem_kwh_dia=eo, potencia_compressor_w=pc, origem_compressor=pco,
                 periodo_min=per, inverter=inv, pico_partida_fator=1.0 if inv else 4.0, pico_partida_s=1.5,
                 degelo=dict(potencia_w=180, duracao_min=18, intervalo_h=12) if ff else None)
        pot, po = pc, pco
        sb, so = (1.5 if t != "purificador_agua" else 1.0), "assumido"
    elif t == "ar_condicionado":
        pbe = PBE_AR.get(i)
        btu = re.search(r"([\d.]+) BTU", var); btu = int(btu.group(1).replace(".", "")) if btu else 9000
        inv = ("inverter" in low) and ("não inverter" not in low) and ("convencional" not in low) and a.get("subtipo") != "janela"
        kwh_ano = round(KWH * 12, 1) if KWH else None
        pp35 = pp29 = None; idrs = None
        if pbe:
            pt, pp35, pp29, sbp, idrs, kwh_ano_p, reg = pbe
            if P and abs(P - pt) / pt > 0.03: r["notas"].append(f"CORRIGIDO: catálogo trazia {P} W; o PBE (registro {reg}) informa {pt} W a 35 °C em carga total.")
            pot, po, sb, so, kwh_ano = pt, "pbe", sbp, "pbe", kwh_ano_p; r["registro_pbe"] = reg; ref_o = "pbe"
        else:
            ref_o = o_cat
            if pot is None: pot = assume(round(btu * 0.293 / 3.2), "potência não publicada: BTU/h × 0,293 / EER 3,2."); po = "assumido"
            sb, so = 2.0, "assumido"
        if inv and pp35 is None: pp35, pp29 = round(0.37 * pot), round(0.25 * pot); m["origem_parciais"] = "derivado"
        elif inv: m["origem_parciais"] = "pbe"
        if kwh_ano: ref = dict(valor=kwh_ano, unidade="kWh/ano", condicao="ENCE (uso padronizado do Inmetro)", origem=ref_o)
        m.update(inverter=inv, btu_h=btu, idrs=idrs, potencia_total_35c_w=pot, potencia_parcial_35c_w=pp35, potencia_parcial_29c_w=pp29,
                 periodo_min=12, ventilador_w=40, pulldown_min=12)
    elif t == "chuveiro_eletrico":
        ele = "eletrônic" in low
        m = dict(controle="eletronico" if ele else "degraus", niveis=None if ele else [0.33, 0.55, 0.78, 1.0], minimo=0.3)
        if KWH: ref = dict(valor=KWH, unidade="kWh/mes", condicao="ENCE (uso padronizado do Inmetro; não é potência × tempo de banho)", origem="loja")
        sb, so = 0.0, "assumido"
    elif t in ("ferro_passar", "air_fryer", "forno_eletrico", "aquecedor", "secadora"):
        m = dict(TIPOS[t]["params"])
        if t == "aquecedor" and a.get("subtipo") == "halogeno": m.update(fracao_ligado=1.0, preaquecimento_min=0)
        if t == "aquecedor" and a.get("subtipo") == "termoventilado": m.update(fracao_ligado=0.8, preaquecimento_min=5, periodo_s=120, base_w=25)
        if t == "secadora":
            c = re.search(r"consumo_ciclo_kwh=([\d.]+)", obs)
            if c: ref = dict(valor=float(c.group(1)), unidade="kWh/ciclo", condicao="fabricante", origem="fabricante")
            if pot is None: pot = assume(1000, "secadora heat pump sem potência nominal: 1000 W (Samsung informa 1 kWh no ciclo de referência)."); po = "assumido"; m.update(fracao_ligado=0.6)
        sb, so = (sb if sb is not None else 0.0), ("fabricante" if SB is not None else "assumido")
    elif t == "secador_cabelo":
        m = dict(TIPOS[t]["params"]); sb, so = 0.0, "assumido"
    elif t == "cafeteira":
        cap = a.get("subtipo") == "capsula"
        m = dict(subtipo="capsula" if cap else "filtro", preparo_s=70 if cap else 480, manter_fracao=0.0 if cap else 0.15, manter_min=0 if cap else 40)
        sb, so = (0.3 if cap else 0.0), "assumido"
        if KWH: r["notas"].append("O kWh/mês do fabricante usa premissa de uso não informada; ignorado no simulador.")
    elif t == "micro_ondas":
        m = dict(periodo_s=30); so = "pbe"
        ref = dict(valor=0.01, unidade="kWh/dia", condicao="espera (PBE)", origem="pbe")
    elif t == "lampada":
        m = {}; sb = sb or 0.0; so = so or "assumido"
    elif t == "tv":
        m = dict(TIPOS[t]["params"])
        if KWH:
            ref = dict(valor=KWH, unidade="kWh/mes", condicao="ENCE (5 h/dia ligada + 19 h em espera, assumido)", origem="pbe")
            pot = round((KWH * 1000 / 30 - 19 * (SB or 0.5)) / 5, 1); po = "derivado"
        else:
            pot = assume(95, "TV OLED 55\" sem registro no PBE: 95 W (faixa típica de 90–110 W em SDR)."); po = "assumido"
    elif t == "monitor":
        m = dict(TIPOS[t]["params"])
        ol = obs.lower()
        if ("maximo" in ol or "máximo" in ol) and "tipico" not in ol and "típico" not in ol:
            pot = assume(round(P * 0.6, 1), f"ficha só traz o máximo ({P} W); típico = 60%."); po = "assumido"
        sb, so = (sb if sb is not None else 0.3), ("loja" if SB is not None else "assumido")
    elif t == "notebook":
        m = dict(TIPOS[t]["params"]); ad = P or 65
        pot = round(0.35 * ad, 1); po = "assumido"; m.update(potencia_carregador_w=ad, potencia_recarga_w=round(0.8 * ad, 1), recarga_min=45)
        r["notas"].append(f"ASSUMIDO: típico = 35% do carregador de {ad} W.")
        sb, so = 0.5, "assumido"
    elif t == "computador_desktop":
        m = dict(TIPOS[t]["params"])
        if i == "desktop-apple-mac-mini-m4": pot, po = 15, "assumido"; m.update(potencia_ocioso_w=4, potencia_max_w=65); r["notas"].append("ASSUMIDO: uso típico de 15 W, entre o ocioso (4 W) e o máximo (65 W) publicados pela Apple.")
        else:
            f = P or 65; fr = 0.25 if f <= 100 else 0.2 if f <= 200 else 0.13
            pot = round(f * fr); po = "assumido"; m.update(potencia_fonte_w=f)
            if "gamer" in i or "rtx" in i: m.update(potencia_jogo_w=round(0.45 * f))
            r["notas"].append(f"ASSUMIDO: típico = {int(fr*100)}% da fonte de {f} W.")
        sb, so = 2.0, "assumido"
    elif t == "videogame":
        m = dict(TIPOS[t]["params"], fator_menu=0.4)
        if i == "console-sony-ps5-slim": pot, po = assume(200, "PS5 em jogo: 200 W."), "assumido"
        elif i == "console-nintendo-switch-oled": pot, po = assume(10, "Switch OLED na base: 10 W (o catálogo traz 16 W como teto)."), "assumido"
        elif pot is None: pot, po = assume(20, "sem dado confiável: 20 W na base."), "assumido"
        if sb is None: sb, so = 0.5, "assumido"
    elif t == "roteador":
        tip = re.search(r"t[ií]pico (\d+,\d+) W", obs) or re.search(r"est[aá]tico (\d+,\d+) W", obs)
        if tip: pot, po = num(tip.group(1)), "loja"; r["notas"].append(f"Usado o consumo típico ({pot} W) em vez do máximo ({P} W).")
        elif i == "roteador-tplink-archer-ax23": pass
        else: pot = assume(round(P * 0.6, 1), f"só há o máximo da fonte ({P} W); típico = 60%."); po = "assumido"
        sb, so = pot, po
    elif t == "ventilador":
        if i in PBE_VENT:
            b, me, al, reg = PBE_VENT[i]; niv = [b, me, al]; no = "pbe"; r["registro_pbe"] = reg
            if P and abs(P - al) / al > 0.1: r["notas"].append(f"CORRIGIDO: catálogo trazia {P} W nominais; o ensaio PBE (registro {reg}) mede {al} W na velocidade alta.")
        elif i in PBE_TETO:
            al, me, b, reg = PBE_TETO[i]; al, me = round(al * 1000 / 30, 1), round(me * 1000 / 30, 1)
            b = round(b * 1000 / 30, 1) if b else round(0.8 * me, 1); niv = [b, me, al]; no = "pbe"; r["registro_pbe"] = reg
            if P and abs(P - al) / al > 0.1: r["notas"].append(f"CORRIGIDO: catálogo trazia {P} W; pelo PBE (registro {reg}, kWh/mês com 1 h/dia) a potência em alta é {al} W.")
        else:
            al = round(KWH * 1000 / 30, 1) if KWH else P; no = "derivado" if KWH else o_cat
            niv = [round(0.6 * al, 1), round(0.8 * al, 1), al]
            if KWH and P and abs(P - al) / al > 0.1: r["notas"].append(f"Potência em alta derivada da etiqueta ({KWH} kWh/mês ÷ 30 h = {al} W); a nominal da loja é {P} W.")
        pot, po = niv[2], no; m = dict(niveis_w=niv)
        if KWH: ref = dict(valor=KWH, unidade="kWh/mes", condicao="ENCE (1 h/dia na velocidade alta)", origem="loja")
        sb, so = 0.0, "assumido"
    elif t == "maquina_lavar":
        pbe = PBE_LAVA.get(i); c = re.search(r"consumo_ciclo_kwh=([\d.]+)", obs)
        semi = "tanquinho" in low or "semiautom" in low; ls = "lava e seca" in low or a.get("subtipo") == "lava e seca"
        if pbe:
            kc, kq, tm, reg = pbe; r["registro_pbe"] = reg; ro = "pbe"
            if c and abs(float(c.group(1)) - kc) > 0.02: r["notas"].append(f"CORRIGIDO: catálogo trazia {c.group(1)} kWh/ciclo; o PBE (registro {reg}) informa {kc}.")
        else:
            kc, kq, tm, ro = (float(c.group(1)) if c else assume(0.35, "kWh/ciclo não publicado: 0,35.")), None, 200, ("fabricante" if c else "assumido")
        ref = dict(valor=kc, unidade="kWh/ciclo", condicao="PBE, água fria", origem=ro)
        dur = 30 if semi else int(min(120, max(45, 0.4 * tm)))
        pres = None
        if ls: pres = (ppt or {}).get("127") or (P if P and P >= 1200 else 1300)
        elif P and P >= 1200: pres = P
        m = dict(kwh_ciclo=kc, kwh_ciclo_agua_quente=kq, tempo_ensaio_pbe_min=tm, duracao_min=dur, semiautomatica=semi,
                 etapas=[["lavar", 1.0, 1.0]] if semi else [["encher", .10, .02], ["lavar", .45, .45], ["molho", .10, .01], ["enxaguar", .20, .20], ["centrifugar", .15, .32]],
                 lava_e_seca=ls, secagem=dict(potencia_w=pres, fracao_ligado=0.6, duracao_min=120, origem="assumido") if ls else None)
        if pot is None or pot >= 1200: pot = assume(500, "potência do motor não publicada (ou a nominal é a da resistência): 500 W de pico na centrifugação."); po = "assumido"
        sb, so = 1.0, "assumido"
    elif t == "lava_loucas":
        c = re.search(r"(\d,\d+) kWh", obs)
        kc = num(c.group(1)) if c else assume(0.9, "kWh/ciclo não publicado: 0,9.")
        ref = dict(valor=kc, unidade="kWh/ciclo", condicao="fabricante/loja (ciclo normal)", origem=o_cat if c else "assumido")
        if pot is None: pot = assume(1250, "potência não publicada: 1250 W."); po = "assumido"
        m = dict(kwh_ciclo=kc, duracao_min=110, etapas=[["pre_lavagem", .10, .03], ["aquecimento", .20, .42], ["lavagem", .25, .06], ["enxague_quente", .15, .40], ["secagem", .30, .09]])
        sb, so = 1.0, "assumido"
    elif t in ("liquidificador", "motor_portao"):
        m = dict(TIPOS[t]["params"])
        if t == "motor_portao":
            if pot is None:
                hp = re.search(r"1/(\d) HP", var); eixo = 746 / int(hp.group(1)) if hp else 184
                pot = assume(round(eixo / 0.55), f"sem potência elétrica: eixo de {round(eixo)} W / 0,55."); po = "assumido"
            sb, so = 3.0, "assumido"
        else: sb, so = (sb if sb is not None else 0.0), "assumido"
    elif t in ("bomba_dagua", "bomba_piscina"):
        m = dict(TIPOS[t]["params"]); eixo = bool(re.search(r"cv|HP", var))
        if i == "bomba-piscina-sodramar-bvv-150-velocidade-variavel":
            m.update(potencia_max_w=round(P / 0.65)); pot = assume(round(0.3 * P / 0.65), "velocidade variável: filtragem a 30% da potência máxima."); po = "assumido"
        elif eixo and i != "pressurizador-lorenzetti-pl20":
            pot = assume(round(P / (0.60 if t == "bomba_dagua" else 0.65)), f"potência de eixo de {P} W convertida em potência elétrica."); po = "assumido"
        sb, so = (1.0 if "pressurizador" in i else 0.0), "assumido"
    elif t == "carregador_veicular":
        m = dict(eficiencia=0.9, rampa_final_min=15); sb, so = 3.0, "assumido"
    if sb is None: sb, so = 0.0, "assumido"
    r.update(potencia_w=pot, potencia_origem=po, standby_w=sb, standby_origem=so, consumo_referencia=ref, funcionamento=m)
    fp = r["fator_potencia"]
    r["corrente_a"] = {str(v): round((r.get("potencia_por_tensao_w", {}).get(str(v)) or (m.get("potencia_total_35c_w") or pot or 0)) / (v * fp), 2) for v in r["tensoes"] if v in (127, 220)}
    if a["confianca"] == "baixa":
        res = [n for n in r["notas"] if n.startswith("CORRIGIDO")] or r.get("registro_pbe")
        r["revisao_confianca_baixa"] = ("Conferido no PBE em 17/11/2026; pode ser tratado como confiança média." if res else
                                      "Sem fonte melhor em 17/11/2026: mantido como baixa; parâmetros do simulador marcados como assumidos. Não citar como dado medido no artigo.")
        r["notas"].append("Observação original: " + obs[:300])
    return r

# ---------------------------------------------------------------------------
# Medidores: parâmetros do modelo de sensor/firmware
# ---------------------------------------------------------------------------
def sensor(mo):
    fw = ((mo.get("firmware_ou_metodo") or "") + " " + (mo.get("ecossistema") or "") + " " + mo["id"]).lower()
    mede = (mo.get("mede") or "").lower()
    s = dict(id=mo["id"], tipo=mo["tipo"], marca=mo["marca"], modelo=mo["modelo"], preco_brl=mo.get("preco_brl"),
             corrente_max_a=mo.get("corrente_max_a"), potencia_max_w=mo.get("potencia_max_w"), tem_rele=bool(mo.get("comandavel")),
             mede_potencia="potencia" in mede, mede_tensao="tensao" in mede, mede_corrente="corrente" in mede,
             perfil_sugerido=mo.get("perfil_sugerido"), chip=mo.get("chip_medicao"), status_original=mo.get("status_precisao_intervalo"))
    multi = {"emylo-pw01-2canais-80a": 2, "tuya-medidor-2canais-bidirecional-80a": 2, "mingzhe-medidor-pinca-wifi-80a": 1, "shelly-pro-3em-120": 3, "shelly-3em-63-gen3": 3, "shelly-pro-4pm": 4, "shelly-2pm-gen4": 2,
             "sonoff-spm-main-4relay": 4, "refoss-em06p": 6, "refoss-em16p": 16, "athom-em6-esphome": 6, "circuitsetup-6ch-esp32-atm90e32": 6,
             "iotawatt-v6-4": 14, "emporia-vue-3-8ct": 8, "luocute-zigbee-3x200a": 3}
    s["canais"] = multi.get(mo["id"], 1)
    if "shelly" in fw:
        em = any(k in mo["id"] for k in ("3em", "-em-", "pro-em"))
        s.update(firmware="shelly", modo="evento", limiar_w=10 if em else 1, limiar_pct=5, intervalo_s=60, erro_ganho_pct=0.5, ruido_pct=0.2, resolucao_w=0.1, potencia_min_w=0.5,
                 origem="confirmado (API Shelly): envio por variação; mensagem de minuto com a energia.")
    elif "tapo" in fw:
        s.update(firmware="tapo", modo="periodico", intervalo_s=30, erro_ganho_pct=1.0, ruido_pct=0.3, resolucao_w=0.1, potencia_min_w=0.5, mede_tensao=False, mede_corrente=False,
                 origem="sem push local: o Pi consulta; 30 s assumido.")
    elif "tasmota de f" in fw:
        s.update(firmware="tasmota", modo="periodico", intervalo_s=60, erro_ganho_pct=1.0, ruido_pct=0.3, resolucao_w=1, potencia_min_w=1,
                 origem="Tasmota: padrão 300 s, mínimo 10 s; simulador usa 60 s (configurável).")
    elif "zigbee" in fw:
        s.update(firmware="zigbee2mqtt", modo="periodico", intervalo_s=60, erro_ganho_pct=1.0, ruido_pct=0.3, resolucao_w=1, potencia_min_w=1,
                 origem="Zigbee2MQTT consulta TS011F a cada 60 s.")
    elif "tuya" in fw or "positivo" in fw or "ekaza" in fw or "novadigital" in fw:
        s.update(firmware="tuya_local", modo="periodico", intervalo_s=30, erro_ganho_pct=1.0, ruido_pct=0.3, resolucao_w=0.1, potencia_min_w=1,
                 origem="Tuya local (tinytuya): consulta recomendada a cada 30 s ou mais.")
    elif "kron" in fw:
        s.update(firmware="mqtt_nativo", modo="periodico", intervalo_s=10, erro_ganho_pct=0.25, ruido_pct=0.1, resolucao_w=0.1, potencia_min_w=0.5,
                 origem="classe 0,5% (fabricante); intervalo MQTT de 10 s assumido.")
    elif "esphome" in fw or "pzem" in fw:
        s.update(firmware="esphome", modo="periodico", intervalo_s=60, erro_ganho_pct=0.5, ruido_pct=0.3, resolucao_w=0.1, potencia_min_w=0.5,
                 origem="ESPHome: 60 s por padrão.")
    else:
        s.update(firmware="desconhecido", modo="periodico", intervalo_s=60, erro_ganho_pct=1.0, ruido_pct=0.3, resolucao_w=1, potencia_min_w=1,
                 origem="intervalo não documentado: 60 s assumido.")
    return s

def main():
    ap = json.loads((CAT / "catalogo_aparelhos.json").read_text(encoding="utf-8"))
    mo = json.loads((CAT / "catalogo_monitoramento.json").read_text(encoding="utf-8"))
    out = dict(
        meta=dict(gerado_em=datetime.date.today().isoformat(), gerado_por="ferramentas/normalizar_catalogo.py",
                  origens=dict(pbe="lido na API pública do PBE/Inmetro em 17/11/2026", fabricante="ficha do fabricante (catálogo bruto, confiança alta)",
                               loja="ficha de loja (catálogo bruto)", derivado="calculado a partir de dado publicado (fórmula nas suposições do tipo)",
                               assumido="suposição documentada; não é dado medido"),
                  erro_medicao="Chips BL0937/BL0942/CSE7766/ADE7953: <1%. Aparelho sem calibração: 2–3%. O simulador sorteia um erro de ganho fixo por medidor (desvio em erro_ganho_pct) e um ruído por leitura."),
        tipos={k: dict(classe=v["classe"], fator_potencia=v["fp"], suposicoes=v["suposicoes"]) for k, v in TIPOS.items()},
        aparelhos={a["id"]: normalizar(a) for a in ap},
        sensores={m["id"]: sensor(m) for m in mo if m.get("recomendado_consumo")},
    )
    (CAT / "catalogo_simulador.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    conf = dict(consultado_em="2026-11-17", api="https://pbe.inmetro.gov.br/integracao/api/itens/buscar",
                refrigeradores_293={k: dict(kwh_dia_16c=v[0], kwh_dia_32c=v[1], kwh_mes=v[2], registro=v[3]) for k, v in PBE_REFRIG.items()},
                lavadoras_322={k: dict(kwh_ciclo_fria=v[0], kwh_ciclo_quente=v[1], tempo_ciclo_min=v[2], registro=v[3]) for k, v in PBE_LAVA.items()},
                condicionadores_166={k: dict(w_35c_total=v[0], w_35c_parcial=v[1], w_29c_parcial=v[2], espera_w=v[3], idrs=v[4], kwh_ano=v[5], registro=v[6]) for k, v in PBE_AR.items()},
                ventiladores_184={k: dict(w_baixa=v[0], w_media=v[1], w_alta=v[2], registro=v[3]) for k, v in PBE_VENT.items()},
                ventiladores_teto_323={k: dict(kwh_mes_alta=v[0], kwh_mes_media=v[1], kwh_mes_baixa=v[2], registro=v[3]) for k, v in PBE_TETO.items()})
    (CAT / "pbe_conferencia.json").write_text(json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")
    A = out["aparelhos"]
    print(len(A), "aparelhos,", len(out["sensores"]), "sensores")
    print("sem potência:", [k for k, v in A.items() if not v["potencia_w"]])
    print("corrigidos:", sum(any(n.startswith("CORRIGIDO") for n in v["notas"]) for v in A.values()),
          "| com suposição:", sum(any(n.startswith("ASSUMIDO") for n in v["notas"]) for v in A.values()),
          "| com registro PBE:", sum("registro_pbe" in v for v in A.values()))

if __name__ == "__main__":
    main()
