# Diário de bordo — simulador da casa (parte 1 do TCC)

Registro das decisões, com motivo, fonte e números, para virar a seção de métodos do artigo.
Convenção: **[medido]** veio de fonte oficial lida diretamente; **[derivado]** foi calculado a partir de
dado publicado; **[assumido]** é suposição minha, a conferir ou a defender no texto.

---

## 17/11/2026 — Etapa A: catálogo normalizado

### A1. Camada normalizada separada do catálogo bruto
- **Decisão:** o catálogo bruto (229 aparelhos, 101 medidores) não é alterado. O script
  `ferramentas/normalizar_catalogo.py` gera `catalogos/catalogo_simulador.json`.
- **Motivo:** o bruto guarda o que foi encontrado nas lojas e fabricantes; a camada normalizada guarda o
  que o simulador usa. Refazer é só rodar o script, e todas as suposições ficam num arquivo só.
- **Campos por aparelho:** `potencia_w` e `potencia_origem`; `standby_w` e `standby_origem`;
  `potencia_por_tensao_w` (quando o fabricante dá valores diferentes em 127 e 220 V);
  `consumo_referencia` (valor, unidade, condição, origem); `funcionamento` (parâmetros do padrão de
  funcionamento); `classe` (qual gerador usa); `fator_potencia`; `corrente_a` por tensão; `notas`.
- **Origens possíveis:** `pbe`, `fabricante`, `loja`, `derivado`, `assumido`.
- **Números:** 229 aparelhos, todos com potência; 61 com registro conferido no PBE; 14 corrigidos;
  45 com pelo menos uma suposição individual. 80 medidores com parâmetros de sensor.

### A2. Conferência na API pública do PBE/Inmetro [medido]
- **Como:** pelo navegador, em `https://pbe.inmetro.gov.br/integracao/api/itens/buscar`, filtrando pelo
  atributo 2001 (modelo). O shell do computador não alcança o site (bloqueio de rede), então os valores
  foram transcritos para o script e gravados em `catalogos/pbe_conferencia.json` com o nº do registro.
- **Achado 1 — geladeiras e freezers (programa 293):** o PBE publica o consumo diário em duas
  temperaturas de ensaio, 16 °C e 32 °C, além do kWh/mês. Exemplo: Consul CRD37MB = 0,6 e 1,3 kWh/dia,
  29,3 kWh/mês. O kWh/mês é praticamente a média dos dois pontos × 30,4. **Uso:** o simulador interpola a
  energia diária pela temperatura do cômodo, o que dá sazonalidade com base oficial.
- **Achado 2 — ar-condicionado (programa 166):** o PBE publica a potência a 35 °C em carga total, a
  35 °C em carga parcial e a 29 °C em carga parcial, a potência em espera, o IDRS e o kWh/ano. Exemplo:
  LG S3-Q09AA31F = 750 / 289 / 196,5 W, espera 4 W, IDRS 7,0, 311,2 kWh/ano. **Uso:** modelo de
  modulação do inverter ancorado nesses três pontos.
- **Achado 3 — lavadoras (programa 322):** kWh/ciclo em água fria e quente e o tempo do ciclo de ensaio
  (188 a 300 min). Esse tempo é do ensaio, não do programa do dia a dia.
- **Achado 4 — ventiladores (programas 184 e 323):** potência nas três velocidades. O kWh/mês da
  etiqueta é exatamente potência × 30 h (128 W → 3,84 kWh), ou seja, **1 h por dia**. Isso confirma a
  dúvida que estava no LEIAME. Nos ventiladores de teto o programa só dá kWh/mês; a potência sai de
  kWh × 1000 / 30.
- **Correções feitas com o PBE:**
  - LG Side by Side GC-L257SLP1: 57,5 → **36,3 kWh/mês** (registro 013224/2025). O valor antigo vinha da
    página da LG e é de outra versão da norma. Esta geladeira está na casa do perfil 3.
  - Ventiladores: EOS EVC60 150 → 93,4 W; Britânia BVT320P 75 → 62,7 W; teto Britânia Cancun 126 → 51 W;
    teto Ventisol Fênix 130 → 65 W; teto Arno VX10 150 → 29 W; teto EOS EVX110B 150 → 38 W. As lojas
    informam a potência "nominal" do motor; o ensaio mede bem menos.
  - Ares-condicionados com diferença maior que 3% entre loja e PBE foram trocados pelo valor do PBE.
- **Não encontrados no PBE:** Brastemp BRM62, LG OLED55B6, ares EOS, Gree e Electrolux N09F/SP12F.
  Ficam com o dado de loja.

### A3. Suposições por tipo de aparelho [assumido, salvo indicação]
Texto completo em `catalogo_simulador.json → tipos → suposicoes`. Resumo:

| Tipo | Modelo | Base | Suposição |
| --- | --- | --- | --- |
| Geladeira, freezer | compressor liga/desliga | kWh/dia a 16 e 32 °C [medido] | compressor de 60 W + 0,12 W/L (70–160 W); período de 45 min; pico de partida de 4× por 1,5 s; degelo frost free de 180 W por 18 min a cada 12 h; abrir a porta soma até 12% |
| Ar inverter | modulação contínua | 3 pontos do PBE [medido] | 12 min em carga total ao ligar; carga pedida = (T externa − setpoint + 4) / 15, entre 25% e 100% |
| Ar on/off | ciclos de 12 min | potência total do PBE [medido] | ventilador de 40 W com o compressor parado |
| Chuveiro | potência constante por banho | potência nominal | eletrônico: 30–100%; multitemperaturas: 33/55/78/100% |
| TV | ligada com variação de ±15% | kWh/mês e espera do PBE [medido] | P = (kWh/mês × 1000/30 − 19 h × espera) / 5 h. A premissa "5 h ligada + 19 h em espera" precisa ser conferida na portaria do Inmetro |
| Lavadora | etapas | kWh/ciclo do PBE [medido] | duração = 40% do tempo de ensaio (45–120 min); repartição da energia entre as etapas |
| Lava-louças | etapas com resistência | kWh/ciclo do fabricante | ciclo de 110 min |
| Ferro, air fryer, forno | pré-aquecimento + termostato | potência do fabricante | fração ligada de 35%, 65% e 45% |
| Micro-ondas | potência cheia ou ciclos de 30 s | potência e espera do PBE [medido] | — |
| Notebook, desktop | consumo típico | potência da fonte | 35% do carregador; 13–25% da fonte |
| Bombas | motor | potência de eixo | elétrica = eixo / 0,60 (água) ou / 0,65 (piscina) |
| Portão | acionamento de 15 s | potência do anúncio | espera de 3 W |

Os picos de partida (1–2 s) e os acionamentos curtos existem de propósito: é o que os medidores com
envio a cada 30–60 s não enxergam.

### A4. Itens com confiança baixa (26)
- **Resolvidos pelo PBE (3):** Elgin Eco Inverter III 9000 (834 W, 327 kWh/ano, IDRS 7,0), Midea AI
  Ecomaster 18000 quente e frio (573,7 kWh/ano confirmado como anual) e Arno VB50 (tem ensaio próprio:
  79,1 / 109,5 / 132,6 W; o cadastro antigo repetia os números do VF42).
- **Mantidos como baixa (23):** bombas de piscina, motores de portão, wallbox IPE, roteadores sem dado
  típico, secadoras Electrolux, Switch 2 e outros. O campo `revisao_confianca_baixa` de cada um avisa que
  os parâmetros são assumidos. Nas três casas, os itens de confiança baixa em uso são: notebook Lenovo
  (perfil 2), portão Garen DZ Niid (perfil 2), bomba de piscina Sodramar BVV-150, roteador Deco M5 e
  portão Rossi (perfil 3). Nenhum pesa no total da casa, exceto a bomba de piscina (6 a 8% do consumo do perfil 3).
- **Micro-ondas Brastemp BMO45AR (comercial, R$ 11.124):** trocado na casa do perfil 3 pelo Panasonic
  NN-GB68QBRUK (30 L, de embutir, 220 V, 1450 W, R$ 2.564). Custo dos aparelhos do perfil 3:
  R$ 96.016,82 → R$ 87.456,87.

### A5. Modelo dos medidores
- Parâmetros por modelo em `catalogo_simulador.json → sensores`: firmware, modo (periódico ou por
  evento), intervalo, limiar de evento, erro de ganho, ruído, resolução, potência mínima, canais e relé.
- **Intervalos:** Tuya local 30 s; Tapo 30 s (consulta do Pi; assumido); Zigbee2MQTT 60 s; ESPHome 60 s;
  Tasmota 60 s (padrão 300 s, mínimo 10 s); Shelly por evento (1 W e 5%; 10 W e 5% nos modelos EM) mais
  uma mensagem por minuto; Kron Konect 10 s (assumido).
- **Erro:** cada medidor recebe um erro de ganho fixo sorteado uma vez (desvio de 1% nos modelos Tuya,
  Tapo e Zigbee; 0,5% nos Shelly; 0,25% no Kron), limitado a 3 desvios, mais ruído de 0,1–0,3% por
  leitura. Coerente com "chip < 1%, aparelho sem calibração 2–3%".
- **Contagem de canais:** perfil 1 = 5, perfil 3 = 31, como no resumo dos cenários. No perfil 2 o
  simulador conta **14** e o resumo dizia 15: o medidor geral de duas pinças (uma por fase) é tratado como
  um canal só (potência total da casa).

---

## 17/11/2026 — Etapa B: moradores, rotinas, clima e metas

### B1. Clima de Marília [medido]
- **Fonte:** INMET, estação automática A763 (Marília-SP, lat −22,235, lon −49,965, 660 m, em operação
  desde 14/05/2017), arquivos anuais de dados históricos de 2023, 2024 e 2025.
- **Como:** os três arquivos foram lidos no navegador direto do portal do INMET; 26.146 leituras
  horárias válidas de temperatura do ar, convertidas de UTC para UTC−3.
- **O que ficou em `dados/clima_marilia_inmet.json`:** média por mês e hora local (12 × 24), desvio-padrão
  da média diária em cada mês e autocorrelação de um dia das anomalias (0,728).
- **Números:** mês mais quente setembro/dezembro (25,2 °C de média; máxima média de 32,1 °C em
  setembro); mais frio julho (19,7 °C; mínima média de 15,1 °C). Extremos do período: 39,0 °C e 5,8 °C.
- **Modelo:** temperatura do dia = climatologia horária do mês + anomalia diária AR(1) com ρ = 0,728 e o
  desvio do mês. Temperatura interna = 0,5 × externa + 0,5 × média do dia + 1 °C [assumido].
- **Limite:** três anos não formam uma normal climatológica; a A763 é a única série local. Dizer isso no artigo.

### B2. Personas [assumido: cenário fictício]
Em `dados/personas.json`, editáveis no modo de montagem.
- **Perfil 1 — Família Souza (3):** Marlene, 41, auxiliar de limpeza (sai 6h30, volta 17h15); José
  Carlos, 44, pedreiro (6h15–18h); Kauã, 15, estuda de manhã (volta 12h40).
- **Perfil 2 — Família Oliveira (4):** Ricardo, 39, analista de sistemas em regime híbrido (home office
  segunda, quarta e sexta); Fernanda, 37, professora; Laura, 12, e Miguel, 8, estudam de manhã.
- **Perfil 3 — Família Almeida (5):** Eduardo, 52, médico, carro elétrico; Patrícia, 49, advogada (home
  office terça e quinta); Beatriz, 20, universitária; Gustavo, 17, ensino médio; Helena, 76, aposentada.
  Uma funcionária de segunda a sexta entra como hábito da casa (lavanderia e ferro de manhã).
- **Variação:** cada horário recebe um desvio normal de 10 a 20 min por dia; no fim de semana há
  probabilidade de saída; home office muda a ocupação da casa.

### B3. Hábitos [assumido, calibrável]
- Banho: 7 a 15 min por pessoa, um por dia, segundo banho com 15–30% de chance acima de 30 °C. Potência
  do chuveiro ligada à temperatura na hora do banho (máxima abaixo de 18 °C, mínima acima de 34 °C).
- TV da sala à noite com alguém acordado em casa; ventilador no quarto com temperatura interna acima de
  25,5 °C às 22h; ar no quarto com temperatura externa às 21h acima de 23,0 °C (perfil 2) ou 22,5 °C
  (perfil 3); lavagem de roupa 3, 4 e 6 vezes por semana; carro elétrico com 40 ± 15 km por dia útil e
  0,16 kWh/km.
- Carga de base não medida (carregadores, relógios, espera de aparelhos fora do catálogo): 18, 40 e 60 W.

### B4. Metas de validação
- **EPE [medido, com ressalva]:** consumo médio residencial do Sudeste = **183,3 kWh/mês**; Nordeste =
  134,9 (Anuário Estatístico de Energia Elétrica 2026, ano-base 2025, factsheet). Li esses números no
  resumo de busca do Google sobre o PDF da EPE, não no PDF aberto. **Abrir o PDF antes de citar.**
- **Faixas por perfil [assumido]:** a EPE só publica a média. Perfil 1: 130–200; perfil 2: 280–450;
  perfil 3: 900–1700 kWh/mês.
- **Curva diária:** nos perfis 1 e 2, a janela de 3 h mais carregada deve começar entre 17h e 19h e a
  potência média das 18h às 21h deve ser pelo menos 1,5 vez a média do dia.
- **Uso final (informativo):** participações da PPH ano-base 2005 citadas de memória (chuveiro 24%,
  geladeira e freezer 27%, condicionamento 20%, iluminação 14%, TV 9%). **Trocar pela PPH 2019.**

### B5. Calibração feita (para não esconder nada)
Primeira rodada (56 dias por perfil): 136, 274 e 1035 kWh/mês. Perfil 2 ficou 2% abaixo da faixa e o
perfil 1 no limite, variando com a semente. Ajustes, todos em hábitos:
1. Limiar do ar do perfil 2: 24,0 → 23,0 °C.
2. Temperatura em que o chuveiro vai para a potência mínima: 30 → 34 °C.
3. Carga de base: 12 → 18 W (perfil 1) e 30 → 40 W (perfil 2).
4. Correção de erro: banho "à noite" de quem volta da escola ao meio-dia estava saindo às 13h30; agora
   nunca começa antes das 17h30. O pico das 13h sumiu e o da noite subiu.

As faixas foram definidas antes da primeira rodada e não foram alteradas.

### B6. Tarifa
- Marília é atendida pela CPFL Paulista. A ANEEL aprovou reajuste médio de +12,13% em abril de 2026
  (notícia de 22/04/2026). **Não consegui a tarifa B1 exata**: o painel usa R$ 0,95/kWh com tributos
  [assumido] e os adicionais de bandeira de 2024–2025 (R$ 1,885, 4,463 e 7,877 por 100 kWh) [a conferir].
  Tudo em `dados/tarifas.json`. Tarifa Social não aplicada.

---

## 17/11/2026 — Etapa C: simulador

### C1. Arquitetura
- **Resolução de 1 s para o sinal real** e mensagens dos medidores a cada 10–60 s. É essa diferença que
  permite mostrar o pico que some. Um dia = 86.400 amostras por aparelho.
- **Um dia por vez**, com estado que passa de um dia para o outro (ciclo do compressor, uso que cruza a
  meia-noite, contador de energia do medidor).
- **Sementes independentes** por aparelho, por medidor e por subsistema (clima, rede, comportamento,
  falhas). Injetar uma falha num aparelho não altera os outros (há teste).
- **Falhas aplicadas sobre a potência real**, antes do medidor: o medidor distorce a falha do mesmo jeito
  que distorce o consumo normal.
- **Cargas resistivas** (chuveiro, ferro, air fryer, forno, cafeteira) variam com o quadrado da tensão.
- **Tamanho:** cerca de 2.900 linhas (Python, HTML e JavaScript), 26 testes.

### C2. Rede elétrica [assumido]
- Tensão entre 0,92 e 1,05 pu (faixa adequada do PRODIST), com afundamento de 2% por volta das 19h30.
- Faltas: 5 por ano, duração média de 45 min. Conferir DEC e FEC da CPFL Paulista na ANEEL.
- Na falta, todos os aparelhos zeram e **os medidores param de enviar** (voltam 20 s depois). No gabarito a
  falta tem `alerta_de_aparelho = False` e não gera rótulo de anomalia.

### C3. Falhas e gabarito
- Sete tipos: magnitude, fora de horário, duração excessiva, pico, queda, consumo não explicado, falta de energia.
- O gabarito guarda a janela pedida e a **janela em que o sinal mudou de fato**. Se nada mudou (falha de
  magnitude num ferro que não foi usado), a linha fica com `efetiva = False`. Numa rodada de 28 dias do
  perfil 1 com 12 falhas, 2 ficaram não efetivas. Isso evita cobrar do detector o que não existiu.
- No dataset rotulado, a falha marca o canal que mede o aparelho (`canal_direto = 1`) e também o medidor
  geral. No perfil 1 só 4 aparelhos têm canal próprio: a maioria das falhas só aparece no geral.
- O gabarito nunca vai para o MQTT (trava no publicador e teste).

### C4. Contrato MQTT
Em `docs/CONTRATO_MQTT.md`. Tópicos conforme o combinado. Para medidores que somam mais de um cômodo ou
ficam no quadro, `{comodo}` = `quadro`. Medidores de vários canais usam o mesmo tópico e o campo `canal`.

### C5. Números de desempenho (no ambiente de teste)
| Perfil | 28 dias simulados em | Mensagens por dia | Consumo com medidor próprio |
| --- | --- | --- | --- |
| 1 | 5 s | 14 mil | 25% |
| 2 | 10 s | 35 mil | 73% |
| 3 | 19 s | 66 mil | 95% |

A última coluna é a diferença central entre os perfis: quanto do consumo a casa consegue medir.

### C6. Validação (`python validacao/validar.py`, semente 42, 14 dias em cada estação)
| Perfil | kWh/mês | Faixa | Início da janela de 3 h mais carregada | Pico/média | Resultado |
| --- | --- | --- | --- | --- | --- |
| 1 | 148,3 | 130–200 | 17h | 3,49 | aprovado |
| 2 | 303,1 | 280–450 | 17h | 3,00 | aprovado |
| 3 | 1058,7 | 900–1700 | 18h | 2,64 | aprovado |

- Com as sementes 7 e 123: 156,0 / 305,0 / 1133,9 e 135,6 / 286,3 / 994,2. Todos aprovados; a variação de
  cerca de ±7% vem do clima sorteado.
- Perfil 1 fica em 81% da média do Sudeste (183,3).
- Uso final no perfil 1: chuveiro 34%, geladeira 21%, ventiladores 15%, iluminação 3,5%, TV e
  eletrônicos 4,6%, outros 22%. Iluminação bem abaixo da referência antiga (14%) porque a casa é toda LED.
- **Ponto estranho a investigar:** nos três perfis o bloco de abril deu consumo diário maior que o de
  julho. Pode ser só a anomalia de temperatura sorteada naquelas duas semanas; rodar o ano inteiro antes
  de escrever sobre sazonalidade.
- Figuras em `validacao/resultados/`: consumo mensal × meta, curva diária, uso final e "real × medidor".

### C7. Testes
`python -m pytest -q` → 26 aprovados. Cobrem: catálogo completo e com origem; cenários compatíveis e
custos iguais aos do resumo; tomada de 10 A com chuveiro reprovada; mesma semente = mesmo resultado;
medidor geral = soma + base; geladeira dentro de 8% da etiqueta a 24 °C; lavadora dentro de 6% do
kWh/ciclo; uso que cruza a meia-noite; sensor periódico perde pico de 2 s mas conta a energia; sensor por
evento; falta de energia; os sete tipos de falha; gabarito fora do MQTT; exportação; tempo real com
falha e comando de relé; API web.

O painel foi aberto num navegador automatizado: iniciou a casa do perfil 2, injetou duas falhas e abriu a
montagem sem erro de JavaScript. Não testei com um broker MQTT de verdade nem no Windows.

---

## Pendências (em ordem de importância para o artigo)
1. Abrir o PDF do Anuário da EPE e confirmar 183,3 kWh/mês.
2. Consultar a PPH 2019 (PPH Web): posse, tempo de banho, horas de TV, uso de ar-condicionado no
   Sudeste. Hoje nada disso está "calibrado pela PPH"; são suposições.
3. Conferir a premissa de 5 h/dia da etiqueta de TV.
4. Tarifa B1 da CPFL Paulista e bandeiras vigentes.
5. DEC e FEC da CPFL Paulista para a taxa de faltas.
6. Rodar 365 dias por perfil e olhar a sazonalidade.
7. Testar com Mosquitto e no Windows com Python 3.11.
8. Decidir o dispositivo físico (tomada com medição numa geladeira por 2–4 semanas): serviria para
   validar o período do compressor (45 min) e o pico de partida, que hoje são assumidos.

---

## 17/11/2026 — Revisão do fechamento da etapa 1

### R1. Ano inteiro (365 dias, semente 42)
- Perfil 1: média de 145,9 kWh/mês (dentro da faixa de 130–200); perfil 2: 301,0 kWh/mês (dentro da faixa de 280–450). 365 dias rodam em 6 s (perfil 1) e 14 s (perfil 2).
- Chuveiro: 20–30% maior no inverno (perfil 1: 44–61 kWh/mês), como esperado.
- **Problema:** ventiladores e ar-condicionado oscilam demais de um mês para outro (ventilador do perfil 1: março 6, abril 30, dezembro 63 kWh/mês). Duas causas somadas:
  1. limiar fixo de temperatura (liga tudo acima de 25,5 °C, nada abaixo), com a temperatura das 22h encostada nesse limiar em boa parte do ano;
  2. o ano sorteado tem meses bem fora da climatologia do INMET (março −2,3 °C, agosto −3,0 °C, dezembro +2,6 °C).
- **Correção prevista:** trocar o limiar fixo por probabilidade que cresce com a temperatura (curva logística) e por limiar próprio de cada morador. Fazer antes de congelar os datasets.
- O "abril maior que julho" da validação vem disso: o abril sorteado ficou 1,9 °C acima do normal.

### R2. MQTT ponta a ponta com broker real
- Broker amqtt local (o shell não tem Mosquitto), perfil 2, modo tempo real a 60×, 5 minutos simulados.
- 120 mensagens publicadas, 120 recebidas por um cliente que fez o papel do Pi; nenhum campo de gabarito no MQTT.
- Comando `{"acao":"desligar"}` publicado pelo "Pi" em `casa/perfil2/sala/t2/comando`: a tomada T2 cortou e passou a enviar 0 W e `estado: desligado`.
- Alerta publicado em `casa/sistema/alertas` apareceu no painel.
- Observação: o medidor geral do perfil 2 informa 220 V e uma potência só, porque as duas pinças foram juntadas num canal. Um medidor real de duas pinças informaria cada fase (127 V). Ajuste menor.

### R3. O que falta, pelo que a etapa 2 precisa (ver plano: E1–E6, F0–F1)
- Datasets congelados (treino só normal, calibração e teste com falhas, 5 sementes, divisão 60/20/20).
- Gerador de carga para E3 e E4 (N dispositivos, frequência ajustável, a partir de um dataset gravado).
- Registro das falhas injetadas ao vivo em arquivo, com hora simulada e hora do relógio (E5 e demonstração).
- Limiares probabilísticos (R1) antes do congelamento.
- Ações do Kleber: rodar no Windows; preparar o Pi (64 bits, dissipador, Mosquitto) e fazer a casa publicar nele; repositório; decidir o dispositivo físico.

---

## 17/11/2026 — Dados reais brasileiros para calibração e testes

- **EPE confirmada:** 183,3 kWh/mês no Sudeste (2025), lido no PDF do Anuário 2026 (sumário executivo, p. 4). Pendência 1 resolvida.
- **PPH 2019, citável:** Abrahão e Souza (2021) publicaram, a partir dos microdados da PPH 2018–2019, a posse por domicílio e o consumo por uso final por região. Extraído para `dados/pph2019_sudeste.json`. Sudeste 2019: chuveiro 34,8%, geladeira e freezer 36,5%, ar e ventiladores 14,4%, iluminação 4,9%, TV e eletrônicos 3,0%, outros 6,5%.
  - `metas_validacao.json` trocou os números da PPH 2005, que eu tinha citado de memória, por estes. A figura 3 da validação passa a comparar com eles.
  - Comparação com o perfil 1: chuveiro 34,0% (bate); geladeira e freezer 21,0% (baixo); ar e ventiladores 15,0% (bate); iluminação 3,5%; TV e eletrônicos 4,6%; **outros 21,9% (alto)**. Hipóteses a testar: carga de base, air fryer, micro-ondas e cafeteira altos demais; e geladeira de 100 W baixa (as autoras usam 250 W × 360 h/mês, mas a etiqueta do PBE de cada modelo é mais confiável que essa premissa).
- **EPE por renda (2019):** kWh por pessoa por ano por faixa de renda e por aparelho, em `metas_validacao.json → epe_renda`. Pela tabela, o perfil 3 (5 moradores, faixa de maior renda) daria cerca de 925 kWh/mês; o simulador dá 1.059 (+14%). O chuveiro do perfil 1 gasta por pessoa (~200 kWh/ano) o que a EPE atribui às faixas de 10 a 20 salários mínimos. A ponderar: a EPE faz a média incluindo domicílios sem chuveiro.
- **Ainda não mexi no simulador.** As correções de calibração entram junto com os limiares probabilísticos (revisão anterior), antes de congelar os datasets.
- Datasets reais para a parte 2 em `../tcc artigo/fontes_brasileiras.md`.

---

## 17/11/2026 — Dados reais baixados e calibração com eles

### D1. Dados reais em `TCC/dados_reais/` (ver `LEIAME.md` lá)
- **Baixados do GitHub:** Boa Energia (casa brasileira, por hora, 58 dias), Brazilian Smart Home Testbed (luz e presença por cômodo, ago–out/2019) e os parâmetros do LIT simulado (não são medições).
- **ANEEL:** o portal é bloqueado pela rede do computador. Li o CSV de 329 MB no navegador e gravei só um extrato: a forma (normalizada pela média do dia) das curvas residenciais B1 de 15 min da CPFL Paulista 2023 (10 consumidores tipo) e a média de 62 distribuidoras, por tipo de dia. CPFL, dia útil: pico às 19h, com 1,99 vez a média do dia.
- **Para baixar à mão:** IFES Serra (Mendeley, 79,7 MB), ANEEL completa em Parquet (34 MB) e ONS. Links no LEIAME.

### D2. O que a casa real do Boa Energia mostrou (fev–mar/2020, verão)
- 317 kVAh/mês no total, 79 só de chuveiro e 54 de ar-condicionado.
- Cerca de 45% da energia do chuveiro foi gasta antes do meio-dia (banhos de manhã).
- Conclusão: a EPE por renda (25 kWh/mês de chuveiro para o perfil 1) subestima o chuveiro; PPH (64 por domicílio) e Boa Energia (79) ficam acima. O perfil 1 (51) está dentro do intervalo das fontes. **Não reduzi o chuveiro do perfil 1.**

### D3. Mudanças no simulador
1. **Ventilador e ar-condicionado com decisão probabilística:** curva logística em torno do limiar de cada morador (limiar do perfil + desvio pessoal fixo de 0,8 °C; inclinação de 1,0 °C no ventilador e 1,2 °C no ar). Timer: 40% das noites o ventilador desliga após 2–4 h; 35% das noites o ar desliga após 3–5 h. Todos os parâmetros são ASSUMIDOS.
   - Resultado (perfil 1, 365 dias): ventilador com média de 21 kWh/mês, perto da PPH (18 por domicílio no Sudeste). A variação de um mês para outro continua grande porque o ano sorteado tem meses fora do normal (dezembro 2,6 °C mais quente).
2. **Horário do banho espalhado:** à noite, Normal(19h45, 75 min) depois de chegar em casa; de manhã, logo após acordar; 15% de chance de trocar de período no dia.
   - Motivo: todos os banhos caíam entre 18h e 19h, e a correlação com a curva real da CPFL era de 0,61 (perfil 1). Agora é **0,85** (perfil 1), **0,71** (perfil 2) e **0,82** (perfil 3).
3. **Banho do perfil 2 mais curto** (8, 10, 9 e 7 min; segundo banho com chance de 10%). O chuveiro dava 112 kWh/mês, acima até da casa real.
4. **Metas por perfil pela EPE por faixa de renda** (substituem as faixas que eu tinha assumido; as antigas ficaram registradas em `metas_validacao.json`).
   - Faixas de renda ASSUMIDAS: perfil 1 = 3–5 SM, perfil 2 = 5–10 SM, perfil 3 = mais de 20 SM.
   - Meta = kWh por pessoa por ano da faixa × moradores ÷ 12, menos os aparelhos que a casa não tem; faixa de ±25%.
   - Resultados: perfil 1 = **133** (100–166); perfil 2 = **293** (220–366); perfil 3 = **925** (694–1.157).
5. **Medidor geral de duas pinças (perfil 2) por fase:** canal 1 = fase A e canal 2 = fase B, a 127 V. Aparelhos de 220 V entram metade em cada fase; os de 127 V alternam de fase por cômodo (ASSUMIDO). O consumo não explicado entra na fase A. A soma das fases bate com o total real (diferença < 0,01% sem o erro de ganho). O perfil 2 volta a ter 15 canais, como no resumo original.
6. **Validação** compara a curva do dia útil com a forma real da CPFL Paulista (figura 2, com a correlação r).

### D4. Validação depois da calibração (semente 42, 14 dias por estação)
| Perfil | kWh/mês | Meta EPE | Correlação com a CPFL | Resultado |
| --- | --- | --- | --- | --- |
| 1 | 152,4 | 100–166 | 0,85 | aprovado |
| 2 | 284,8 | 220–366 | 0,71 | aprovado |
| 3 | 1.067,3 | 694–1.157 | 0,82 | aprovado |

- **Diferenças que ficam, com explicação:**
  - O pico da casa simulada é mais alto que o da CPFL (pico/média de 2,7–3,0 contra 2,0) e há um pico de manhã e um vale no meio do dia. A curva da ANEEL é a média de muitas casas com horários variados; uma casa só é mais "pontuda".
  - Geladeira e freezer abaixo da EPE e da PPH: as casas usam modelos novos, com a etiqueta do PBE (25–36 kWh/mês). O estoque real é mais antigo e muitas casas têm mais de uma geladeira. Não mexi, porque a etiqueta é o dado oficial do modelo escolhido; vale citar no artigo.
- Testes: 28 aprovados (novos: medidor geral por fase e ventilador sem "tudo ou nada").

### D5. Próximos passos da etapa 1
1. Congelar os datasets (60/20/20, 5 sementes, Parquet, manifesto).
2. Gerador de carga para E3 e E4 (N canais, ritmo ajustável, a partir de um dataset gravado).
3. Registro em arquivo das falhas injetadas ao vivo (E5 e demonstração).
4. Quando os arquivos baixados à mão chegarem: testar no IFES o tratamento de faltas de energia e usar o Boa Energia como teste com dado real.


## Etapa 1 — fechamento (datasets, carga, registro ao vivo)

### F1. Datasets congelados v1 (`TCC/datasets/v1/`)
- 3 perfis × 5 sementes × 120 dias = 15 conjuntos, 90 arquivos, 864 MB em Parquet (zstd). Manifesto com SHA-256 de cada arquivo e do código e dados de entrada.
- **Divisão temporal 60/20/20** dentro de cada semente (72 + 24 + 24 dias). Escolhi a divisão no tempo, e não sorteada, porque o detector no Pi vai sempre ver o futuro depois de aprender com o passado; sortear dias misturaria estações e inflaria o resultado.
- **Treino sem falha injetada.** As faltas de energia da rede continuam acontecendo (0 a 2 por conjunto), porque acontecem na vida real; ficam no gabarito com `alvo = rede`.
- **Calibração e teste com tipos balanceados:** 17 falhas em cada (≈5 por semana, ASSUMIDO), os 7 tipos em rodízio embaralhado e 60% num aparelho com medidor próprio (ASSUMIDO, para haver casos suficientes no canal direto). Total 510 falhas; 448 efetivas (as demais caíram em horário em que o aparelho estava desligado).
- **Cada semente começa num mês diferente** (passo de 73 dias), para o conjunto inteiro cobrir o ano.
- kWh/mês: perfil 1 de 147 a 163; perfil 2 de 288 a 303; perfil 3 de 967 a 1.192. As sementes 4 e 5 do perfil 3 (primavera e verão) passam um pouco da faixa anual (1.157) por causa do ar-condicionado; aceitei porque a meta EPE é média do ano.
- Leitura: `casasim.datasets.carregar(pasta, "treino")` devolve sem as colunas de gabarito.

### F2. Gerador de carga (E3/E4) — `casasim/carga.py`
- Reenvia a partição de teste de um conjunto congelado, multiplicada em N casas virtuais (`casa/carga1`, `casa/carga2`...). Cada canal manda uma mensagem a cada `--intervalo` s, com fase própria (os aparelhos reais não sincronizam).
- Rampa "minuto:casas" e CSV por segundo (casas, canais, enviadas, taxa-alvo, atraso).
- Medido sem broker: ~3.000 mensagens/s sustentadas. Basta para o Pi; o gerador deve rodar no notebook.

### F3. Registro ao vivo (E5) — `RegistroAoVivo` em `tempo_real.py`
- JSON Lines em `registros/`: sessão iniciada, falha injetada (hora simulada, hora real, velocidade, duração real), comando recebido, alerta recebido (com as falhas ativas naquele instante), mudança de velocidade e gabarito de cada dia concluído.
- Ligado por padrão no painel (`/api/iniciar`) e no `tempo-real`. Não passa pelo MQTT.

### F4. Testes
- 32 aprovados (novos: plano balanceado, treino limpo e gabarito escondido, rampa do gerador de carga, registro ao vivo).

---

## 22/11/2026 — Empacotamento (para a parte 2)
- `pyproject.toml` ganhou `[tool.setuptools.packages.find] include = ["casasim*"]`. Sem isso, `pip install -e ../simulador`
  (usado pelo venv do detector) falhava: o setuptools achava várias pastas candidatas a pacote (`dados`, `cenarios`,
  `catalogos`...). Nada muda no código nem nos dados; `casasim/dados.py` continua lendo as pastas a partir do próprio
  arquivo. A instalação editável cria `casasim.egg-info/` aqui (pode ser ignorado).


## 23/11/2026 — gerador de carga para o E3/E4 (Claude)
- `Publicador` ganhou `client_id` e `assinar` (padrão igual ao de antes: "casasim", assina comandos e alertas).
  Motivo [medido]: dois geradores com o mesmo client_id se derrubavam no broker e metade das mensagens se perdia.
- `casasim carga` ganhou `--prefixo` e `--processos N` (N geradores em paralelo, cada um com o prefixo
  `<prefixo>K-` e a sua parte da rampa; `carga.executar_em_processos`). Cada gerador usa client_id próprio.
- Roteiro do E3/E4 em `TCC/pi/e3_pc.py` (detalhes no DIARIO do detector, K10).
