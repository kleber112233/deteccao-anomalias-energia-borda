# casasim — simulador da casa (parte 1 do TCC)

Simulador comportamental do consumo de energia de uma casa brasileira (Marília-SP). Ele gera o que os
medidores de consumo enviariam a um Raspberry Pi 5 (4 GB), publica por MQTT e grava datasets rotulados para a
parte 2 (detecção de anomalias no Pi).

    moradores + clima (INMET) + rede elétrica
            │
            ▼
    usos dos aparelhos ──► potência real de cada aparelho (1 s) ──► falhas injetadas (gabarito em arquivo)
                                                                        │
                                                 medidor escolhido (erro, intervalo, firmware)
                                                                        │
                                          MQTT ─► Raspberry Pi      painel web      dataset rotulado

## Instalação

Python 3.11 (funciona a partir do 3.10). No Windows, dentro da pasta `simulador`:

    py -3.11 -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt

## Uso rápido

    python -m casasim web                         # painel em http://127.0.0.1:8000
    python -m casasim simular --cenario perfil1 --dias 30 --falhas-por-semana 3 --saida saida/p1_teste
    python -m casasim simular --cenario perfil2 --dias 60 --saida saida/p2_normal --formato parquet
    python -m casasim tempo-real --cenario perfil1 --mqtt 192.168.0.50 --velocidade 1
    python -m casasim validar perfil3             # confere a montagem (tensão, corrente, custo)
    python validacao/validar.py                   # gráficos e metas (EPE, curva diária, uso final)
    python ferramentas/gerar_datasets.py          # refaz os datasets congelados v1 (TCC/datasets/v1, ~860 MB, ~12 min)
    python -m casasim carga ../datasets/v1/perfil2/semente_1 --mqtt 192.168.0.50 --intervalo 10 --rampa "0:1,2:10,4:50" --duracao 360
    python -m pytest -q                           # 32 testes

Para o MQTT é preciso um broker (Mosquitto) no Pi ou no notebook. Sem broker o painel funciona igual;
só não há publicação.

## Painel web

- **Painel:** indicadores (potência no medidor geral, energia e custo do dia com tarifa e bandeira,
  projeção do mês), curva do dia, potência por cômodo, planta 2D com os aparelhos acendendo, painel
  para injetar cada tipo de falha e tabela com o que cada medidor está enviando. Medidores com relé
  têm botão de desligar/religar (o mesmo efeito do tópico `.../comando`).
- **Montagem da casa:** parte de um dos três perfis; escolha, por cômodo, o aparelho (modelo do
  catálogo) e o medidor (do acervo); edite moradores e rotina. A conferência mostra erros (tomada de
  10 A com carga maior, aparelho 220 V em casa 127 V), avisos e o custo total. "Salvar cenário" grava
  um novo arquivo em `cenarios/`, que passa a aparecer na lista.

## Organização

| Pasta / arquivo | Conteúdo |
| --- | --- |
| `catalogos/` | catálogo bruto (229 aparelhos, 101 medidores), `catalogo_simulador.json` (camada normalizada) e `pbe_conferencia.json` (o que foi lido no PBE/Inmetro) |
| `ferramentas/normalizar_catalogo.py` | gera a camada normalizada; todas as suposições estão escritas nele |
| `cenarios/` | as três casas (`casa_perfil1/2/3.json`) e as que forem salvas no modo de montagem |
| `dados/` | clima de Marília (INMET A763), personas e hábitos, tarifas, metas de validação |
| `casasim/dados.py` | carrega catálogo e cenários; valida a montagem |
| `casasim/clima.py`, `rede.py` | temperatura por minuto; tensão e faltas de energia |
| `casasim/comportamento.py` | moradores → eventos de uso |
| `casasim/aparelhos.py` | geradores de consumo por classe de aparelho (resolução de 1 s) |
| `casasim/sensores.py` | modelo de medidor/firmware (intervalo, erro, resolução, periódico × por evento) |
| `casasim/falhas.py` | sete tipos de falha e o gabarito |
| `casasim/motor.py` | junta tudo, um dia por vez; modo acelerado e exportação |
| `casasim/tempo_real.py`, `mqtt.py` | modo tempo real, publicação e comandos; `RegistroAoVivo` grava em `registros/` cada falha injetada, comando e alerta recebido (gabarito do E5) |
| `casasim/carga.py` | gerador de carga (E3/E4): reenvia um dataset congelado em N casas virtuais, com rampa e registro por segundo |
| `casasim/datasets.py` | leitura dos datasets congelados, sem as colunas de gabarito por padrão |
| `ferramentas/gerar_datasets.py` | gera e congela os datasets (treino/calibração/teste, manifesto com SHA-256) |
| `casasim/web/` | FastAPI + WebSocket e a página do painel |
| `validacao/validar.py` | validação contra as metas; figuras em `validacao/resultados/` |
| `docs/CONTRATO_MQTT.md` | contrato entre simulador e Pi |
| `DIARIO.md` | diário de bordo: decisões, motivos, fontes e números |

## Reprodutibilidade

A mesma semente gera exatamente a mesma casa, o mesmo clima e as mesmas mensagens. Cada aparelho e
cada medidor tem seu próprio gerador aleatório, então injetar uma falha num aparelho não muda o
comportamento dos outros: dá para comparar a mesma semana com e sem falha.

## Saídas do modo acelerado

`telemetria`, `dataset_rotulado`, `gabarito_falhas.csv`, `verdade_1min` e `resumo.json` (descritos no fim
de `docs/CONTRATO_MQTT.md`). Para treinar só com comportamento normal, rode sem `--falhas-por-semana`.

## Datasets congelados (v1)

Ficam em `TCC/datasets/v1/` (ver o `LEIAME.md` de lá): 3 perfis × 5 sementes × 120 dias, divisão temporal
60/20/20 (treino sem falhas; calibração e teste com 17 falhas cada, tipos balanceados).

## Experimentos ao vivo

- **E3/E4 (capacidade):** `python -m casasim carga ...` publica em `casa/carga1/...`, `casa/carga2/...`. O CSV em
  `registros/carga_*.csv` tem, por segundo, casas e canais ativos, mensagens enviadas e a taxa-alvo.
  Sem broker, chega a ~3.000 mensagens/s num notebook; rode o gerador fora do Pi.
- **E5 (detecção ao vivo):** o painel e o `tempo-real` gravam `registros/aovivo_<cenário>_<data>.jsonl` com
  `relogio_real` e `relogio_sim` de cada falha injetada, comando e alerta recebido (com as falhas ativas no momento)
  e o gabarito de cada dia concluído. A latência de detecção sai da diferença entre `falha_injetada` e `alerta_recebido`.

## Limites conhecidos

- As rotinas são suposições de cenário calibradas para as metas; a PPH 2019 ainda precisa ser
  consultada para confirmar posse e tempo de uso (ver `DIARIO.md`, "Pendências").
- Um medidor de um canal ligado a "Cômodo: tipo" mede todos os aparelhos daquele tipo no cômodo.
- A falha injetada pelo painel vale até o fim do dia simulado em que começou.
- Feriados não são tratados (contam como dia útil ou fim de semana, conforme o calendário).
