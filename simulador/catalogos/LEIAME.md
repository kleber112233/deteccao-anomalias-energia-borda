# Catálogos da casa inteligente (TCC)

Pesquisa feita em 16/11/2026, no navegador, em sites de fabricantes, lojas oficiais, Frigelar, Leroy Merlin, KaBuM, Amazon.com.br, Google Shopping e no sistema do PBE/Inmetro. Os preços valem para essa data e servem só como referência.

## Arquivos

| Arquivo | Para quê |
| --- | --- |
| `catalogo_casa_inteligente.xlsx` | Abrir e conferir no Excel: abas Aparelhos, Monitoramento, Chips de medição e Firmwares, todas com filtros |
| `catalogo_aparelhos.csv` / `.json` | 229 aparelhos (as cargas da casa), para o simulador ler |
| `catalogo_monitoramento.csv` / `.json` | 101 equipamentos de monitoramento; 80 deles medem consumo de verdade (`recomendado_consumo`) |
| `referencia_chips_firmwares.json` | Precisão dos chips de medição e intervalos de cada firmware, com as fontes |

## Rodada 2: foco em medição de consumo (16/11/2026)

### Campos novos

**No acervo de monitoramento:**

- `mede_consumo`: sim / só estado / não / não confirmado.
- `recomendado_consumo`: indica se o item mede consumo de verdade.
- `perfil_sugerido`: 1 modesto, 2 mediano, 3 rico ou opcional.
- `chip_medicao`.
- `precisao` e `intervalo_envio_s`, com `status_precisao_intervalo` (confirmado / inferido pelo chip / desconhecido).
- `firmware_ou_metodo` e `fonte_precisao_url`.

**Nos aparelhos:**

- `perfil_sugerido`, definido pela faixa de preço dentro do tipo: o terço mais barato vai para o perfil 1 e o mais caro para o 3.
- `informa_consumo`, `como_informa` e `acesso_local`, para eletrodomésticos smart.

### Achados principais

**Tomadas e módulos que medem:**

- No Brasil só existem 2 interruptores de parede com medição: Intelbras ETS 2001 e 2002, que são tomada + interruptor.
- A linha Intelbras ETW **não** mede; o item ETW 1021 foi corrigido. Para iluminação, use mini módulos com medição atrás do interruptor: Shelly 1PM Mini, Sonoff MINI-ZB1GSP ou ZB1GP.

**Medidores de quadro:**

- O Kron Konect 120 (nacional) mede de 20 a 500 V, com 0,5% de precisão, MQTT e Modbus.
- Os Eastron SDM120 e SDM230 **não funcionam em 127 V**.
- Medidores com uma só entrada de tensão medem mal a segunda fase em casa bifásica.

**Precisão e intervalo (`referencia_chips_firmwares.json`):**

- O chip responde por menos de 1% de erro (BL0937, BL0942, CSE7766, ADE7953). O erro do aparelho depende da calibração: até cerca de 2–3% sem calibrar.
- Tasmota lê o sensor 1 vez por segundo e envia a cada 300 s por padrão (mínimo 10 s; PowerDelta envia por variação).
- ESPHome usa 60 s por padrão.
- Shelly envia por evento, a partir de 1 W e 5% de variação, e grava energia por minuto.
- Tuya local deve ser consultada a cada 30 s ou mais.
- Zigbee2MQTT consulta as tomadas TS011F a cada 60 s.
- **ESPHome assume 50 Hz por padrão:** no Brasil é preciso configurar 60 Hz.

**Eletrodomésticos smart:**

- Só 5 de 14 confirmam que informam o próprio consumo: 2 ares Samsung, lava e seca Samsung e LG, ar Midea.
- Samsung e LG só pela nuvem, com dados a cada ~15 min ou por dia.
- Só o Midea tem caminho local, pela comunidade.

**Escopo do catálogo:** só entra o que fica dentro da casa, ou seja, os aparelhos e os equipamentos que medem consumo. O Raspberry Pi 5 (4 GB) é a plataforma fixa do projeto e não faz parte do catálogo. Equipamentos Zigbee precisam de um adaptador USB ligado ao Pi.

## Campo `confianca`

- **alta:** dado do fabricante ou do PBE/Inmetro.
- **media:** dado de loja.
- **baixa:** dado incerto, conflitante ou inferido. Conferir antes de usar no artigo.

Um campo vazio significa que o dado não foi encontrado. Nenhum valor foi inventado.

## Cuidados com as unidades

- **Ar-condicionado:** a etiqueta atual do Inmetro informa kWh/ano. O campo `consumo_mensal_kwh` guarda esse valor dividido por 12.
- **Ventiladores:** o kWh/mês da etiqueta segue o uso padronizado do Inmetro (aparentemente cerca de 1 h/dia, a confirmar). Não é o consumo real da casa.
- **Chuveiros:** o kWh/mês segue o padrão de uso do Inmetro, não potência × tempo de banho.
- **Máquinas de lavar, lava-louças e algumas secadoras:** o consumo é por ciclo (`consumo_ciclo_kwh=` em `observacoes`).
- **TVs:** só existe o kWh/mês do Inmetro; a potência em uso não é publicada. O simulador precisa assumir um perfil de horas de uso.
- **Notebooks e desktops:** a "potência nominal" é a capacidade da fonte ou do carregador (o máximo), não o consumo típico.
- **Bombas d'água e de piscina:** a potência é a de eixo (cv/HP convertido). A potência elétrica absorvida é maior.
- **Aquecedores, air fryers, ferros, secadores, fornos e liquidificadores:** não têm etiqueta Inmetro. O consumo é potência × tempo de uso.
- **Purificadores:** a etiqueta mede eficiência em kWh por litro, e é isso que está no campo de classe.
- **Classes de geladeira e freezer:** convivem a escala nova (A–C, 2025–2030) e a antiga (A+++…), indicada no próprio campo.

## Avisos do acervo de monitoramento

- **"Funciona sem nuvem":** tomadas e medidores Tuya funcionam localmente (LocalTuya/tinytuya) só depois de obter a chave local uma vez pela nuvem Tuya. Isso está escrito no campo.
- **Itens que não servem no Brasil:**
  - Shelly Plug US Gen4: plugue americano e 120 V, fora da NBR 14136. Fica só como referência de API local.
  - IoTaWatt: não é vendido aqui.
  - Emporia Vue 3: importado.
- **Intervalo de envio:** quase nunca é documentado pelos fabricantes. Valores do Tasmota (TelePeriod padrão de 300 s, mínimo de 10 s) e do ESPHome (60 s, configurável) precisam ser conferidos na documentação oficial.
- **Homologação Anatel:** confirmada só em algumas tomadas. O restante está como "desconhecido".

## Itens a conferir

- O micro-ondas Brastemp BMO45AR é comercial (R$ 11 mil). Considerar retirar.
- O preço do Xbox Series S (R$ 5.199) parece alto.
- A potência do Electrolux LSP11 diverge entre lojas.
- Todos os itens com `confianca = baixa`.

## Fonte útil para calibração: API pública do PBE/Inmetro

É a mesma API que o site do PBE usa.

- **Buscar itens:** `POST https://pbe.inmetro.gov.br/integracao/api/itens/buscar?page=0&size=2000&sort=marca,ASC`, com um corpo como `{"idPrograma":289,"atributos":{"2000":"SAMSUNG"}}` (o atributo 2000 é a marca).
- **Nomes das colunas:** `GET /integracao/api/atributos/{id}`.

| Programa | idPrograma |
| --- | --- |
| Televisores | 289 |
| Lâmpadas LED | 290 |
| Fluorescentes compactas | 173 |
| Refrigeradores | 293 |
| Condicionadores de ar | 166 |
| Micro-ondas | 208 |
| Máquinas de lavar | 322 |
| Ventiladores (mesa, coluna, circulador) | 184 |
| Ventilador de teto | 323 |

## Rodada 3: camada normalizada para o simulador (17/11/2026)

- `catalogo_simulador.json`: gerado por `ferramentas/normalizar_catalogo.py`. Para cada aparelho traz potência em operação e em espera, consumo de referência com a unidade certa, corrente por tensão e os parâmetros de funcionamento (`funcionamento`). Cada número tem a origem: `pbe`, `fabricante`, `loja`, `derivado` ou `assumido`. As suposições de cada tipo estão em `tipos[...]["suposicoes"]`.
- `pbe_conferencia.json`: valores lidos na API do PBE/Inmetro em 17/11/2026, com o número do registro (61 aparelhos conferidos; 14 corrigidos).
- Não edite o `catalogo_simulador.json` à mão: mude o catálogo bruto ou o script e gere de novo.
- Itens resolvidos da lista "a conferir": micro-ondas Brastemp BMO45AR (comercial) saiu da casa do perfil 3 e deu lugar ao Panasonic NN-GB68QBRUK; ventilador Arno VB50 tem ensaio próprio no PBE (registro 004070/2020); Elgin Eco Inverter III e Midea AI Ecomaster 18000 confirmados no PBE. O preço do Xbox Series S e os demais itens de confiança baixa continuam pendentes.
