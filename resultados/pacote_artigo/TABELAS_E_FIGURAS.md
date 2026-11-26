# Tabelas e figuras geradas (automático)

## E1 — baselines no teste: média ± desvio-padrão das 15 casas (3 perfis × 5 sementes)

Arquivo: `tabelas/T1_baselines_teste.csv` — fonte: resultados/baselines_v1/tabela_por_semente.csv (DIARIO do detector, seção H)

| modelo              | AUC-PR evento   | F1            | precisão      | revocação     |   FP/dia |   atraso mediano (min) |   µs por janela (x86) |
|:--------------------|:----------------|:--------------|:--------------|:--------------|---------:|-----------------------:|----------------------:|
| Regra (limiar fixo) | 0.250 ± 0.102   | 0.277 ± 0.154 | 0.639 ± 0.345 | 0.218 ± 0.122 |     0.2  |                   27.5 |                  0.02 |
| Isolation Forest    | 0.089 ± 0.070   | 0.106 ± 0.109 | 0.194 ± 0.218 | 0.085 ± 0.080 |     0.41 |                   62.9 |                  4.5  |
| OCSVM               | 0.426 ± 0.194   | 0.436 ± 0.159 | 0.515 ± 0.247 | 0.449 ± 0.176 |     0.47 |                   23.5 |                  9.54 |
| Autoencoder         | 0.372 ± 0.162   | 0.440 ± 0.131 | 0.508 ± 0.213 | 0.438 ± 0.116 |     0.44 |                   27.3 |                  0.36 |
| LSTM-AE             | 0.351 ± 0.142   | 0.345 ± 0.143 | 0.458 ± 0.237 | 0.352 ± 0.159 |     0.51 |                   18.7 |                 58.68 |

## E1 — AUC-PR por evento no teste, por perfil (média das 5 sementes)

Arquivo: `tabelas/T1b_baselines_auc_por_perfil.csv` — fonte: resultados/baselines_v1/tabela_perfil_modelo.csv

| modelo              |   perfil1 |   perfil2 |   perfil3 |
|:--------------------|----------:|----------:|----------:|
| Regra (limiar fixo) |     0.198 |     0.306 |     0.248 |
| Isolation Forest    |     0.096 |     0.123 |     0.049 |
| OCSVM               |     0.586 |     0.392 |     0.3   |
| Autoencoder         |     0.436 |     0.417 |     0.264 |
| LSTM-AE             |     0.458 |     0.267 |     0.328 |

## E1 — falhas detectadas / falhas no teste, por tipo e modelo (15 casas somadas)

Arquivo: `tabelas/T1c_baselines_por_tipo.csv` — fonte: resultados/baselines_v1/tabela_por_tipo.csv

| tipo de falha         | Regra (limiar fixo)   | Isolation Forest   | OCSVM   | Autoencoder   | LSTM-AE   |
|:----------------------|:----------------------|:-------------------|:--------|:--------------|:----------|
| Consumo não explicado | 1/30                  | 0/30               | 7/30    | 11/30         | 3/30      |
| Duração excessiva     | 7/45                  | 5/45               | 28/45   | 34/45         | 29/45     |
| Fora de horário       | 2/45                  | 8/45               | 28/45   | 14/45         | 23/45     |
| Magnitude             | 25/31                 | 3/31               | 5/31    | 5/31          | 4/31      |
| Pico                  | 8/30                  | 0/30               | 9/30    | 13/30         | 3/30      |
| Queda                 | 0/17                  | 1/17               | 12/17   | 10/17         | 8/17      |

## E1 — AUC-PR por evento dos cinco baselines no teste

Arquivo: `figuras/F1_baselines_auc.png` — fonte: resultados/baselines_v1/tabela_por_semente.csv

## E1 — cascata OCSVM + regra → LSTM-AE no teste, por orçamento (15 casas)

Arquivo: `tabelas/T2_cascata_orcamentos.csv` — fonte: resultados/cascata_v1/tabela_cascata.csv (DIARIO, seção I)

|   orçamento (% escalado) |   escalados no teste (%) | F1            |   AUC-PR evento |   FP/dia |   revocação do estágio 1 |   custo relativo ao LSTM-AE sempre |
|-------------------------:|-------------------------:|:--------------|----------------:|---------:|-------------------------:|-----------------------------------:|
|                        0 |                      0   | 0.496 ± 0.176 |           0.294 |     0.46 |                    0     |                              0.028 |
|                        1 |                      1.2 | 0.494 ± 0.165 |           0.351 |     0.4  |                    0.78  |                              0.039 |
|                        2 |                      2.2 | 0.484 ± 0.161 |           0.368 |     0.44 |                    0.855 |                              0.05  |
|                        5 |                      5.6 | 0.484 ± 0.163 |           0.372 |     0.45 |                    0.955 |                              0.084 |
|                       10 |                     10.9 | 0.487 ± 0.165 |           0.372 |     0.42 |                    0.984 |                              0.136 |
|                       20 |                     20.5 | 0.486 ± 0.165 |           0.372 |     0.43 |                    1     |                              0.233 |
|                       50 |                     48.8 | 0.483 ± 0.165 |           0.371 |     0.42 |                    1     |                              0.516 |
|                      100 |                    100   | 0.484 ± 0.165 |           0.372 |     0.42 |                    1     |                              1.028 |

## E1 — F1 e custo da cascata em função do orçamento de escalada

Arquivo: `figuras/F2_cascata_orcamento.png` — fonte: resultados/cascata_v1/tabela_cascata.csv

## Análise de sensibilidade da arquitetura (orçamento 5 %): no teste (exploratório) e nos 28 dias novos

Arquivo: `tabelas/T3_arquiteturas.csv` — fonte: resultados/cascata_exploratoria e resultados/cascata_campanha (DIARIO K6, K7; testes pareados em K7)

| arquitetura                       | dados            | F1            |   revocação |   precisão |   FP/dia |
|:----------------------------------|:-----------------|:--------------|------------:|-----------:|---------:|
| OCSVM + regra → LSTM-AE (oficial) | teste (já usado) | 0.484 ± 0.163 |       0.532 |      0.497 |     0.45 |
| OCSVM + regra → LSTM-AE (oficial) | 28 dias novos    | 0.408 ± 0.139 |       0.377 |      0.532 |     0.6  |
| OCSVM + regra → AE                | teste (já usado) | 0.540 ± 0.193 |       0.606 |      0.541 |     0.53 |
| OCSVM + regra → AE                | 28 dias novos    | 0.450 ± 0.137 |       0.456 |      0.549 |     0.87 |
| OCSVM → LSTM-AE (sem regra)       | teste (já usado) | 0.433 ± 0.152 |       0.394 |      0.538 |     0.36 |
| OCSVM → LSTM-AE (sem regra)       | 28 dias novos    | 0.379 ± 0.152 |       0.338 |      0.574 |     0.66 |
| IF + regra → LSTM-AE              | teste (já usado) | 0.448 ± 0.164 |       0.431 |      0.561 |     0.3  |
| IF + regra → LSTM-AE              | 28 dias novos    | 0.322 ± 0.138 |       0.273 |      0.552 |     0.42 |
| IF → LSTM-AE (plano original)     | teste (já usado) | 0.329 ± 0.146 |       0.268 |      0.547 |     0.24 |
| IF → LSTM-AE (plano original)     | 28 dias novos    | 0.280 ± 0.143 |       0.224 |      0.534 |     0.48 |

## Campanha com 28 dias novos por casa (15 casas, 418 dias, 423 falhas): robustez

Arquivo: `tabelas/T4_campanha_robustez.csv` — fonte: resultados/campanha_v1/tabela_campanha.csv (DIARIO K5)

| cenário                           |   revocação |   precisão |    F1 |   FP/dia | faltas reconhecidas   |
|:----------------------------------|------------:|-----------:|------:|---------:|:----------------------|
| sem perturbação (orçamento 5 %)   |       0.376 |      0.39  | 0.383 |     0.6  | 99/99                 |
| sem perturbação (só estágio 1)    |       0.426 |      0.416 | 0.421 |     0.61 | 99/99                 |
| sem perturbação (LSTM-AE sempre)  |       0.369 |      0.388 | 0.378 |     0.59 | 99/99                 |
| 5 % das mensagens fora de ordem   |       0.376 |      0.389 | 0.382 |     0.6  | 99/99                 |
| 5 % duplicadas                    |       0.376 |      0.39  | 0.383 |     0.6  | 99/99                 |
| 1 medidor mudo 6 h por semana     |       0.378 |      0.376 | 0.377 |     0.63 | 99/99                 |
| deriva +5 % no medidor geral      |       0.421 |      0.395 | 0.407 |     0.65 | 99/99                 |
| 1 % das mensagens perdidas        |       0.383 |      0.344 | 0.362 |     0.74 | 99/99                 |
| 5 % perdidas                      |       0.411 |      0.24  | 0.303 |     1.32 | 99/99                 |
| 20 % perdidas                     |       0.513 |      0.127 | 0.204 |     3.57 | 99/99                 |
| deriva +5 % em todos os medidores |       0.449 |      0.061 | 0.107 |     7    | 99/99                 |

## Campanha — alertas falsos por dia em cada perturbação (azul: sem perturbação)

Arquivo: `figuras/F3_campanha_robustez.png` — fonte: resultados/campanha_v1/tabela_campanha.csv

## E2 — latência de UMA inferência no Raspberry Pi 5 (lote 1, 1 thread, 2.000 repetições, 2,4 GHz, sem throttling)

Arquivo: `tabelas/T5_e2_latencia_inferencia.csv` — fonte: resultados/e2_20261123_0912/custo_*.json (DIARIO K9)

| casa                   | modelo              |   mediana (µs) |   p99 (µs) |   .onnx por canal (kB) |
|:-----------------------|:--------------------|---------------:|-----------:|-----------------------:|
| perfil1_s1 (6 canais)  | Regra (limiar fixo) |           11.9 |       12.8 |                    0.1 |
| perfil1_s1 (6 canais)  | Isolation Forest    |         2179.4 |     2373.4 |                  918.2 |
| perfil1_s1 (6 canais)  | OCSVM               |           19.7 |       23.6 |                    9.8 |
| perfil1_s1 (6 canais)  | Autoencoder         |           19.7 |       23.1 |                    8   |
| perfil1_s1 (6 canais)  | LSTM-AE             |          199.9 |      213.7 |                   61.5 |
| perfil3_s1 (32 canais) | Regra (limiar fixo) |           10.9 |       12.3 |                    0.1 |
| perfil3_s1 (32 canais) | Isolation Forest    |         2349.6 |     2549.8 |                  845.7 |
| perfil3_s1 (32 canais) | OCSVM               |           19.5 |       23.9 |                   10.7 |
| perfil3_s1 (32 canais) | Autoencoder         |           20.6 |       24.3 |                    7.9 |
| perfil3_s1 (32 canais) | LSTM-AE             |          196.7 |      211.6 |                   61.4 |

## E2 — custo do sistema ao vivo no Pi 5 por minuto de casa (36.000 min de teste), antes e depois da otimização

Arquivo: `tabelas/T6_e2_sistema_por_minuto.csv` — fonte: resultados/e2_*/reproduzir_*.txt (DIARIO K9)

| versão                       | casa                   |   orçamento (%) |   ms por minuto de casa |   atributos |   estágio 1 |   estágio 2 |   escalados (%) |   alertas |
|:-----------------------------|:-----------------------|----------------:|------------------------:|------------:|------------:|------------:|----------------:|----------:|
| atributos antigos            | perfil1_s1 (6 canais)  |               0 |                   1.319 |       1.124 |       0.16  |       0     |             0   |        24 |
| atributos antigos            | perfil1_s1 (6 canais)  |               5 |                   1.406 |       1.125 |       0.164 |       0.08  |             5   |        25 |
| atributos antigos            | perfil1_s1 (6 canais)  |             100 |                   3.154 |       1.191 |       0.234 |       1.669 |            99.8 |        24 |
| atributos antigos            | perfil3_s1 (32 canais) |               0 |                   6.876 |       5.756 |       0.957 |       0     |             0   |        16 |
| atributos antigos            | perfil3_s1 (32 canais) |               5 |                   7.658 |       5.843 |       1.073 |       0.55  |             5.6 |        16 |
| atributos antigos            | perfil3_s1 (32 canais) |             100 |                  17.746 |       6.137 |       1.437 |       9.845 |            99.8 |        16 |
| atributos otimizados (final) | perfil1_s1 (6 canais)  |               0 |                   0.475 |       0.289 |       0.155 |       0     |             0   |        24 |
| atributos otimizados (final) | perfil1_s1 (6 canais)  |               5 |                   0.563 |       0.291 |       0.159 |       0.078 |             5   |        25 |
| atributos otimizados (final) | perfil1_s1 (6 canais)  |             100 |                   2.231 |       0.316 |       0.222 |       1.633 |            99.8 |        24 |
| atributos otimizados (final) | perfil3_s1 (32 canais) |               0 |                   2.461 |       1.493 |       0.82  |       0     |             0   |        16 |
| atributos otimizados (final) | perfil3_s1 (32 canais) |               5 |                   3.217 |       1.563 |       0.955 |       0.522 |             5.6 |        16 |
| atributos otimizados (final) | perfil3_s1 (32 canais) |             100 |                  13.163 |       1.75  |       1.377 |       9.716 |            99.8 |        16 |

## E2 — latência de uma inferência por modelo no Pi 5 (perfil1_s1)

Arquivo: `figuras/F4_e2_latencia.png` — fonte: resultados/e2_20261123_0912/custo_perfil1_semente_1.json

## E3 (1ª rodada, rampa 50→3.000 casas): pior atraso de alerta por nº de casas. *Nesta rodada o gerador desalinhava os canais e o orçamento de 5 % escalou 64 % (DIARIO K11)

Arquivo: `figuras/F5_e3_atraso_por_casas.png` — fonte: resultados/e3_20261123_1012/analise/e3_degraus.csv

## E3 — 1ª rodada (rampa, uma mensagem por canal a cada 10 s), por degrau

Arquivo: `tabelas/T7_e3_rampa.csv` — fonte: resultados/e3_20261123_1012/analise/e3_degraus.csv (DIARIO K11)

| rodada   |   casas |   canais |   msg_s_enviadas |   msg_s_processadas |   fracao_processada |   atraso_pior_s |   escalados_pct |   ms_por_minuto_casa |   cpu_detector_media |   mem_mb_max |
|:---------|--------:|---------:|-----------------:|--------------------:|--------------------:|----------------:|----------------:|---------------------:|---------------------:|-------------:|
| E3_b1    |      50 |     1600 |            155   |               155   |               1     |           0.13  |          100    |               12.041 |                  2.2 |        178   |
| E3_b1    |     100 |     3200 |            310   |               310.1 |               1     |           0.641 |          100    |               12.068 |                  4.8 |        204.8 |
| E3_b1    |     200 |     6400 |            620   |               610.5 |               0.985 |           1.579 |          100    |               12.087 |                  8.1 |        259.8 |
| E3_b1    |     400 |    12800 |           1240   |              1218.8 |               0.983 |           3.914 |          100    |               12.11  |                 13.8 |        367.5 |
| E3_b1    |     600 |    19200 |           1860   |              1819.5 |               0.978 |           6.48  |          100    |               12.189 |                 19.4 |        481.1 |
| E3_b1    |     800 |    25600 |           2480   |              2418.7 |               0.975 |           9.058 |          100    |               12.263 |                 25.1 |        602.2 |
| E3_b1    |    1000 |    32000 |           3100   |              3009.2 |               0.971 |          11.7   |          100    |               12.354 |                 30.6 |        727.7 |
| E3_b1    |    1300 |    41600 |           4030   |              3717.4 |               0.922 |          15.462 |          100    |               12.366 |                 39   |        907   |
| E3_b1    |    1600 |    51200 |           4960   |              4191   |               0.845 |          19.431 |          100    |               12.37  |                 44.4 |       1088.2 |
| E3_b1    |    2000 |    64000 |           6200   |              4650   |               0.75  |          25.343 |          100    |               12.807 |                 52.8 |       1323.8 |
| E3_b1    |    2500 |    80000 |           7750   |              5181.7 |               0.669 |          30.899 |          100    |               12.477 |                 61.5 |       1624   |
| E3_b1    |    3000 |    96000 |           9299.6 |              5617.3 |               0.604 |          37.459 |          100    |               12.494 |                 73.1 |       1926.3 |
| E3_b005  |      50 |     1600 |            155   |               155   |               1     |           0.105 |           63.5  |                8.414 |                  1.9 |       1685.8 |
| E3_b005  |     100 |     3200 |            310   |               310   |               1     |           0.43  |           63.88 |                8.505 |                  3.8 |       1685.8 |
| E3_b005  |     200 |     6400 |            620   |               619.9 |               1     |           1.171 |           63.34 |                8.593 |                  7.4 |       1685.8 |
| E3_b005  |     400 |    12800 |           1240   |              1239.9 |               1     |           2.728 |           63.14 |                8.503 |                 14.2 |       1684.8 |
| E3_b005  |     600 |    19200 |           1860   |              1859.6 |               1     |           4.413 |           63.53 |                8.625 |                 20.6 |       1684.8 |
| E3_b005  |     800 |    25600 |           2480   |              2479.1 |               1     |           6.227 |           63.54 |                8.663 |                 26.5 |       1684.8 |
| E3_b005  |    1000 |    32000 |           3100   |              3097.8 |               0.999 |           8.299 |           63.83 |                8.734 |                 33.5 |       1684.8 |
| E3_b005  |    1300 |    41600 |           4030   |              4030.7 |               1     |          11.535 |           63.75 |                8.784 |                 42.9 |       1684.8 |
| E3_b005  |    1600 |    51200 |           4960   |              4433.3 |               0.894 |          13.868 |           64.07 |                8.876 |                 50.1 |       1683.8 |
| E3_b005  |    2000 |    64000 |           6200   |              4229.6 |               0.682 |          18.561 |           64.27 |                9.2   |                 57.9 |       1683.8 |
| E3_b005  |    2500 |    80000 |           7750   |              4640.8 |               0.599 |          22.214 |           64.38 |                8.995 |                 66.2 |       1759.6 |
| E3_b005  |    3000 |    96000 |           9299.6 |              5298.9 |               0.57  |          27.207 |           64.44 |                8.999 |                 69.7 |       1950.6 |
| E3_b0    |      50 |     1600 |            155   |               155   |               1     |           0.043 |            0    |                1.976 |                  1.2 |       1815.2 |
| E3_b0    |     100 |     3200 |            310   |               310   |               1     |           0.142 |            0    |                2.057 |                  2.4 |       1815.2 |
| E3_b0    |     200 |     6400 |            620   |               620   |               1     |           0.081 |            0    |                2.037 |                  4.5 |       1815.2 |
| E3_b0    |     400 |    12800 |           1240   |              1239.8 |               1     |           0.332 |            0    |                2.068 |                  8.3 |       1815.2 |
| E3_b0    |     600 |    19200 |           1860   |              1859.7 |               1     |           0.668 |            0    |                2.121 |                 11.9 |       1815.2 |
| E3_b0    |     800 |    25600 |           2480   |              2480.8 |               1     |           1.103 |            0    |                2.146 |                 15   |       1815.2 |
| E3_b0    |    1000 |    32000 |           3100   |              3100.6 |               1     |           1.607 |            0    |                2.215 |                 19   |       1815.2 |
| E3_b0    |    1300 |    41600 |           4030   |              4030   |               1     |           2.389 |            0    |                2.236 |                 23.5 |       1815   |
| E3_b0    |    1600 |    51200 |           4960   |              4960.9 |               1     |           3.987 |            0    |                2.311 |                 29.5 |       1815   |
| E3_b0    |    2000 |    64000 |           6200   |              6201.3 |               1     |           4.303 |            0    |                2.328 |                 35.6 |       1815   |
| E3_b0    |    2500 |    80000 |           7750   |              7746.8 |               1     |           5.668 |            0    |                2.36  |                 45.5 |       1814   |
| E3_b0    |    3000 |    96000 |           9299.6 |              8846.8 |               0.951 |           7.082 |            0    |                2.396 |                 51   |       1975.1 |
| E4_ctrl  |      50 |     1600 |            155   |               155   |               1     |           0.225 |          100    |               12.128 |                  1.6 |       1849.1 |
| E4_ctrl  |     100 |     3200 |            310   |               310   |               1     |           0.619 |          100    |               12.163 |                  3.2 |       1849.1 |
| E4_ctrl  |     200 |     6400 |            620   |               620   |               1     |           1.776 |          100    |               12.17  |                  6.1 |       1812.1 |
| E4_ctrl  |     400 |    12800 |           1240   |              1239.8 |               1     |           3.817 |          100    |               12.191 |                 12.1 |       1812.1 |
| E4_ctrl  |     600 |    19200 |           1860   |              1860.7 |               1     |           6.382 |          100    |               12.268 |                 17.5 |       1811.1 |
| E4_ctrl  |     800 |    25600 |           2480   |              2697.9 |               1.088 |           8.831 |           90.88 |               11.413 |                 23.8 |       1811.1 |
| E4_ctrl  |    1000 |    32000 |           3100   |              3386.4 |               1.092 |          10.992 |           88.6  |               11.262 |                 30.7 |       1811.1 |
| E4_ctrl  |    1300 |    41600 |           4030   |              4331.2 |               1.075 |          12.892 |           80.27 |               10.445 |                 38.1 |       1811.3 |
| E4_ctrl  |    1600 |    51200 |           4960   |              4866.1 |               0.981 |          10.788 |           22.59 |                4.614 |                 37.4 |       1811.3 |
| E4_ctrl  |    2000 |    64000 |           6200   |              5872.8 |               0.947 |          12.2   |           19.72 |                4.398 |                 42.5 |       1811.3 |
| E4_ctrl  |    2500 |    80000 |           7750   |              7137.6 |               0.921 |          14.038 |           17.79 |                4.196 |                 51.2 |       1811.3 |
| E4_ctrl  |    3000 |    96000 |           9299.6 |              8162   |               0.878 |          16.235 |           17.14 |                4.154 |                 55.9 |       1975   |

## E3/E4/E6 — 4.000 casas perfil3 fiéis (128 mil canais, ~3.080 msg/s): sustenta? (últimos 5 min de cada rodada)

Arquivo: `tabelas/T8_e3_e4_e6_4000_casas.csv` — fonte: resultados/e3_20261123_1331, _1552, _1632 /analise/e3_degraus.csv (DIARIO K13, K14, K16)

| configuração                       | trecho            |   processado (%) |   fila (fim − início) |   pior atraso (s) |   escalados (%) |   ms por min-casa |   CPU detector (%) | orçamentos   |   memória (MB) |
|:-----------------------------------|:------------------|-----------------:|----------------------:|------------------:|----------------:|------------------:|-------------------:|:-------------|---------------:|
| LSTM-AE sempre (100 %), 2,4 GHz    | degrau            |             97.8 |                 31212 |              51.5 |           100   |             12.87 |               98   | 1.0          |         2657.6 |
| cascata 5 %, 2,4 GHz               | regime_5min_final |            103.3 |                -47735 |              27.1 |            38.7 |              7.85 |               72.3 | 0.05         |         3305.2 |
| controlador (limite 30 s), 2,4 GHz | regime_5min_final |            100.2 |                 -6692 |              28.5 |            35.2 |              7.71 |               74.6 | 0.1          |         3298.2 |
| LSTM-AE sempre (100 %), 1,5 GHz    | degrau            |             74   |                260680 |             131   |           100   |             17.77 |              109.7 | 1.0          |         2989.6 |
| controlador (limite 30 s), 1,5 GHz | regime_5min_final |            100.6 |                    -2 |              30.5 |            11.8 |              7.37 |               82.4 | 0.0,0.01     |         3310.8 |

## E4 e E6 — trajetória do controlador de carga (orçamento e pior atraso por minuto)

Arquivo: `figuras/F6_e4_e6_controlador.png` — fonte: resultados/e3_20261123_1552 e e3_20261123_1632 /analise/e4_trajetoria.csv (DIARIO K14, K16)

## E5 — sessão ao vivo painel → MQTT → Pi 5 → painel (perfil1_s1, orçamento 5 %)

Arquivo: `tabelas/T9_e5_ponta_a_ponta.csv` — fonte: resultados/e5_bateria_noturna (DIARIO K8)

| medida                                                  | valor   |
|:--------------------------------------------------------|:--------|
| falhas injetadas pelo painel                            | 158     |
| dias simulados (120×)                                   | 29.73   |
| revocação (todas)                                       | 0.335   |
| revocação — aparelhos com medidor próprio               | 47/92   |
| revocação — sem medidor próprio / consumo não explicado | 6/66    |
| precisão                                                | 0.981   |
| alertas falsos por dia                                  | 0.034   |
| atraso mediano de detecção (min simulados)              | 35.3    |
| latência do sistema, mediana (s reais)                  | 0.11    |
| faltas de energia / alertas falsos durante elas         | 14 / 0  |

## Realismo — forma média do dia da casa real (Boa Energia) e dos 3 perfis

Arquivo: `figuras/F7_realismo_forma_do_dia.png` — fonte: tabelas/realismo_forma_do_dia.csv (scripts/realismo_boa_energia.py)

## Realismo — casa real (Boa Energia) × perfis simulados: consumo, variabilidade e forma

Arquivo: `tabelas/realismo_boa_energia.csv` — fonte: dados_reais/boa_energia/BoaEnergia.csv + datasets/v1 (treino)

| casa               |   dias |   kwh_dia_media |   kwh_mes_30d |   cv_diario |   pico_sobre_media_hora |   hora_do_pico |   fracao_noite_18_23h |   correlacao_forma_com_real |
|:-------------------|-------:|----------------:|--------------:|------------:|------------------------:|---------------:|----------------------:|----------------------------:|
| Boa Energia (real) |     29 |          10.433 |       312.995 |       0.223 |                   1.668 |             18 |                 0.342 |                     nan     |
| perfil1            |    345 |           5.031 |       150.938 |       0.179 |                   3.702 |             19 |                 0.509 |                       0.35  |
| perfil2            |    345 |           9.703 |       291.089 |       0.126 |                   3.287 |             19 |                 0.479 |                       0.336 |
| perfil3            |    345 |          36.638 |      1099.14  |       0.236 |                   3.412 |             20 |                 0.451 |                       0.485 |
