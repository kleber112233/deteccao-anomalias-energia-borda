# Detecção de anomalias no consumo elétrico residencial na borda

Acervo do Trabalho de Conclusão de Curso **"Detecção de anomalias no consumo elétrico residencial na borda:
qualidade, custo e capacidade em um Raspberry Pi 5"**, do Bacharelado em Ciência da Computação da Universidade
de Marília (UNIMAR), 2026.

- **Autor:** Kleber Moraes da Silva Junior
- **Orientador:** Prof. Cesar Giacomini Penteado

O trabalho compara quatro modelos treinados com consumo normal (Isolation Forest, One-Class SVM, autoencoder
denso e autoencoder LSTM) e uma regra de potência na detecção de falhas em aparelhos de casas brasileiras
simuladas. Em seguida, avalia uma cascata (regra + OCSVM, com o LSTM-AE acionado só quando há suspeita) e mede,
em um Raspberry Pi 5 físico, o custo de inferência, a capacidade de atender várias casas por MQTT e um
controlador que ajusta o uso do modelo mais caro ao atraso observado.

## Como o sistema funciona

```
 computador                                    Raspberry Pi 5 (4 GB)
 ┌──────────────────────────┐   MQTT (Wi-Fi)   ┌──────────────────────────────────────────┐
 │ simulador da casa        │ ───────────────► │ Mosquitto                                │
 │ (casasim): aparelhos,    │                  │   │                                      │
 │ moradores, clima e       │                  │   ▼                                      │
 │ medidores                │                  │ detector: atributos por canal e minuto   │
 │                          │                  │   ├─ estágio 1: regra + OCSVM            │
 │ painel web               │ ◄─────────────── │   └─ estágio 2: LSTM-AE (se suspeito)    │
 │ (alertas e falhas)       │   alertas (MQTT) │ controlador de carga (orçamento x atraso)│
 └──────────────────────────┘                  └──────────────────────────────────────────┘
```

O Raspberry Pi não mede energia: as leituras vêm dos medidores simulados, no formato de tomadas e medidores
comerciais. O que é medido na placa é o custo da detecção (tempo, memória, CPU, temperatura e capacidade).

## Organização

| Pasta | Conteúdo |
|---|---|
| `simulador/` | Simulador `casasim`: catálogo de 229 aparelhos (PBE/Inmetro e fabricantes), 80 medidores, três perfis de casa, painel web, publicação MQTT, gerador de carga e validação contra EPE, ANEEL/CPFL e Boa Energia. 32 testes. |
| `detector/` | Atributos causais, os cinco detectores, exportação para ONNX, cascata, avaliação por evento, serviço MQTT do Pi e análises dos ensaios. 29 testes. O `DIARIO.md` registra cada decisão e cada número. |
| `pi/` | Preparo do Raspberry Pi 5, roteiros dos ensaios E2 e E3/E4/E6 e os pacotes de modelos que rodam na placa (`pi/pacotes`). |
| `datasets/v1/` | Manifesto das 15 séries congeladas (3 perfis × 5 sementes × 120 dias), com SHA-256 de cada arquivo, gabaritos das falhas e resumos. |
| `resultados/` | Resultados de todos os ensaios (E1 a E6) e o pacote com as tabelas e figuras do artigo (`resultados/pacote_artigo`). |
| `dados_reais/` | Fontes de dados reais usadas como referência, com links de download, e a curva B1 da CPFL Paulista (ANEEL) já tratada. |
| `tcc artigo/imagens/figuras_no_tcc/` | Fotos e capturas da bancada usadas no artigo (Figuras 2, 4 e 5). |

## Onde está cada resultado do artigo

| Seção do artigo | Arquivos |
|---|---|
| 4.3 Aderência do simulador (Tabela 1) | `simulador/validacao/`, `resultados/pacote_artigo/FIDELIDADE_DO_SIMULADOR.md` |
| 5.1 Detectores individuais (Tabelas 2 e 3) | `resultados/baselines_v1/` |
| 5.2 Cascata por orçamento (Figura 2) | `resultados/cascata_v1/` |
| 5.3 Novos dias e robustez (Tabela 4) | `resultados/cascata_campanha/`, `resultados/campanha_v1/`, `resultados/cascata_exploratoria/` |
| 5.4 Latência no Pi (Tabela 5) | `resultados/e2_20261123_0912/` |
| 5.5 Capacidade com 4.000 casas (Tabela 6) | `resultados/e3_20261123_1012/` (rampa), `resultados/e3_20261123_1331/` (rodada final) |
| 5.6 Controlador (Figura 3) | `resultados/e3_20261123_1552/` (E4, 2,4 GHz), `resultados/e3_20261123_1632/` (E6, 1,5 GHz) |
| 5.7 Fluxo ponta a ponta (E5) | `resultados/e5_bateria_noturna/`, `simulador/registros/` |
| 7 Sistema em funcionamento (Figuras 4 e 5) | `tcc artigo/imagens/figuras_no_tcc/` |

As tabelas e figuras consolidadas, com a origem de cada número, estão em `resultados/pacote_artigo/LEIAME.md`.

## Como reproduzir

Versões usadas: Python 3.11, scikit-learn 1.9.1, onnxruntime 1.32.0, numpy 2.4.6, pandas 3.1.1 (iguais no
computador e no Pi) e PyTorch 2.15 (só no computador, para treinar as redes).

1. **Simulador** (Windows, dentro de `simulador`):

   ```
   py -3.11 -m venv .venv
   .\.venv\Scripts\python -m pip install -r requirements.txt
   .\.venv\Scripts\python -m pytest -q
   .\.venv\Scripts\python ferramentas\gerar_datasets.py
   ```

   O último comando refaz as 15 séries em `datasets/v1` (cerca de 860 MB). Tudo é determinístico pela
   semente, e os arquivos gerados podem ser conferidos pelos SHA-256 de `datasets/v1/manifesto.json`.

2. **Detector** (Windows, dentro de `detector`):

   ```
   py -3.11 -m venv .venv
   .\.venv\Scripts\python -m pip install -r requirements.txt
   .\.venv\Scripts\python -m pytest -q
   .\.venv\Scripts\python -m detector baselines --processos 8
   .\.venv\Scripts\python -m detector cascata --processos 8
   .\.venv\Scripts\python -m detector empacotar perfil1 1
   ```

   Os demais comandos (campanha, variantes, análise do E3 a E6) estão em `detector/README.md`.

3. **Raspberry Pi 5:** siga `pi/PREPARO_PI.md` (sistema, Mosquitto e ambiente Python) e `pi/E2_NO_PI.md`.
   Para rodar o detector ao vivo, dentro de `~/tcc-pi` no Pi:

   ```
   PYTHONPATH=$PWD/detector .venv/bin/python -m detector servico --pacote pacotes/perfil1_s1 --broker localhost
   ```

   e, no computador, abra o painel com `python -m casasim web`, informando o IP do Pi no campo do broker MQTT.

## O que não está no repositório

- **Séries em Parquet** (`datasets/v1/**/*.parquet`, 864 MB): regeradas pelo passo 1 e conferidas pelo manifesto.
- **Modelos ONNX dos detectores individuais** (247 MB, quase todos do Isolation Forest): retreinados pelo
  passo 2. Os modelos da cascata que rodam no Pi estão em `pi/pacotes`.
- **Dados brutos de terceiros** (Boa Energia, Brazilian Smart Home Testbed, LIT): baixe pelas fontes listadas
  em `dados_reais/LEIAME.md`.

## Licença

O código está sob a licença MIT (`LICENSE`). Dados, resultados, figuras e textos estão sob a licença
CC BY 4.0 (`LICENCA-DADOS.md`).

## Como citar

SILVA JUNIOR, Kleber Moraes da. **Detecção de anomalias no consumo elétrico residencial na borda:** qualidade,
custo e capacidade em um Raspberry Pi 5. 2026. Trabalho de Conclusão de Curso (Bacharelado em Ciência da
Computação) – Universidade de Marília, Marília, 2026. Disponível em:
<https://github.com/kleber112233/deteccao-anomalias-energia-borda>.
