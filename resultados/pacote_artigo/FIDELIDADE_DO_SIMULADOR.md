# Fidelidade do simulador — de onde vem cada número (material para o artigo)

Preparado em 23/11/2026 a partir de `simulador/DIARIO.md`, `simulador/catalogos/catalogo_simulador.json`,
`simulador/validacao/resultados/validacao.json`, `simulador/dados/*.json` e da comparação com a casa real
Boa Energia (`scripts/realismo_boa_energia.py`). Decisão do Kleber (23/11/2026): a ausência de dado real por aparelho
entra como **limitação**, explicando que a simulação não usa valores inventados.

## 1. A regra: todo número tem origem registrada

O catálogo normalizado marca a origem de cada valor com um destes rótulos:

| rótulo | significado |
|---|---|
| `pbe` | lido na API pública do Programa Brasileiro de Etiquetagem (PBE/Inmetro), com o nº do registro |
| `fabricante` | ficha técnica do fabricante |
| `loja` | ficha do anúncio em loja |
| `derivado` | calculado a partir de dado publicado (a fórmula fica registrada) |
| `assumido` | suposição documentada, não é dado medido (aparece marcada no catálogo e no DIARIO) |

**Números do catálogo (229 aparelhos reais do mercado brasileiro, com marca e modelo):**
- Potência de operação: **157 de 229 (69 %) com fonte publicada** (fabricante 78, loja 42, PBE 29, derivado 8) e
  72 assumidas.
- Potência em espera (standby): 49 com fonte (PBE 36, loja 12, fabricante 1) e 180 assumidas — a maioria dos
  fabricantes não publica esse valor; o peso dele no consumo é pequeno.
- 61 aparelhos conferidos um a um no PBE; **14 valores corrigidos** pelo PBE. Exemplos: geladeira LG side by side
  57,5 → 36,3 kWh/mês (o valor da página da LG era de outra versão da norma); ventiladores com a potência "nominal"
  do anúncio trocada pelo valor do ensaio (ex.: EOS EVC60 150 → 93,4 W; ventilador de teto Arno VX10 150 → 29 W).
- 23 itens ficaram com confiança baixa (marcados); nas três casas, só a bomba de piscina do perfil 3 pesa no total
  (6–8 % do consumo dessa casa).

> Para o texto: **a maior parte dos números elétricos vem de fonte publicada; o que é suposição está marcado e
> justificado.** Não dizer "nenhum valor é assumido" — 31 % das potências e quase todas as esperas são.

## 2. Como cada aparelho "responde" (o comportamento elétrico no tempo)

O comportamento minuto a minuto de cada tipo segue o dado oficial quando ele existe; os detalhes que nenhuma fonte
publica são suposições registradas (DIARIO do simulador, A3):

| tipo | ancorado em dado publicado | suposição documentada |
|---|---|---|
| Geladeira / freezer | energia diária nas duas temperaturas do ensaio do PBE (16 °C e 32 °C), interpolada pela temperatura do cômodo → sazonalidade com base oficial | compressor 60 W + 0,12 W/L (coerente com 3 modelos que publicam: 94, 108, 124 W); ciclo de 45 min (faixa típica 30–60); pico de partida 4× por 1,5 s; degelo de 180 W por 18 min a cada 12 h |
| Ar-condicionado inverter | 3 pontos do ensaio do PBE (35 °C carga total e parcial, 29 °C parcial), espera e kWh/ano | 12 min em carga total ao ligar; carga ∝ (T externa − setpoint + 4)/15 |
| Lavadora | kWh/ciclo do PBE (água fria e quente) | duração = 40 % do tempo de ensaio; repartição entre etapas |
| Ventilador | potência nas três velocidades (PBE); a etiqueta corresponde a 1 h/dia (conferido) | uso pelo limiar de conforto do morador |
| TV | kWh/mês e espera do PBE | premissa de "5 h ligada + 19 h em espera" na etiqueta — **ainda a conferir na portaria do Inmetro** (Portaria 377/2021, televisores) |
| Chuveiro | potência nominal do fabricante | potência ligada à temperatura na hora do banho |
| Micro-ondas | potência e espera do PBE | — |
| Ferro, air fryer, forno | potência do fabricante | fração ligada do termostato (35 %, 65 %, 45 %) |

Os picos curtos de partida (1–2 s) existem de propósito: são o que os medidores reais, que enviam a cada 30–60 s,
não enxergam — e é por isso que o detector usa a energia acumulada, não só a potência.

## 3. Medidores e rede (o que chega ao Raspberry Pi)

- 80 modelos de medidor com parâmetros por firmware: intervalo de envio (Tuya 30 s; Zigbee2MQTT, ESPHome e Tasmota
  60 s; Shelly por evento + 1 mensagem por minuto; Kron Konect 10 s), resolução, potência mínima.
- Erro de medição coerente com os chips usados (BL0937, BL0942, CSE7766, ADE7953: < 1 %; aparelho sem calibração
  2–3 %): cada medidor recebe um erro de ganho fixo sorteado (desvio de 0,25–1 %) e ruído de 0,1–0,3 % por leitura.
- Faltas de energia: todos os aparelhos zeram e os medidores param de enviar. Taxa de 5 por ano, 45 min em média
  [assumido; conferir DEC/FEC da CPFL Paulista na ANEEL].
- O contrato MQTT (v1.2) é o de dispositivos reais; nenhum campo de gabarito sai pela rede (testado).

## 4. Moradores, hábitos e clima

- **Clima medido:** INMET, estação automática A763 (Marília-SP), 2023–2025, 26.146 leituras horárias; modelo =
  climatologia por mês e hora + anomalia diária AR(1) (ρ = 0,728, medido).
- **Moradores:** três famílias fictícias por faixa de renda (3–5, 5–10 e > 20 salários mínimos), com horários de
  trabalho e escola variando de 10 a 20 min por dia. As personas e os hábitos (banho de 7–15 min, TV à noite, limiar
  de conforto para ventilador e ar) são **suposições calibradas** para bater com as estatísticas oficiais abaixo.
- **Posse de aparelhos e usos finais:** PPH 2019 (Procel/Eletrobras), Sudeste, via Abrahão e Souza (2021).

## 5. Validação contra dados reais brasileiros (agregados)

| conferência | simulador | referência | situação |
|---|---|---|---|
| Consumo mensal, perfil 1 (3–5 SM) | 152 kWh/mês | EPE por renda: 133 (100–166) | dentro da faixa |
| Consumo mensal, perfil 2 (5–10 SM) | 285 kWh/mês | EPE por renda: 293 (220–366) | dentro |
| Consumo mensal, perfil 3 (> 20 SM) | 1.067 kWh/mês | EPE por renda: 925 (694–1.157) | dentro (algumas sementes de verão passam) |
| Forma do dia × curva de carga B1 da CPFL Paulista (ANEEL) | correlação 0,85 / 0,71 / 0,82 | curva média de consumidores residenciais | boa |
| Participação do chuveiro, perfil 1 | 35,8 % | PPH 2019 Sudeste: 34,8 % | próxima |
| Consumo médio Sudeste (todas as rendas) | — | EPE 2025: 183,3 kWh/mês | referência de ordem de grandeza |

**Comparação com UMA casa real medida (Boa Energia, Poli-USP, São Paulo, 29 dias de fev/2020, por hora; nova em
23/11/2026; `tabelas/realismo_boa_energia.csv` e `figuras/F7_realismo_forma_do_dia.png`):**

| medida (medidor geral, por hora) | casa real | perfil 1 | perfil 2 | perfil 3 |
|---|---|---|---|---|
| consumo médio (kWh/mês) | 313 | 151 | 291 | 1.099 |
| variação entre dias (coef. de variação) | 0,22 | 0,18 | 0,13 | 0,24 |
| hora do pico médio | 18 h | 19 h | 19 h | 20 h |
| pico ÷ média horária | 1,67 | 3,70 | 3,29 | 3,41 |
| fração do consumo entre 18 h e 23 h | 34 % | 51 % | 48 % | 45 % |
| correlação da forma do dia com a casa real | — | 0,35 | 0,34 | 0,49 |

Leitura honesta: a casa real tem o **mesmo porte do perfil 2** (313 × 291 kWh/mês), a mesma variação entre dias e o
pico no começo da noite; mas o consumo dela é **bem mais espalhado ao longo do dia** (banhos de manhã e à tarde: o
chuveiro dessa casa usa 10–25 % da energia de cada hora entre 6 h e 23 h, e há ar-condicionado durante a tarde). As
casas simuladas concentram mais o consumo à noite (banho das 18–20 h, como na curva média da distribuidora). Ou
seja: **o simulador reproduz bem a casa "média" (EPE, CPFL/ANEEL), não uma casa específica** — o que é o esperado de
hábitos sorteados em torno de médias, e vai para as limitações. (Ressalvas da comparação: a casa real é uma só, em
São Paulo e no verão; os valores dela são kVAh estimados por corrente; as casas simuladas são de Marília e as
sementes cobrem meses diferentes.)

## 6. Parágrafo sugerido para o artigo (adaptar)

> Como não há base pública brasileira com consumo por aparelho na resolução de minutos, os experimentos usam uma
> casa simulada. A simulação não usa valores arbitrários: cada aparelho é um modelo real do mercado brasileiro e cada
> parâmetro tem a origem registrada — 69 % das potências vêm do PBE/Inmetro, do fabricante ou de lojas, e 14 valores
> foram corrigidos pelos ensaios do PBE; o comportamento no tempo de geladeiras, ares-condicionados, lavadoras e
> ventiladores é ancorado nos pontos de ensaio do PBE, e o que nenhuma fonte publica (ciclo do compressor, picos de
> partida, hábitos) é suposição documentada. O clima vem de 26 mil leituras do INMET em Marília, e os medidores
> reproduzem o intervalo de envio e o erro dos chips de medição reais. As três casas ficam dentro das faixas de
> consumo da EPE por renda e têm correlação de 0,71 a 0,85 com a curva de carga residencial da CPFL Paulista
> (ANEEL); comparadas a uma casa real medida (Boa Energia), têm o mesmo porte e o mesmo pico noturno, mas um consumo
> mais concentrado à noite. Como limitação, o detector não foi avaliado com medições reais por aparelho; a
> arquitetura recebe um dispositivo físico pelo mesmo contrato MQTT, sem mudança no código.

## 7. O que ainda é suposição a conferir (não bloqueia, mas citar com cuidado)

1. Premissa de 5 h/dia da etiqueta de TV (Portaria Inmetro 377/2021) — não consegui abrir a portaria nesta sessão.
2. DEC/FEC da CPFL Paulista para a taxa de faltas (hoje 5/ano, 45 min, assumido).
3. Hábitos (tempo de banho, horas de TV) estão calibrados pelo total, não lidos diretamente na PPH.
4. Dígitos da EPE por renda (lidos de gráfico).
