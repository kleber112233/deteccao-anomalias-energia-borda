# detector — detecção de anomalias de energia no Raspberry Pi 5 (parte 2 do TCC, encerrada em 23/11/2026)

Treina, calibra e testa os cinco baselines nos datasets congelados (`TCC/datasets/v1`) e exporta cada modelo
para ONNX, o formato que o Raspberry Pi 5 vai rodar. Usa só o que chegaria ao Pi pelo MQTT
(ts, medidor, canal, potência, energia); o gabarito só é lido em `detector/avaliacao.py`.

    telemetria irregular (10 s, 30 s, 60 s, por evento)
            │  grade de 1 min, causal (só o passado)
            ▼
    atributos por canal + canal virtual "residuo" (geral − medidores próprios)
            │
            ├─ regra de limiar fixo ─┐
            ├─ Isolation Forest     ─┤  score por canal e minuto ──► normalização pelo treino do canal
            ├─ One-Class SVM        ─┤                                     │
            ├─ autoencoder (AE)     ─┤                          θ e persistência k escolhidos na calibração
            └─ LSTM-AE (60 min)     ─┘                                     │
                                                          alertas ──► avaliação por evento no teste (uma vez)
                         .onnx de cada canal ──► mesmo score no ONNX Runtime? (conferido)

## Instalação (Windows, Python 3.11)

Dentro de `TCC\detector`, sem ativar o venv (política de scripts do PowerShell):

    py -3.11 -m venv .venv
    .\.venv\Scripts\python -m pip install --upgrade pip
    .\.venv\Scripts\python -m pip install -r requirements.txt
    .\.venv\Scripts\python -m detector ambiente
    .\.venv\Scripts\python -m pytest -q                      # 29 testes (aprovados no Windows em 23/11/2026)

O venv é separado do simulador de propósito: o do simulador fica como está (32 testes aprovados) e este traz
as versões travadas do Pi (numpy 2.4.6, pandas 3.1.1, scikit-learn 1.9.1, onnxruntime 1.32.0) e o PyTorch.
O `casasim` entra em modo editável (`-e ../simulador`) só para ler os datasets sem o gabarito.

## Uso

    .\.venv\Scripts\python -m detector baselines --processos 8                     # tudo: 3 perfis × 5 sementes × 5 modelos, 8 casas por vez
    .\.venv\Scripts\python -m detector baselines --perfis perfil1 --sementes 1      # uma casa
    .\.venv\Scripts\python -m detector baselines --modelos regra if ocsvm ae         # sem o LSTM-AE
    .\.venv\Scripts\python -m detector baselines --desenvolvimento                   # não lê o teste (escolhas de projeto)
    .\.venv\Scripts\python -m detector consolidar                                    # refaz as tabelas
    .\.venv\Scripts\python -m detector cascata --processos 8                       # cascata com os modelos oficiais (resultados/cascata_v1)
    .\.venv\Scripts\python -m detector empacotar perfil1 1                         # o que o Pi precisa para uma casa (pi/pacotes/perfil1_s1)
    .\.venv\Scripts\python -m detector campanha --processos 8                      # cenários com dados novos (resultados/campanha_v1)
    .\.venv\Scripts\python -m detector e5 ..\simulador\registros\aovivo_....jsonl  # análise de uma sessão ao vivo
    .\.venv\Scripts\python -m detector cascata --filtro if --sem-regra --cache ..\resultados\_cache   # variantes (exploratório)
    .\.venv\Scripts\python -m detector e3 ..\resultados\e3_AAAAMMDD_HHMM ..\simulador\registros\e3_fiel  # análise do E3/E4/E6

No Raspberry Pi (dentro de ~/tcc-pi, com o venv de lá; não precisa de torch nem de casasim):

    .venv/bin/python -m detector reproduzir --pacote pacotes/perfil1_s1 --dados semente_1 --orcamento 0 0.05 1
    .venv/bin/python -m detector servico --pacote pacotes/perfil1_s1 --broker localhost --registro aovivo.jsonl
    .venv/bin/python -m detector custo --casa baselines/perfil1/semente_1 --dados dados/perfil1/semente_1   # E2 (ver pi/E2_NO_PI.md, pi/e2.sh)
    bash e3_pi.sh          # E3/E4/E6: serviço em modo de carga (--carga pacotes/perfil3_s1); o PC roda pi/e3_pc.py

Resultados finais de todos os experimentos (tabelas e figuras para o artigo): `TCC/resultados/pacote_artigo/`
(ler o `LEIAME.md` de lá). Histórico completo de decisões e números: `DIARIO.md` (seções A–K).

Saída em `TCC/resultados/baselines_v1/`:

| Arquivo | Conteúdo |
| --- | --- |
| `tabela_perfil_modelo.csv` | média e desvio-padrão entre sementes: AUC-PR por evento e por minuto, precisão, revocação, F1, FP/dia, atraso |
| `tabela_por_tipo.csv` | revocação e atraso por tipo de falha, perfil e modelo |
| `tabela_por_semente.csv` | uma linha por casa e modelo, com θ, k, tempos e a conferência do ONNX |
| `perfilN/semente_S/casa.json` | canais, limiares de "ligado", P(ligado \| hora), faltas de energia reconhecidas, versões |
| `perfilN/semente_S/<modelo>/<canal>.onnx` | modelo exportado (entrada `x`, saída `score`) |
| `perfilN/semente_S/<modelo>/config.json` | o que o Pi precisa: atributos, normalização, θ, k, hiperparâmetros, paridade ONNX |
| `perfilN/semente_S/<modelo>/eventos_teste.csv` | cada falha: detectada?, atraso, canal do alerta |
| `perfilN/semente_S/<modelo>/alertas_teste.csv` | cada alerta: canal, início, fim, verdadeiro? |
| `perfilN/semente_S/<modelo>/curva_*.csv` | precisão × revocação para cada θ (e k) |

## Organização

| Arquivo | Conteúdo |
| --- | --- |
| `detector/dados.py` | leitura sem gabarito; chave do canal (`t1`, `q_c1`, `c1_c3`); contexto da partição anterior |
| `detector/atributos.py` | grade de 1 min, potência pela energia, picos, tempo ligado, raridade de horário, resíduo |
| `detector/modelos.py` | os cinco detectores atrás de uma interface única e a exportação ONNX |
| `detector/avaliacao.py` | eventos, alertas, casamento, AUC-PR, escolha de θ e k, faltas de energia |
| `detector/experimento.py` | fluxo por casa e consolidação das tabelas |
| `detector/cascata.py` | cascata OCSVM + regra → LSTM-AE com os .onnx oficiais: orçamento de escalada, saída antecipada, conferência |
| `detector/aovivo.py` | a versão do Pi: mensagem a mensagem, minuto a minuto, mesmos atributos e alarmes do notebook; `empacotar` |
| `detector/campanha.py` | cenários com dados novos do simulador (orçamentos, perda, medidor mudo, fora de ordem, duplicadas, deriva) |
| `detector/e5.py` | análise de uma sessão ao vivo a partir do registro do simulador (detecção, atraso, latência) |
| `detector/servico.py` | serviço MQTT do Pi (alertas em `casa/sistema/alertas`, estado a cada 10 s, registro JSONL), fila interna, modo de carga com controlador de orçamento (E3/E4) e `reproduzir` |
| `detector/custo.py` | E2: latência de uma inferência de cada modelo no Pi |
| `detector/e3.py` | análise do teste de carga (atraso, fila, % processado, CPU, controlador) |
| `tests/` | 29 testes com uma casa sintética (causalidade, pico na energia, casamento, ONNX, ponta a ponta, cascata, ao vivo = notebook, campanha, E5, modo de carga, controlador, vigilância ao baixar o orçamento) |
| `DIARIO.md` | decisões, motivos, fontes e números (vira a seção de métodos) |
