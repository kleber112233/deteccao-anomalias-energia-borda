# Contrato MQTT entre o simulador da casa e o Raspberry Pi

Versão 1.2 (17/11/2026; medidor geral por fase no perfil 2; casas virtuais do gerador de carga e registros dos experimentos). Este é o único canal entre a parte 1 (simulador) e a parte 2 (detector no Pi).
O Pi deve funcionar igual com medidores reais que publiquem no mesmo formato.

## Regra de ouro

**O gabarito das falhas nunca passa pelo MQTT.** Ele só existe nos arquivos `gabarito_falhas.csv` e
`dataset_rotulado.*`. O publicador (`casasim/mqtt.py`) recusa qualquer mensagem com os campos
`anomalia`, `falha_id`, `falha_tipo`, `canal_direto`, `gabarito`, `rotulo` ou `falha`, e há um teste
automático para isso (`test_gabarito_nunca_vai_para_o_mqtt`).

## Tópicos

| Tópico | Sentido | Conteúdo |
| --- | --- | --- |
| `casa/{perfil}/{comodo}/{medidor}/telemetria` | simulador → Pi | uma leitura de um canal de medição |
| `casa/{perfil}/{comodo}/{medidor}/comando` | Pi → simulador | liga ou desliga o relé do medidor |
| `casa/sistema/alertas` | Pi → painel | alerta gerado pelo detector |

- `{perfil}`: identificador da casa, por exemplo `perfil1`, `perfil2`, `perfil3` ou o nome de um cenário salvo no modo de montagem.
- `{comodo}`: nome do cômodo sem acentos e em minúsculas (`cozinha`, `suite_casal`, `area_de_servico`). Medidores de quadro e medidores que somam mais de um cômodo usam `quadro`.
- `{medidor}`: rótulo do medidor em minúsculas (`q`, `t1`, `r2`, `c`). O medidor geral é `q`, no cômodo `quadro`.
- Medidor geral de duas pinças em casa bifásica (perfil 2): publica **um canal por fase** no mesmo tópico (`canal` 1 = fase A, `canal` 2 = fase B, tensão de fase de ~127 V). O consumo da casa é a soma dos dois canais. Aparelhos de 220 V aparecem metade em cada fase.
- Para assinar tudo de uma casa: `casa/perfil1/+/+/telemetria`.
- Gerador de carga (E3/E4): casas virtuais `carga1`, `carga2`, ... com o mesmo formato de mensagem; `ts` é a hora real do envio. Para o Pi, é só mais casas: assine `casa/+/+/+/telemetria`.

## Telemetria

JSON em UTF-8, QoS 0, sem retenção.

```json
{
  "ts": "2026-01-05T19:12:30-03:00",
  "medidor_id": "t1",
  "canal": 1,
  "potencia_w": 101.3,
  "energia_wh": 1523.47,
  "tensao_v": 125.8,
  "corrente_a": 0.938,
  "estado": "ligado"
}
```

| Campo | Sempre? | Significado |
| --- | --- | --- |
| `ts` | sim | instante da leitura, ISO 8601 com fuso de Brasília (`-03:00`) |
| `medidor_id` | sim | rótulo do medidor (igual ao do tópico) |
| `canal` | sim | número do canal dentro do medidor (1 nos medidores de um canal; 1 a 3 no Shelly Pro 3EM) |
| `potencia_w` | sim | potência ativa instantânea, já com o erro, a resolução e o corte de potência mínima do medidor |
| `energia_wh` | sim | contador acumulado de energia do canal (só cresce; não zera à meia-noite) |
| `tensao_v` | se o medidor mede | tensão eficaz |
| `corrente_a` | se o medidor mede | corrente eficaz |
| `estado` | se o medidor tem relé | `ligado` ou `desligado` |

Pontos que o detector precisa tratar:

- **O intervalo entre mensagens depende do firmware** e muda de um canal para outro: 30 s (Tuya local e Tapo), 60 s (Zigbee2MQTT, ESPHome e Tasmota configurado), 10 s (Kron Konect) ou por variação de potência com uma mensagem de minuto (Shelly). Picos de 1 a 3 s quase nunca aparecem em `potencia_w`, mas entram em `energia_wh`.
- **Cada medidor tem um erro de ganho fixo** (até cerca de 3% nos modelos sem calibração) e um pequeno ruído por leitura.
- **Falta de energia:** os medidores somem da rede; nenhuma mensagem chega durante a falta e por mais 20 s. Silêncio simultâneo de todos os canais é evento da rede, não anomalia de aparelho.
- Aparelhos sem medidor próprio aparecem só no medidor geral, somados a uma carga de base.

## Comando

Publicado pelo Pi em `casa/{perfil}/{comodo}/{medidor}/comando`:

```json
{"acao": "desligar", "canal": 1, "motivo": "ferro ligado há 3 h"}
```

- `acao`: `desligar` ou `ligar` (obrigatório).
- `canal`: opcional; padrão 1.
- `motivo`: opcional, texto livre.

Só medidores com relé obedecem (tomadas e módulos). O medidor geral e as pinças não cortam carga.
Depois do comando, o canal passa a enviar `"estado": "desligado"` e potência zero.

## Alertas

Publicado pelo Pi em `casa/sistema/alertas`; o painel do simulador mostra os dez últimos.
Formato sugerido (a parte 2 pode acrescentar campos):

```json
{
  "ts": "2026-01-05T19:15:00-03:00",
  "casa": "perfil1",
  "medidor_id": "t4",
  "canal": 1,
  "tipo": "duracao_excessiva",
  "score": 0.93,
  "mensagem": "Ferro de passar ligado há 3 h 10 min, fora do padrão das últimas 4 semanas.",
  "acao": "desligar"
}
```

## Arquivos que ficam fora do MQTT

| Arquivo | Conteúdo |
| --- | --- |
| `telemetria.csv` / `.parquet` | as mesmas mensagens do MQTT, sem rótulo |
| `dataset_rotulado.csv` / `.parquet` | telemetria com `anomalia`, `falha_id`, `falha_tipo` e `canal_direto` |
| `gabarito_falhas.csv` | uma linha por falha e por dia: janela pedida, janela em que o sinal mudou de fato, se foi efetiva e se deve virar alerta de aparelho |
| `verdade_1min.csv` / `.parquet` | potência real média por minuto de cada aparelho, do total e a temperatura externa |
| `resumo.json` | kWh por aparelho, por tipo e por dia; semente e parâmetros da rodada |
| `TCC/datasets/v1/.../{treino,calibracao,teste}.parquet` | datasets congelados: telemetria + gabarito + coluna `particao` (ver `datasets/v1/LEIAME.md`) |
| `registros/aovivo_*.jsonl` | sessão ao vivo: falhas injetadas, comandos e alertas recebidos, gabarito de cada dia (E5) |
| `registros/carga_*.csv` | gerador de carga: casas, canais e mensagens por segundo (E3/E4) |
