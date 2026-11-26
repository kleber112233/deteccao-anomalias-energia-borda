# Diário de bordo — detector (parte 2 do TCC): baselines

Registro das decisões, com motivo, fonte e números, para virar a seção de métodos do artigo.
Mesma convenção do simulador: **[medido]** veio de rodada ou fonte lida; **[derivado]** foi calculado a partir
disso; **[assumido]** é escolha minha, a defender no texto.

---

## 22/11/2026 — A. Onde o código mora e com que ambiente

### A1. Pacote novo `TCC/detector/`
- Mesmo estilo do simulador: pacote Python, `README.md`, este diário, testes pytest (`tests/`, 18 testes com uma casa
  sintética). Resultados em `TCC/resultados/baselines_v1/` (fora do pacote).
- O detector lê os datasets por `casasim.datasets.carregar` (que recusa as colunas de gabarito) e só as colunas
  que chegariam pelo MQTT: `ts`, `medidor_id`, `canal`, `potencia_w`, `energia_wh`. O gabarito só é lido em
  `avaliacao.py`; há teste que procura `gabarito_falhas` no código de `dados.py`, `atributos.py` e `modelos.py`.
- Nem o `resumo.json` é lido: ele tem contagens de falhas por tipo. A lista de canais e qual é o medidor geral saem
  da própria telemetria (o geral é o medidor `q`, como diz o contrato MQTT v1.2).

### A2. venv novo no Windows (`TCC/detector/.venv`), não o do simulador
- **Motivo:** o venv do simulador está aprovado (32 testes) e não precisa de PyTorch; o do detector precisa das
  versões travadas iguais às do Pi (numpy 2.4.6, pandas 3.1.1, scikit-learn 1.9.1, onnxruntime 1.32.0) e do torch.
  Misturar arriscaria quebrar o simulador por troca de versão de numpy ou pandas.
- `requirements.txt` instala o `casasim` em modo editável (`-e ../simulador`), skl2onnx 1.20.0, onnx 1.23.2,
  onnxscript 0.7.2 e torch 2.15.0 (no Windows, o pacote do PyPI é só CPU).
- Para o `-e ../simulador` funcionar, o `pyproject.toml` do simulador passou a declarar que só `casasim` é pacote
  (registrado também no DIARIO do simulador). Testado: com as versões travadas, `casasim` importa e os testes do
  detector passam.
- **Onde testei:** num ambiente Linux x86 com Python 3.11.15 e exatamente essas versões (2 núcleos Xeon 2,1 GHz,
  7 GB). Os números que valem para o artigo saem da rodada do Kleber no notebook.

### A3. Exportação ONNX
- IF e OCSVM: `skl2onnx`, `target_opset = {"": 17, "ai.onnx.ml": 3}`; no IF, opção `score_samples`. Acrescentei ao
  grafo um `Reshape` + `Neg` para que **todo modelo tenha a mesma saída: `score` [N], maior = mais anômalo**. O
  OCSVM sai com opset 9 / ai.onnx.ml 1 (o skl2onnx usa o mínimo necessário); o ONNX Runtime 1.32 aceita.
- AE e LSTM-AE: a padronização (média e desvio do treino) fica DENTRO da rede, como buffers, e a saída já é o erro
  de reconstrução. Assim o Pi passa os atributos crus e recebe o score.
- **Achado [medido]:** no torch 2.15 o exportador novo (`dynamo=True`) só gera opset 18; pedir 17 falha na
  conversão ("No initializer or constant input to node found"). O exportador TorchScript (`dynamo=False`) respeita
  o opset 17 e gera o nó `LSTM` nativo do ONNX. Fiquei com ele (decisão 6 do plano: opset 17). Ele está marcado
  como obsoleto no torch; se sumir numa versão futura, a saída é aceitar opset 18 (o ONNX Runtime do Pi aceita).
- Conferência: o pipeline exporta cada modelo de cada canal, roda o teste inteiro também no ONNX Runtime e compara
  score, decisões e F1 (colunas `onnx_*` da `tabela_por_semente.csv`). No desenvolvimento: diferença máxima de
  score 2,5e-7 (IF), 1,1e-5 (OCSVM), 5,7e-6 (AE), 3,1e-5 (LSTM-AE); decisões de alarme iguais em 100% dos minutos,
  exceto uma rodada do IF com 99,993% (alguns minutos com score exatamente na beira de θ; o ONNX faz a média das
  árvores em float32).

---

## B. Os cinco baselines (hiperparâmetros fixados antes de qualquer resultado; nada ajustado no teste)

Um modelo por canal de medição (escolha do Kleber em 22/11/2026, entre "por canal", "por casa" e os dois) e mais
um para o canal virtual `residuo` (seção D3). Cada casa treina só com os 72 dias de treino dela: os 62 primeiros
para ajustar, os 10 últimos como validação (parada antecipada das redes).

| Modelo | Entrada | Configuração | Fonte |
| --- | --- | --- | --- |
| Regra de limiar fixo | `p_max15` | alarme quando a maior potência de 15 min passa de um limite do canal; o limite em W sai da normalização (D4) e de θ | — |
| Isolation Forest | 16 atributos (18 no geral) | 100 árvores, 256 amostras por árvore, `random_state` = semente | Liu, Ting e Zhou (2008), valores do artigo |
| One-Class SVM | idem, padronizados | RBF, `gamma="scale"`, ν = 0,01, 5.000 minutos sorteados do treino (custo quadrático) [assumido] | Schölkopf et al. (2001) |
| Autoencoder | idem | d → 32 → 8 → 32 → d, ReLU, Adam 1e-3, lote 512; treina até convergir (G2) [assumido] | — |
| LSTM-AE | 60 min × 10 atributos (11 no geral) | codificador LSTM(32) → vetor repetido → decodificador LSTM(32) → linear; Adam 1e-3, lote 256, janelas de treino a cada 5 min; treina até convergir (G2) [assumido] | Malhotra et al. (2016) |

Score: IF = −`score_samples`; OCSVM = −`decision_function`; redes = erro quadrático médio da reconstrução
(no espaço padronizado).

---

## C. Avaliação por evento (o que o artigo vai chamar de protocolo)

### C1. Evento
- Uma falha do gabarito com `alerta_de_aparelho = True` e pelo menos um dia `efetiva = True`.
- Intervalo = do primeiro `efeito_inicio` ao último `efeito_fim` efetivos (quando o sinal mudou de fato, não a
  janela pedida). Falhas que não mudaram o sinal (ex.: ferro com falha de magnitude num dia sem uso) não contam.
- Canais que podem detectar o evento: o `canal_direto` (medidor próprio), se houver; os canais do medidor geral; e
  o canal `residuo`. Alerta em outro canal é falso.
- Falta de energia (`alvo = rede`) fica fora: tem avaliação própria (C5).

### C2. Alarme e alerta
- Alarme no minuto m do canal c: score normalizado > θ durante k minutos seguidos (persistência, causal).
- Minutos de alarme do mesmo canal separados por até 10 min viram um alerta [assumido].
- **θ e k ∈ {1, 3, 5} são escolhidos juntos na calibração**, maximizando o F1 por evento (empate: menos alertas,
  depois θ maior). Um só θ por casa e modelo, porque cada canal já vem normalizado (D4). Os candidatos a θ são 120
  quantis dos scores da calibração, do topo 10⁻⁶ até a mediana.

### C3. Casamento
- Alerta verdadeiro (VP): começa entre `efeito_inicio − 5 min` e `efeito_fim + 30 min` de um evento, num canal que
  o enxerga [assumido: tolerância de 30 min porque "queda" e "duração" só ficam visíveis depois de um tempo].
- Evento detectado: tem ao menos um alerta VP. **Atraso** = início do primeiro alerta VP − `efeito_inicio` (≥ 0).
- **Localizado**: algum alerta VP veio do medidor próprio do aparelho (só para eventos que têm medidor próprio).

### C4. Métricas
- **Precisão por evento** = eventos detectados / (eventos detectados + alertas falsos). Vários alertas no mesmo
  evento contam uma vez; cada alerta falso conta. É a convenção de Hundman et al. (2018) [referência a conferir e
  acrescentar a `dados_pesquisa.md`: HUNDMAN, K. et al. Detecting spacecraft anomalies using LSTMs and nonparametric
  dynamic thresholding. KDD 2018]. **Por que não por alerta:** na primeira versão contei alertas VP / alertas, e uma
  única falha de magnitude da geladeira gerou 12 alertas "verdadeiros", inflando a precisão.
- **Revocação** = eventos detectados / eventos; **F1**; **FP por dia** (o que o morador sente no celular).
- **AUC-PR por evento**: varre θ (com o k escolhido) e soma em degraus Σ (Rᵢ − Rᵢ₋₁)·Pᵢ, como a average precision.
- **AUC-PR por minuto** (`average_precision_score` com o rótulo do minuto), só para comparar com a literatura.
- Por perfil, por semente (média e desvio entre as 5) e por tipo de falha (revocação e atraso).

### C5. Falta de energia (regra fixa, igual para todos os modelos)
- Todos os canais da casa sem mensagem há mais de 150 s = falta (evento da rede). Os alarmes ficam suprimidos
  durante a falta e por 30 min depois [assumido: os aparelhos religam, a geladeira compensa o tempo parado].
- Relatório próprio em `casa.json`: faltas do gabarito reconhecidas pela regra e silêncios sem falta.

### C6. Disciplina do teste
- O modo `--desenvolvimento` não lê o arquivo de teste: métricas na calibração. **Todas as escolhas das seções D e
  E foram feitas nesse modo**, com a calibração de 6 casas (perfil 1, 2 e 3, sementes 1 e 2).
- **Para não esconder nada:** a primeira versão do pipeline (antes de C4, D3, D5, D6 e da persistência k) chegou a
  rodar no teste do perfil 1, semente 1, com regra, IF e OCSVM (F1 de 0,25 / 0,11 / 0,53). Vi esses números. Depois
  disso, nada mais foi olhado no teste. A rodada oficial do Kleber refaz tudo do zero.

---

## D. Atributos (`detector/atributos.py`)

### D1. Grade de 1 minuto, causal
- A decisão do minuto m é tomada no fim dele e só usa mensagens com `ts` < fim do minuto (teste
  `test_atributos_sao_causais`: alterar o futuro não muda nenhum atributo do passado).
- Calibração e teste recebem as últimas 24 h da partição anterior como contexto (o Pi fica ligado o tempo todo);
  nenhuma decisão é tomada no contexto.
- Por canal e minuto:
  - `p_med`: média no tempo da potência informada (valor mantido até a próxima mensagem, amostrado a cada 5 s).
    Serve igual para 10 s, 30 s, 60 s e para o Shelly por evento.
  - `e_pot`: potência média pela energia, Δ`energia_wh` / Δt.
  - `exc`: maior excesso, num intervalo entre duas mensagens, da potência pela energia sobre a média das duas
    leituras. **É o rastro dos picos de 1–3 s** (o contrato diz que eles quase não aparecem em `potencia_w`). Teste:
    um pico de 3.000 W por 2 s entre leituras de 30 s não muda `p_med` e dá `exc` > 150 W.
  - `vivo`: houve mensagem nos últimos 150 s [assumido: 2,5× o maior intervalo, 60 s].

### D2. Estado ligado e tempos
- Limiar de "ligado" por canal, aprendido no treino: 20% do percentil 90 da potência nos minutos com mais de 1 W,
  no mínimo 2 W [assumido]. Exemplos [medido, perfil 2, semente 1]: geladeira 20,9 W; chuveiros 1.327 e 1.185 W;
  micro-ondas 252 W; bomba d'água 70 W; lâmpadas 4,8 e 12 W.
- `run_on` (minutos ligado; desligado por até 3 min não encerra, por causa de termostato e ciclos), `desde_on`
  (minutos desde a última vez ligado), partidas na última hora. Tempos limitados a 24 h.

### D3. Canal virtual `residuo` [decisão tomada com a calibração]
- `residuo` = medidor geral (soma das fases) − soma dos medidores próprios, minuto a minuto. Recebe os mesmos
  atributos e um modelo próprio, como qualquer canal.
- **Motivo [medido, calibração do perfil 1, semente 1]:** na falha F0006 (consumo não explicado de +414 W, das 10h10
  às 17h53), a mediana de 60 min do resíduo foi de 23 W para 433–525 W, enquanto no treino o percentil 95 dessa
  mediana entre 10h e 17h é de 24 a 116 W. O sinal é claro, mas dentro do modelo do medidor geral ele é 2 de 18
  atributos de um canal que já varia muito (chuveiro de 5 kW), e nenhum modelo o detectava (0 de 2 eventos de
  consumo não explicado no perfil 1 e no perfil 2).
- É também a forma concreta do "monitoramento hierárquico" (medidor geral + aparelhos) que o plano coloca como
  contribuição: o Pi vigia cada aparelho medido e, à parte, o que os aparelhos medidos não explicam. Aparelhos sem
  medidor próprio (chuveiro do perfil 1, air fryer) aparecem justamente nele.

### D4. Normalização por canal [decisão tomada com a calibração]
- s = (score − mediana do treino) / (máximo do treino − mediana), com os minutos de falta de energia fora. Um único
  θ vale para a casa toda; s = 1 é "tão estranho quanto o minuto mais estranho do treino daquele canal".
- Comparei, só na calibração das 6 casas, a escala pelo percentil 99,9, 99,99 e pelo máximo (média da AUC-PR por
  evento) [medido]:

| Modelo | p99,9 | p99,99 | máximo |
| --- | --- | --- | --- |
| Regra | 0,203 | 0,257 | 0,257 |
| IF | 0,153 | 0,186 | 0,190 |
| OCSVM | 0,378 | 0,387 | 0,405 |
| AE | 0,432 | 0,421 | 0,430 |

  O máximo é igual ou melhor em todos e é o mais fácil de explicar. Motivo de fundo: com o p99,9, canais de cauda
  pesada (lâmpadas, TV + videogame) tinham, fora das falhas, scores de até 5–6, e o θ único subia por causa deles.

### D5. Raridade de horário [decisão tomada com a calibração]
- Tabela P(ligado | hora) de cada canal, contada no treino com suavização de Laplace (24 números por canal).
  Atributo: −log10 P(ligado | hora) enquanto o canal está ligado (máximo dos últimos 15 min na entrada tabular).
- **Motivo:** o plano já pedia contexto ("sem contexto o IF não enxerga anomalia de horário"), mas seno e cosseno
  da hora são 2 de 16 atributos. Micro-ondas à 1h35 no perfil 2 (F0009) passava sem alerta em todos os modelos.
  Depois dele (introduzido junto com o resíduo), fora de horário na calibração: perfil 1 de 1/3 para 3/3 (OCSVM e AE); perfil 2 de 1–2/3 para
  2–3/3.

### D6. Lista final
- Tabular (16; +2 nos canais do geral): `p_med15, p_max15, p_std15, p_min15, p_med60, p_mediana60, e_pot15,
  exc_max15, frac_on15, trans60, run_on, desde_on, raridade15, hora_sin, hora_cos, fds` (+ `res_mediana60,
  res_med15`). Potências em log(1 + W) com sinal, para que o fator de uma falha de magnitude vire uma soma.
- Sequência do LSTM-AE (10 por minuto; +1 no geral): `p_med, e_pot, exc, on, run_on, desde_on, raridade, hora_sin,
  hora_cos, fds` (+ `res`).
- `p_mediana60` entrou junto com o resíduo (é o "piso" de consumo de uma hora, robusto aos banhos).
- Temperatura externa não entra: o Pi não a recebe pelo MQTT (está só no `verdade_1min`, que é gabarito).

---

## E. Resultados do desenvolvimento (só calibração; NÃO são os resultados do artigo)

Calibração de 6 casas (perfil 1, 2 e 3; sementes 1 e 2), θ e k escolhidos na própria calibração, portanto
otimista. Serve para ordenar os modelos e achar problemas, não para citar.

| Modelo | AUC-PR por evento | F1 | Precisão | Revocação | FP/dia |
| --- | --- | --- | --- | --- | --- |
| Regra | 0,26 | 0,37 | 0,80 | 0,27 | 0,08 |
| IF | 0,19 | 0,30 | 0,49 | 0,23 | 0,18 |
| OCSVM | 0,41 | 0,51 | 0,53 | 0,56 | 0,38 |
| AE | 0,43 | 0,54 | 0,62 | 0,51 | 0,23 |
| LSTM-AE | só perfil 1, semente 1 até agora: 0,56 (AE na mesma casa: 0,61) | 0,62 | 0,67 | 0,57 | 0,17 |

### E1. O Isolation Forest satura [medido; importante para a cascata]
- O score do IF quase não passa do máximo visto no treino: na calibração do perfil 1, semente 1, os minutos normais
  chegam a s = 1,09 e as falhas ficam entre 0,63 e 1,03 (normalização pelo p99,9, antes de D3–D5). A geladeira parada por 4 h (F0008) deu 0,63 no IF e 8,6 no
  OCSVM.
- Causa (do próprio algoritmo): os cortes de cada árvore são sorteados entre o mínimo e o máximo das amostras do
  nó, então um ponto além da borda do treino é isolado na mesma profundidade que o ponto da borda. "Mais do
  mesmo" (geladeira parada há 4 h quando o normal é 30 min; consumo 1,8× maior) não fica mais anômalo que o normal
  mais extremo.
- **Consequência para a cascata:** o estágio 1 só repassa ao LSTM-AE o que o IF acha suspeito. Se o IF não separa
  essas falhas, a cascata herda o ponto cego (é a "limitação assumida" do plano). Levar ao Kleber como decisão (F2).

### E2. Perfil 3 é o mais difícil
- AUC-PR por evento do AE: 0,27 e 0,36 no perfil 3, contra 0,41–0,61 no perfil 1. Com 32 canais, cada canal
  acrescenta alarmes falsos e o θ único sobe.

### E3. LSTM-AE: custo de treino [medido]
- No ambiente de teste (Xeon 2,1 GHz, **1 thread**), 128 s por canal; o perfil 1 (6 canais) levou 12,9 min. Nas 15
  casas são 270 modelos (6 + 16 + 32 canais por semente, × 5): cerca de 9,6 h com 1 thread. Com mais núcleos cai,
  mas não na mesma proporção (rede pequena, lotes de 256).
- Em 4 de 6 canais o treino parou no teto de 60 épocas com a perda de validação ainda caindo devagar. Resolvido em
  G2 (treino até convergir).
- Por tipo, na calibração do perfil 1, semente 1: fora de horário 3/3, queda 2/2, duração 2/3, consumo não
  explicado 1/2, magnitude 0/2, pico 0/2.
- Inferência em lote no x86 (indicativo; o E2 mede no Pi): LSTM-AE 39 µs por janela no PyTorch e 67 µs no ONNX
  Runtime com 1 thread; AE 0,1 µs; OCSVM ~4 µs (sklearn) e ~1 µs (ONNX); IF ~3 µs (sklearn) e ~16 µs (ONNX).
- Lição prática: dois processos de treino ao mesmo tempo, cada um com o número padrão de threads do PyTorch,
  deixaram o AE 13× mais lento (572 s contra 44 s). Na rodada oficial, rodar um processo só.

---

## G. 22/11/2026 — Ajustes para o notebook do Kleber

### G1. Hardware da rodada oficial [medido, informado pelo Kleber]
- Intel Core i9-12900KF (16 núcleos: 8 de desempenho + 8 de eficiência; 24 threads), 31,8 GB de RAM,
  NVIDIA GeForce RTX 3080 Ti, 369 GB livres no disco C:.
- **A rodada usa só a CPU** [decisão]: as redes são pequenas (h = 32, lotes de 256), a GPU ganharia pouco e exigiria
  o PyTorch com CUDA (outro pacote, de outro site) e deixaria os resultados menos reprodutíveis. Assim o ambiente é
  o mesmo testado aqui e os .onnx não mudam.
- **Paralelismo por casa** (`--processos N`): cada casa roda num processo com 1 thread. Motivo: no teste, dois
  processos disputando threads deixaram o AE 13× mais lento (E3); um processo por casa com 1 thread não disputa.

### G2. Redes treinadas até convergir [decisão]
- Antes, o AE parava no teto de 40 épocas em todos os canais e o LSTM-AE no de 60 em 4 de 6 canais: o teto, e não
  os dados, decidia quanto treinar. Agora: parada antecipada quando a perda de validação (os 10 últimos dias do
  treino, só comportamento normal) passa 5 épocas sem cair 0,1% (melhora relativa); tetos de 200 (AE) e 150
  (LSTM-AE) só como segurança. É a regra padrão e não usa nenhuma falha.
- Com a regra nova, o AE do perfil 1, semente 1, parou entre 59 e 120 épocas, com perda de validação bem menor
  (geladeira: 0,0022).
- **Efeito observado na calibração, registrado para não esconder:** o AE convergido ficou PIOR na semente 1 do
  perfil 1 (AUC-PR por evento 0,61 → 0,41) e melhor na semente 2 (0,41 → 0,51). Um autoencoder treinado por mais
  tempo também aprende a reconstruir o que é anômalo. Mantive a convergência mesmo assim: escolher o número de
  épocas pela AUC da calibração seria ajustar o AE nas falhas, coisa que não fiz em nenhum outro modelo. Possível
  estudo futuro: gargalo menor (8 → 4).

### G3. Ensaio no notebook (modo desenvolvimento, perfil 1, semente 1, 1 thread) [medido em 22/11/2026]
- Ambiente: Windows (build 26300), Python 3.11.9, numpy 2.4.6, pandas 3.1.1, scikit-learn 1.9.1, onnxruntime 1.32.0,
  skl2onnx 1.20.0, torch 2.15.0+cpu; 18 testes aprovados (inclui a exportação ONNX do AE e do LSTM-AE no Windows).
- **Reprodutibilidade entre máquinas:** regra (AUC-PR por evento 0,357), IF (0,232) e OCSVM (0,666) deram exatamente o
  mesmo que no Linux de teste. As redes, não: AE 0,464 no Windows contra 0,410 no Linux; as épocas até convergir
  quase coincidem (ex.: TV 86 × 93; resíduo 101 × 100). Causa: o PyTorch usa rotinas de cálculo diferentes em cada
  sistema, e diferenças mínimas de arredondamento mudam a trajetória do treino. Na mesma máquina e com a mesma
  semente o resultado se repete. **Os números do artigo são os do notebook.**
- Tempo com 1 thread, 6 canais: regra 2 s, IF 61 s, OCSVM 12 s, AE 190 s, LSTM-AE 1.191 s (≈ 200 s por canal;
  47 a 110 épocas). Total 24,4 min ≈ 243 s por canal com os 5 modelos.
- **Estimativa da rodada oficial [derivado]:** 270 canais × 243 s ≈ 18 h de CPU com 1 thread. A casa mais demorada
  (perfil 3, 32 canais) leva ≈ 2,2 h num núcleo de desempenho; com 8 processos, o total fica entre 2,5 e 4 h
  (os núcleos de eficiência do i9 são mais lentos). Disco: ≈ 6 MB por casa (o IF é o maior, 5,5 MB).

## H. 22/11/2026 — Rodada oficial dos baselines (teste usado uma vez) [medido]

Notebook do Kleber (i9-12900KF, Windows, Python 3.11.9, versões travadas), `python -m detector baselines --processos 8`,
153,8 min. 15 casas × 5 modelos = 75 avaliações; 198 eventos de aparelho no teste. Tabelas em
`TCC/resultados/baselines_v1/` (`tabela_perfil_modelo.csv`, `tabela_por_tipo.csv`, `tabela_por_semente.csv`) e log em
`TCC/resultados/baselines_v1_log.txt`. Média ± desvio-padrão entre as 5 sementes.

### H1. Geral (15 casas)
| Modelo | AUC-PR evento | AUC-PR minuto | F1 | Precisão | Revocação | FP/dia | Atraso (mediana, min) | Localizado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Regra | 0,25 ± 0,10 | 0,07 | 0,28 ± 0,15 | 0,64 | 0,22 | 0,20 | 28 | 0,20 |
| IF | 0,09 ± 0,07 | 0,07 | 0,11 ± 0,11 | 0,19 | 0,09 | 0,41 | 63 | 0,09 |
| OCSVM | **0,43 ± 0,19** | 0,26 | 0,44 ± 0,16 | 0,52 | 0,45 | 0,48 | 23 | 0,44 |
| AE | 0,37 ± 0,16 | 0,21 | **0,44 ± 0,13** | 0,51 | 0,44 | 0,44 | 27 | 0,44 |
| LSTM-AE | 0,35 ± 0,14 | 0,13 | 0,35 ± 0,14 | 0,46 | 0,35 | 0,51 | **19** | 0,37 |

### H2. Por perfil (AUC-PR por evento)
| Modelo | Perfil 1 | Perfil 2 | Perfil 3 |
| --- | --- | --- | --- |
| Regra | 0,20 ± 0,08 | 0,31 ± 0,09 | 0,25 ± 0,13 |
| IF | 0,10 ± 0,07 | 0,12 ± 0,09 | 0,05 ± 0,03 |
| OCSVM | **0,59 ± 0,10** | 0,39 ± 0,20 | 0,30 ± 0,17 |
| AE | 0,44 ± 0,11 | **0,42 ± 0,15** | 0,26 ± 0,19 |
| LSTM-AE | 0,46 ± 0,08 | 0,27 ± 0,11 | **0,33 ± 0,17** |

### H3. Por tipo de falha (eventos detectados / eventos, 15 casas)
| Tipo | Regra | IF | OCSVM | AE | LSTM-AE |
| --- | --- | --- | --- | --- | --- |
| Consumo não explicado | 1/30 | 0/30 | 7/30 | **11/30** | 3/30 |
| Duração excessiva | 7/45 | 5/45 | 28/45 | **34/45** | 29/45 |
| Fora de horário | 2/45 | 8/45 | **28/45** | 14/45 | 23/45 |
| Magnitude | **25/31** | 3/31 | 5/31 | 5/31 | 4/31 |
| Pico | 8/30 | 0/30 | 9/30 | **13/30** | 3/30 |
| Queda | 0/17 | 1/17 | **12/17** | 10/17 | 8/17 |

### H4. Outros números
- **Falta de energia (regra do silêncio):** 30 de 30 faltas reconhecidas no teste, nenhum silêncio sem falta.
- **ONNX:** em todas as 75 avaliações, o F1 com os scores do ONNX Runtime é idêntico ao do modelo original; decisões
  de alarme iguais em ≥ 99,998% dos minutos; maior diferença de score 9,5e-4 (LSTM-AE do perfil 3, semente 3, cujos
  scores brutos são grandes).
- **Custo indicativo no x86** (µs por janela, em lote, 1 thread; o E2 mede no Pi): regra ~0; AE 0,3 (ONNX 0,3);
  OCSVM 8,1 (ONNX 1,6); IF 3,8 (ONNX 26,1); LSTM-AE 58,3 (ONNX 56,8).
- Persistência escolhida na calibração: regra sempre k = 1; OCSVM e AE quase sempre k = 5; IF e LSTM-AE variam.

### H5. Leitura (para a seção de resultados)
1. **O Isolation Forest é o pior baseline, abaixo da regra de limiar fixo** (AUC-PR 0,09 contra 0,25), confirmando E1
   (saturação fora da faixa do treino). Como ele é o estágio 1 planejado da cascata, isso exige decisão (F2).
2. **OCSVM e AE empatam no topo** (F1 0,44); o OCSVM tem a maior AUC-PR, o AE é o mais barato. O LSTM-AE não supera
   os dois em qualidade e custa ~200× mais por janela que o AE, mas tem o menor atraso (19 min) e é o 2º melhor em
   fora de horário.
3. **Complementaridade:** a regra de limiar fixo pega 25 de 31 falhas de magnitude, que os modelos de aprendizado
   quase não pegam (≤ 5/31); os modelos pegam duração, queda e fora de horário, que a regra não pega. Responde com
   dados à pergunta "por que não um if?": o if pega um tipo, os modelos pegam os outros.
4. **Perfil 3 é o mais difícil** para todos (mais canais → mais alarmes falsos com um θ único).
5. **Consumo não explicado e pico continuam difíceis** (no máximo 11/30 e 13/30).
6. A variação entre sementes é grande (desvio de 0,10 a 0,20 na AUC-PR), esperada com ~13 eventos por casa.

### H6. Insumo para escolher o estágio 1 da cascata (só calibração)
Revocação máxima que cada modelo alcança na calibração, com k = 1, aceitando até N alertas falsos por dia (um filtro
de estágio 1 pode ser permissivo, porque o estágio 2 confirma):

| Modelo | até 1 FP/dia | até 5 | até 20 | sem limite |
| --- | --- | --- | --- | --- |
| Regra | 0,25 | 0,34 | 0,64 | 0,95 |
| IF | 0,21 | 0,40 | 0,67 | 0,98 |
| OCSVM | 0,57 | 0,72 | 0,91 | 1,00 |
| AE | 0,52 | 0,68 | 0,89 | 0,99 |
| LSTM-AE | 0,52 | 0,67 | 0,85 | 0,94 |

### H7. Decisão: estágio 1 da cascata = OCSVM + regra (do Kleber, 22/11/2026)
- Opções apresentadas: manter o IF (como no plano), trocar pelo OCSVM, trocar pelo AE, ou OCSVM + regra. Escolhida
  a última: o canal escala para o LSTM-AE quando **o OCSVM ou a regra de limiar fixo** passam do limiar de suspeita.
- Motivos: o IF teve o pior resultado (AUC-PR 0,09) e, como filtro permissivo, alcança só 0,67 de revocação com até
  20 alertas falsos/dia na calibração, contra 0,91 do OCSVM; a regra custa quase nada e cobre a magnitude
  (25/31 no teste), onde todos os modelos de aprendizado falham (≤ 5/31).
- O IF continua no artigo como baseline (e como evidência de por que não serviu de estágio 1). O estágio 2 continua
  o LSTM-AE. O desenho da cascata (limiares de suspeita, histerese, controlador de τ) será feito só com a calibração.

## I. 22/11/2026 — Cascata offline: protocolo fixado ANTES do teste

### I1. O que é (`detector/cascata.py`, `python -m detector cascata`)
- Usa os .onnx e a normalização da rodada oficial dos baselines (nada é treinado de novo). Conferência embutida:
  cada modelo sozinho, com o θ e o k oficiais, tem de reproduzir o F1 da rodada oficial (teste automático também).
- Por canal e minuto:
  - **regra** com o limite e a persistência que ela já recebeu na calibração dos baselines. É um "if": quando
    dispara, alerta direto e também escala o canal;
  - **vigilância** = OCSVM > τ ou regra disparou, em algum dos últimos V = 30 min [assumido] → só então o LSTM-AE é
    calculado (minuto escalado);
  - **alarme** = regra OU persistência k de [OCSVM > θ_saída (saída antecipada, o estágio 1 tem certeza) OU
    (vigilância E LSTM-AE > θ2)]; depois, a mesma junção de alertas e supressão de faltas dos baselines.
- **τ vem de um orçamento** b = fração de minutos-canal escalados, ajustada na calibração sem usar rótulo:
  b ∈ {100%, 50%, 20%, 10%, 5%, 2%, 1%, 0%}. b = 100% é o LSTM-AE sempre ligado (com a regra e a saída
  antecipada); b = 0% é só o estágio 1 (OCSVM + regra). No Pi, o controlador de carga mexerá em b.
- Para cada b, θ_saída (15 quantis do topo do OCSVM + o θ oficial do OCSVM + "nunca"), θ2 (30 quantis do LSTM-AE
  entre os minutos escalados + o θ oficial do LSTM-AE + "nunca") e k ∈ {1, 3, 5} são escolhidos na calibração pelo
  maior F1 por evento. O teste é usado uma vez.
- Mede também: fração escalada no teste, **revocação do estágio 1** (evento escalado em algum minuto, num canal que o
  enxerga) por tipo, e custo relativo = (c_OCSVM + c_regra + p·c_LSTM) / c_LSTM, com os µs por janela do ONNX no x86
  (indicativo; no Pi o E2 mede de novo).

### I2. Por que a regra não entra no mesmo limiar do OCSVM [medido na calibração do perfil 2, semente 1]
- A primeira versão usava s1 = máx(OCSVM, regra) com um θ só. A regra normalizada fica perto de 1 sempre que um
  aparelho trabalha na sua potência nominal; no limiar do OCSVM ela gerou 184 alertas falsos contra 17 do OCSVM
  sozinho (F1 0,09 contra 0,47). Por isso a regra entra com o limite próprio.
- A grade de θ_saída também foi alargada (8 → 15 quantis, mais o θ oficial do OCSVM), porque com orçamento 0 a
  cascata não conseguia nem repetir o OCSVM sozinho (F1 0,29 contra 0,47 na mesma calibração).

### I3. Hipótese H1 com a margem definida antes do teste
- **H1:** com orçamento b ≤ 10%, o F1 médio da cascata nas 15 casas não fica mais de **0,05 abaixo** do F1 médio do
  LSTM-AE sozinho (0,345, seção H1). Também se compara com o melhor baseline sozinho (OCSVM 0,436 / AE 0,440).
- Desenvolvimento (só calibração, otimista, porque os limiares são escolhidos nela): perfil 1, semente 1 → F1 0,83
  em todos os orçamentos de 100% a 1% (LSTM-AE sozinho 0,64; OCSVM 0,67); perfil 2, semente 1 → 0,55–0,57 de 100% a
  1% (LSTM-AE 0,52; OCSVM 0,47). Esses números não valem como resultado.

### I4. Resultado no teste (usado uma vez; notebook do Kleber, 13,5 min, `--processos 8`) [medido]
- **Conferência:** nas 15 casas, OCSVM, regra e LSTM-AE sozinhos, recalculados pelos .onnx, deram exatamente o F1
  da rodada oficial. Testes: 21 aprovados no Windows.
- Média das 15 casas (`resultados/cascata_v1/tabela_cascata.csv`):

| Orçamento | Escalados no teste | F1 | Precisão | Revocação | FP/dia | AUC-PR evento | Atraso (min) | Rev. estágio 1 | Custo / LSTM sempre |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0% (só OCSVM + regra) | 0% | **0,496** | 0,52 | 0,56 | 0,46 | 0,29 | 9 | — | 0,03 |
| 1% | 1,2% | 0,494 | 0,53 | 0,52 | 0,40 | 0,35 | 15 | 0,78 | 0,04 |
| 5% | 5,6% | 0,484 | 0,50 | 0,53 | 0,45 | 0,37 | 15 | 0,96 | 0,08 |
| 10% | 10,9% | 0,487 | 0,50 | 0,52 | 0,42 | 0,37 | 15 | 0,98 | 0,14 |
| 100% (LSTM-AE sempre) | 100% | 0,484 | 0,51 | 0,52 | 0,42 | 0,37 | 14 | 1,00 | 1,03 |

  Referências (seção H1): LSTM-AE sozinho F1 0,345; OCSVM 0,436; AE 0,440; regra 0,277; IF 0,106.
- **H1 confirmada com folga:** com orçamento ≤ 10%, F1 de 0,484–0,494, acima do LSTM-AE sozinho (0,345), e não
  abaixo dele menos 0,05, que era o critério.
- **Mas o ganho vem do estágio 1, não do LSTM-AE.** Só o estágio 1 (OCSVM + regra, orçamento 0%) já dá F1 0,496 — o
  melhor resultado de todo o trabalho, acima de qualquer modelo sozinho — a 3% do custo de rodar o LSTM-AE sempre.
  Ligar o LSTM-AE (de 1% a 100%) não muda o F1 médio (0,48–0,49): sobe a AUC-PR (0,29 → 0,37: o ranking melhora),
  mas, entre orçamento 0% e 100%, 4 eventos passam a ser detectados e 12 deixam de ser (a calibração passou a confiar
  no LSTM-AE e subiu o limiar da saída antecipada do OCSVM).
- Por perfil: o LSTM-AE ajuda no **perfil 1** (F1 0,54 → 0,59 com 1% escalado; é a casa que mede só 25% do consumo) e
  atrapalha um pouco nos perfis 2 (0,46 → 0,45) e 3 (0,49 → 0,44).
- Por tipo (orçamento 0% → 10%): magnitude 25/31 → 25/31; duração 27/45 → 29/45; fora de horário 26/45 → 23/45;
  queda 12/17 → 9/17; pico 13/30 → 11/30; consumo não explicado 7/30 → 6/30.
- **Revocação do estágio 1** (o evento foi escalado): 78% com 1% dos minutos escalados, 96% com 5%, 98% com 10%.
- **Leitura para o artigo:** a curva "% escalados × F1" é plana: o Pi pode cortar o LSTM-AE para 1% dos minutos
  sem perder qualidade, ou seja, a política adaptativa degrada de graça sob carga. O resultado honesto é que a
  qualidade vem da combinação OCSVM + regra (complementares, H5); o LSTM-AE melhora o ranking (AUC-PR) e o perfil 1.
- **Cuidado:** qualquer variante nova da cascata testada agora (ex.: trocar o LSTM-AE pelo AE no estágio 2) seria
  escolhida depois de ver este teste; se for feita, entra no artigo como análise exploratória, separada.

## J. 22/11/2026 — Versão ao vivo (o que roda no Pi)

### J1. Como funciona (`detector/aovivo.py`, `detector/servico.py`)
- Processa mensagem por mensagem. Cada canal guarda só o necessário: as últimas mensagens (para o valor mantido
  dentro do minuto), os acumuladores de energia do minuto e as janelas de 15/60 min. O minuto m de uma casa é fechado
  quando chega uma mensagem com ts ≥ fim do minuto: o relógio é o das próprias mensagens, então funciona igual com o
  simulador em tempo real, acelerado ou reproduzindo um arquivo. Mensagem fora de ordem é descartada e contada.
- Ao fechar o minuto: sinais → resíduo → atributos → regra e OCSVM → LSTM-AE só se o canal estiver em vigilância →
  alertas (mesma junção de 10 min) publicados em `casa/sistema/alertas`.
- Depende só de numpy, pandas (leitura dos datasets) e onnxruntime: o venv do Pi já tem tudo; não precisa de torch nem
  de casasim. `python -m detector empacotar perfil1 1` junta em `TCC/pi/pacotes/perfil1_s1/` (468 kB) os 12 .onnx,
  a normalização, os limiares de "ligado", P(ligado | hora) e os parâmetros calibrados de todos os orçamentos.
- **Orçamento padrão do pacote: 5%** [assumido]: na calibração ele já escala 96% das falhas; no Pi o controlador de
  carga (E4) vai mexer nele.

### J2. Igual ao notebook [medido]
- Reprodução da calibração do perfil 1, semente 1 (36.000 minutos, 359 mil mensagens) e do perfil 2, semente 1
  (936 mil mensagens, 16 canais): entrada do LSTM-AE **idêntica** em todos os minutos; atributos tabulares iguais, exceto
  o desvio-padrão de 15 min, com diferença de até 2,7e-4 (o pandas acumula erro de arredondamento na janela móvel; a
  versão ao vivo recalcula a janela inteira); supressão de faltas idêntica; **nenhum minuto de alarme diferente**
  (672 e 1.155 minutos de alarme com orçamento 5%).
- Testes automáticos (25 no total): atributos e entrada do LSTM-AE iguais e alarmes iguais aos da cascata do notebook
  com orçamentos 100%, 10% e 0% na casa sintética; leitura das mensagens MQTT (ts ISO, canal, mensagem desconhecida,
  fora de ordem).

### J3. Custo por minuto, antes do Pi (reprodução do teste do perfil 1, semente 1; 6 canais) [medido, x86, indicativo]
| Orçamento | ms por minuto da casa | atributos | estágio 1 | estágio 2 | escalados |
| --- | --- | --- | --- | --- | --- |
| 0% | 0,89 | 0,77 | 0,09 | 0 | 0% |
| 5% | 0,93 | 0,76 | 0,09 | 0,04 | 5,0% |
| 100% | 1,86 | 0,86 | 0,12 | 0,83 | 99,8% |
(Xeon 2,1 GHz do ambiente de teste; na VM do notebook, 0,58 ms/minuto com 5%.)
- **Achado importante para o E3:** com decisão a cada minuto, o cálculo dos atributos em Python (~0,13 ms por canal)
  pesa tanto quanto rodar o LSTM-AE sempre (~0,14 ms por canal). A cascata corta o custo total pela metade
  (1,86 → 0,93 ms), não por 30×, porque o resto do caminho não depende dela. O E2 no Pi vai medir isso de verdade;
  otimizar os atributos é uma opção antes do E3, para a comparação ficar justa.

### J4. Primeira medição no Raspberry Pi 5 (23/11/2026; preliminar: governador `ondemand`, sem dissipador nem ventoinha) [medido]
Reprodução do teste do perfil 1, semente 1 (358.626 mensagens, 36.000 minutos, 6 canais), 1 processo:

| Orçamento | ms por minuto da casa | atributos | estágio 1 | estágio 2 | µs por mensagem | escalados | alertas | temp. no fim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0% | 1,31 | 1,12 | 0,16 | 0 | 132 | 0% | 24 | 68,9 °C |
| 5% | 1,40 | 1,13 | 0,16 | 0,08 | 141 | 5,0% | 25 | 73,3 °C |
| 100% | 3,20 | 1,23 | 0,23 | 1,68 | 322 | 99,8% | 24 | 82,6 °C |

- **O Pi decide igual ao notebook:** 24, 25 e 24 alertas, os mesmos do x86.
- O Pi foi ~1,45× mais lento que o Xeon de teste nos atributos e ~2× no LSTM-AE (0,28 ms por inferência por canal).
- Cascata com 5% contra LSTM-AE sempre: 3,20 → 1,40 ms por minuto (2,3× menos). Os atributos são 80% do custo da
  cascata.
- **Temperatura:** 82,6 °C no fim da rodada com LSTM-AE sempre. Logo depois, `vcgencmd get_throttled` = **0xe0000**
  (bits 17, 18 e 19: houve limite de frequência, throttling e limite suave de temperatura desde o boot; os bits 0–3,
  de agora, zerados; sem subtensão). Em repouso, 58,7 °C. **Os números da tabela, sobretudo os de 100%, estão inflados
  pelo calor e não valem como E2.** E2/E3 só com refrigeração, `performance`, Pi recém-ligado (os bits "ocorreu" só
  zeram no boot) e `get_throttled` conferido antes e depois de cada rodada.
- Ordem de grandeza (derivado, só processamento, sem MQTT): 141 µs por mensagem com a cascata → ~7.000 mensagens/s num
  núcleo; 322 µs com LSTM-AE sempre → ~3.100 mensagens/s. O gerador de carga do notebook faz ~3.000 mensagens/s, então
  o E3 consegue saturar o modo "LSTM-AE sempre", mas talvez não a cascata com um gerador só.

### J5. Primeira sessão ao vivo (23/11/2026): simulador no notebook → MQTT → Pi [medido]
- Painel do simulador (perfil 1, semente 1, data 05/01/2026, 17h30, velocidade 60) publicando no Mosquitto do Pi;
  `detector servico` no Pi com o pacote perfil1_s1 (orçamento 5%): ~10 mensagens/s, 1 minuto simulado por segundo,
  CPU do processo 0,4–0,5%, 138 MB de memória, 33–34 °C. Nenhum alerta falso no aquecimento nem em 550 minutos.
- Falhas injetadas pelo painel na geladeira: magnitude 1,41× por 1 min; **magnitude 1,81× por ~23 h; queda por 3 h 41 min**.
  **Nenhuma gerou alerta.** Reproduzi a mesma sessão fora do Pi (mesma semente, mesmas falhas): zero alertas
  também, ou seja, o Pi fez exatamente o que o modelo manda. Os scores mostram por quê:
  - magnitude na geladeira: 100 → 180 W, mas 180 W é a potência normal do degelo (18 min a cada 12 h), então a regra
    fica em 0,73 (limite 1,0); o OCSVM sobe a 0,4–0,5 (escala o canal) e o LSTM-AE não confirma (≤ 0,3; limite 10,5);
  - queda: o OCSVM **satura** em ~1,00 (limite de saída 1,01): o núcleo RBF dá a mesma nota a qualquer ponto muito
    longe dos vetores de suporte, e o treino já tinha um ponto assim; o LSTM-AE chega a ~2,3 (limite 10,5).
- Na mesma reprodução, outras falhas foram pegas: magnitude 1,8× na TV (alerta 1 min depois, regra); fora de horário
  do micro-ondas às 3h (3 min, OCSVM); duração excessiva do ferro (58 min, OCSVM, no medidor geral e no resíduo, não
  na tomada do ferro); TV ligada às 2h (alerta às 3h39, LSTM-AE); magnitude 2× no micro-ondas (no uso, regra).
- **Limitações para o artigo:** (1) magnitude moderada num aparelho cujo pico normal já é alto (geladeira com
  degelo) não passa da regra; (2) o OCSVM também satura longe do treino, em grau menor que o IF; a confirmação fica com
  o LSTM-AE, cujo limite calibrado é alto. Qualquer correção (ex.: regra de domínio "geladeira sem ciclo há X min",
  atributo de consumo por hora) seria escolhida depois do teste → só como trabalho futuro ou análise exploratória.

### J6. Ciclo completo ao vivo funcionando (23/11/2026) [medido]
- Segunda sessão do painel (perfil 1, semente 1, velocidade 60), serviço do Pi religado (`aovivo_teste2.jsonl`). A
  primeira tentativa desta sessão não gerou alerta porque o serviço do Pi estava parado (a reprodução fora do Pi
  mostrou que a magnitude na TV teria dado alerta às 22h11).
- **Fora de horário do micro-ondas**, injetado pelo painel às 05h17 (simulado; ligado até 05h23): alerta às 05h27,
  decidido pelo **OCSVM** no canal do próprio micro-ondas (`t2`, score 1,10). Atraso de 10 min simulados desde o início
  da falha (persistência k = 3 e janela de 15 min); o alerta chegou ao painel 5 s simulados depois de o minuto fechar
  (< 0,1 s real). Do clique no painel até o alerta na tela: ~10 s reais a 60×.
- O simulador grava a injeção e o alerta recebido (com as falhas ativas) em `simulador/registros/aovivo_*.jsonl`: é o
  material do E5.

## K. 23/11/2026 (madrugada) — Bateria noturna automática (Kleber autorizou rodar tudo sem pedir nada)

### K1. Bateria ao vivo pelo painel (E5)
- O Claude acessa o painel do simulador pelo navegador embutido do app (o Pi continua inacessível: rede local
  isolada). Um agendador dentro da página (Web Worker) lê o relógio simulado e injeta falhas pela API do painel,
  todo dia simulado, sempre nos mesmos horários: 02h fora de horário (rodízio de 8 aparelhos), 06h falta de energia
  (dias alternados), 09h30 duração excessiva (6 aparelhos), 13h queda/consumo não explicado/magnitude da geladeira,
  16h30 pico (5 aparelhos, 60 min), 20h magnitude (6 aparelhos, 120 min), 22h30 queda (geladeira/roteador, 180 min).
  Velocidade 120× (1 dia simulado = 12 min reais). O simulador grava injeções, alertas recebidos e o gabarito do dia
  em `simulador/registros/aovivo_*.jsonl`; `python -m detector e5 <registro>` faz a tabela.
- Ressalvas: o detector no Pi usa o pacote perfil1_s1 com orçamento fixo de 5% (mudar exige reiniciar o serviço no
  Pi); falhas sobrepostas no mesmo canal (ex.: duas magnitudes na TV) contam como perdidas se o alerta já estava
  aberto antes, porque o casamento exige um alerta que COMECE na janela da falha.

### K2. Campanha com dados novos (`detector/campanha.py`)
- 15 casas × 13 cenários × 28 dias novos por casa (os dias logo depois do fim do teste de cada semente; nenhum modelo
  viu), falhas sorteadas pelo simulador (~10 por semana), avaliação com as mesmas regras de `avaliacao.py`.
- Conferência do avaliador: passando o teste oficial do perfil 1 e do perfil 2 (semente 1) pela campanha, o F1 sai
  igual ao da cascata oficial (0,519 e 0,292).
- Rodada no ambiente do Claude (2 núcleos x86); os tempos `ms_por_minuto` da campanha são da versão anterior da
  janela móvel (ver K3) e servem só para comparar cenários entre si.

### K3. Atributos ao vivo 2,9× mais rápidos, bit a bit iguais [medido]
- O perfil de execução mostrou o tempo nas janelas móveis (chamadas de numpy em listas de 15–60 números). Troquei por
  Python puro reproduzindo a MESMA ordem de soma do numpy (soma em pares, blocos de 8), desvio com ddof = 1 e mediana.
- Dois dias de calibração do perfil 3 e do perfil 2: atributos tabulares, entrada do LSTM-AE e alarmes **idênticos bit
  a bit** à versão anterior; atributos 8,7 → 3,0 s (perfil 3) e 4,7 → 1,5 s (perfil 2); tempo total 10,9 → 5,2 s e
  5,9 → 2,4 s. 27 testes aprovados. **O Pi ainda está com a versão antiga** (copiar `detector/` de novo antes do E2).

### K4. Ferramenta do E2: `python -m detector custo` (`detector/custo.py`)
- Mede, NO Pi, a latência de UMA inferência (lote 1, 1 thread do onnxruntime) de cada modelo em cada canal, com
  atributos reais de 1 dia do teste de uma casa (limiares lidos do `casa.json`, nada é treinado), 2000 repetições
  depois de 50 de aquecimento: mediana, p95, p99, tamanho do .onnx, memória do processo e o estado do Pi antes e
  depois (governador, frequência, temperatura, `vcgencmd get_throttled`). Saída em JSON.
- Uso no Pi (precisa da pasta da casa em `resultados/baselines_v1/perfilN/semente_S` e dos dados da semente):
  `python -m detector custo --casa baselines_p1s1 --dados semente_1 --saida e2_p1s1.json`
- Teste de sanidade no ambiente do Claude (x86, 2 núcleos OCUPADOS pela campanha, 200 repetições; NÃO é o E2):
  regra 3,7 µs; IF 1202 µs; OCSVM 6,1 µs; AE 6,7 µs; LSTM-AE 60,9 µs por inferência (mediana); .onnx por canal:
  IF 918 KB, OCSVM 9,8 KB, AE 8,0 KB, LSTM-AE 61,5 KB. Observação [medido, a confirmar no Pi]: o IF em ONNX
  (100 árvores, TreeEnsemble) é o modelo MAIS caro por inferência, ~200× o OCSVM; isso reforça a escolha do OCSVM
  como estágio 1 (H7) e conta contra o plano original (IF como filtro).
- Causa do custo do IF [medido]: o grafo ONNX gerado pelo skl2onnx 1.20 tem **2712 nós** (por árvore: TreeEnsemble +
  cálculo do comprimento de caminho com Cast/Mul/Add/Max…; 602 Add, 401 Cast, 401 Mul, 300 Max), contra 7 nós do
  OCSVM, 13 do AE e 54 do LSTM-AE. O custo vem do overhead por nó do onnxruntime com lote de 1, não da floresta em
  si. Trabalho futuro (não muda o resultado do TCC): um único TreeEnsemble com o comprimento de caminho já gravado
  nas folhas reduziria o grafo a poucos nós.
- Pacote pronto para o Pi: `resultados/_transferencia/e2_pi.tar` (81 MB: código atual do detector, modelos e dados de
  perfil1_s1 e perfil3_s1, pacotes ao vivo e `e2.sh`). Passo a passo em `pi/E2_NO_PI.md`. Conferido no notebook
  extraindo o tar numa pasta vazia: `custo` e `reproduzir` rodam (sem torch, sem simulador).
- Referência no notebook (VM do Cowork no i9, sem disputa de CPU; NÃO é o E2), perfil1_s1, mediana por inferência:
  regra 2,9 µs; IF 600 µs; OCSVM 4,8 µs; AE 5,4 µs; LSTM-AE 52 µs. Sistema ao vivo completo (versão otimizada K3,
  b = 5 %): 0,232 ms por minuto de casa (atributos 0,143; estágio 1 0,046; estágio 2 0,026).

### K5. Resultado da campanha (15 casas × 13 cenários × ~28 dias novos = 418 dias por cenário) [medido]
Arquivos: `resultados/campanha_v1/` (tabela_campanha*.csv, resultados/*.json, log.txt; os dados gerados ficam só no
ambiente do Claude, 218 MB, e são refeitos por `python -m detector campanha` — o gerador é determinístico por semente).
Rodada em 175,8 min (2 processos, x86). Métricas somadas nas casas (precisão = detectados/(detectados + alertas
falsos)); "F1 casas" = média do F1 por casa. 423 eventos com aparelho/geral; 99 faltas de energia.

| cenário | revocação | precisão | F1 | FP/dia | F1 casas | escalados | ms/min (x86) |
|---|---|---|---|---|---|---|---|
| limpo, b = 0 (sem LSTM) | 0,426 | 0,416 | **0,421** | 0,61 | 0,444 | 0 % | 2,27 |
| limpo, b = 1 % | 0,357 | 0,392 | 0,374 | 0,56 | 0,401 | 1,5 % | 2,27 |
| **limpo, b = 5 % (padrão)** | 0,376 | 0,390 | **0,383** | 0,60 | 0,411 | 6,0 % | 2,42 |
| limpo, b = 20 % | 0,369 | 0,391 | 0,380 | 0,58 | 0,406 | 20,6 % | 2,85 |
| limpo, b = 100 % | 0,369 | 0,388 | 0,378 | 0,59 | 0,405 | 99,9 % | 4,68 |
| perda de 1 % das mensagens | 0,383 | 0,344 | 0,362 | 0,74 | 0,388 | 6,1 % | 2,27 |
| perda de 5 % | 0,411 | 0,240 | 0,303 | 1,32 | 0,329 | 6,5 % | 2,36 |
| perda de 20 % | 0,513 | 0,127 | 0,204 | 3,57 | 0,246 | 8,1 % | 2,38 |
| 1 medidor mudo 6 h por semana | 0,378 | 0,376 | 0,377 | 0,63 | 0,406 | 6,1 % | 2,26 |
| 5 % fora de ordem | 0,376 | 0,389 | 0,382 | 0,60 | 0,411 | 6,0 % | 2,28 |
| 5 % duplicadas | 0,376 | 0,390 | 0,383 | 0,60 | 0,411 | 6,0 % | 2,29 |
| deriva +5 % em todos os medidores | 0,449 | 0,061 | 0,107 | 7,00 | 0,178 | 8,1 % | 2,37 |
| deriva +5 % só no geral | 0,421 | 0,395 | 0,407 | 0,65 | 0,438 | 7,0 % | 2,39 |

Faltas de energia: 99/99 reconhecidas em todos os cenários, 0 silêncios sem falta, ≤ 1 alerta durante falta.

Leituras:
1. **Generalização**: com o orçamento padrão, F1 médio por casa 0,484 no teste oficial (H/I) → 0,411 em 28 dias novos.
   Queda esperada (o teste é curto e o limiar foi escolhido em calibração de poucos dias), mas o sistema continua
   útil: 0,6 alerta falso por dia somando todos os canais da casa.
2. **O LSTM-AE não ajuda em dados novos**: b = 0 (só OCSVM + regra) teve o MAIOR F1 (0,421 contra 0,383 de b = 5 %),
   e escalar 100 % não muda nada (0,378). O mesmo já aparecia no teste oficial (F1 médio 0,496 com b = 0 e 0,484 com
   b = 5 %). Motivo [medido no pacote perfil3_s5]: em b > 0 a calibração escolheu θ2 ≈ 11 (LSTM quase nunca confirma)
   e θ_saída = 1,0085 com k = 1; em b = 0 escolheu θ_saída = 0,9991 com k = 5 — é a escolha de (θ_saída, k), não o
   LSTM, que muda o resultado. Alertas por estágio em b = 5 %: OCSVM 191, regra 152, LSTM 127 (de 470).
   **Implicação para o TCC: o ganho da cascata é de CUSTO, não de qualidade**: com b = 5 % ela custa 2,42 ms/min
   contra 4,68 ms/min com o LSTM em todo minuto (−48 %), com a mesma qualidade. Em qualidade, o estágio 1 sozinho é
   tão bom quanto ou melhor.
3. **Robustez**: fora de ordem e duplicadas não mudam nada (descartadas/inócuas por construção); medidor mudo quase
   nada; deriva só no geral quase nada (o resíduo absorve). **Perda de mensagens e deriva em todos os medidores são o
   ponto fraco, e o culpado é a REGRA**, não os modelos: alertas por estágio em perda de 20 %: regra 1303, OCSVM 367,
   LSTM 151; em deriva de todos: regra 2863.
   - Mecanismo da perda [medido, perfil3_s1, canal r9 com mensagem a cada 60 s]: o valor de potência é instantâneo e
     mantido até a próxima mensagem; quando uma mensagem se perde, um pico curto fica mantido por um minuto inteiro e
     a média do minuto (p_med) chega ao pico bruto: máximo de p_med 1151 W → 2950 W (pico bruto da mensagem 2956 W).
     Como a regra compara `p_max15` com o máximo do treino, dispara. No resíduo acontece o mesmo pelo lado dos
     medidores próprios.
   - Mecanismo da deriva: o limite da regra fica perto do máximo do treino; +5 % em tudo passa do limite sempre que
     o aparelho trabalha no pico (perfil 3: 12 FP/dia).
   - Correções possíveis (trabalho futuro, NÃO aplicadas — o teste já foi usado): regra sobre `e_pot` (energia, imune à
     perda porque o contador integra) ou sobre a mediana; margem de tolerância na regra; recalibração periódica.
4. **Por tipo (b = 5 %)**: magnitude 0,75 (atraso mediano 1,4 min); duração excessiva 0,51 (13,6 min); fora de horário
   0,29 (7,9 min); pico 0,30 (5,4 min); queda 0,31 (55,8 min); consumo não explicado 0,27 (191,6 min). Aparelhos mais
   difíceis: ventiladores, purificador, bombas d'água (baixa potência ou uso irregular).
5. **Custo**: as casas do perfil 3 (31 canais) custam ~4 ms/min, as do perfil 1 (6 canais) ~0,7 ms/min (x86, versão
   antiga da janela móvel); o custo cresce com o número de canais e o escalonamento quase dobra o custo em b = 100 %.

### K6. Variantes da cascata — EXPLORATÓRIO, avaliadas no teste DEPOIS de ele ter sido usado [medido]
Mesmos modelos oficiais, mesma escolha de τ/θ/k na calibração; só muda a arquitetura. Saída em
`resultados/cascata_exploratoria/<variante>/` (`python -m detector cascata --filtro/--sem-regra/--confirmador`).
Média das 15 casas no teste (F1 por casa):

| variante | b | F1 | revocação | precisão | FP/dia | AUC-PR evento |
|---|---|---|---|---|---|---|
| **oficial: OCSVM + regra → LSTM-AE** | 0 | 0,496 | 0,558 | 0,517 | 0,46 | 0,294 |
| | 5 % | 0,484 | 0,532 | 0,497 | 0,45 | 0,372 |
| | 100 % | 0,484 | 0,517 | 0,506 | 0,42 | 0,372 |
| OCSVM sem regra → LSTM-AE | 0 | 0,434 | 0,454 | 0,510 | 0,49 | 0,231 |
| | 5 % | 0,433 | 0,394 | 0,538 | 0,36 | 0,320 |
| plano original: IF → LSTM-AE | 0 | 0,102 | 0,091 | 0,164 | 0,52 | 0,026 |
| | 5 % | 0,329 | 0,268 | 0,547 | 0,24 | 0,274 |
| | 100 % | 0,338 | 0,329 | 0,446 | 0,46 | 0,311 |
| IF + regra → LSTM-AE | 0 | 0,296 | 0,283 | 0,425 | 0,39 | 0,123 |
| | 5 % | 0,448 | 0,431 | 0,561 | 0,30 | 0,316 |
| OCSVM + regra → AE | 0 | 0,496 | 0,558 | 0,517 | 0,46 | 0,294 |
| | 5 % | **0,540** | 0,606 | 0,541 | 0,53 | **0,441** |
| | 100 % | 0,533 | 0,581 | 0,549 | 0,43 | 0,434 |

Custo do modelo por janela (x86, em lote, mediana das 15 casas, `onnx_us_por_janela`): regra 0,04 µs; AE 0,35 µs;
OCSVM 1,77 µs; IF 32,9 µs; LSTM-AE 57,7 µs. Estágio 1 oficial = 1,81 µs/min/canal (0,031 × LSTM); com b = 5 %:
oficial ≈ 5,0 µs (0,083 × LSTM), com o AE de confirmador ≈ 1,83 µs (0,032 × LSTM).

Leituras (exploratórias — não substituem o resultado oficial, porque o teste já tinha sido visto):
1. **A escolha do estágio 1 (H7) se confirma com folga**: o plano original (IF → LSTM-AE) fica em F1 0,33 com b = 5 %
   contra 0,48 da cascata oficial, e o IF custa ~19× o OCSVM por janela. IF sozinho como estágio 1 (b = 0) é quase
   inútil (F1 0,10): ele satura (ver H/notas do IF).
2. **A regra vale ~0,05 de F1** (0,484 → 0,433 sem ela), principalmente em revocação (0,53 → 0,39).
3. **O AE como confirmador foi melhor que o LSTM-AE** no teste (0,540 × 0,484) e ~160× mais barato por janela. Como
   isso foi visto depois do teste, a conclusão honesta é "hipótese a confirmar"; a confirmação limpa é nos dados
   novos da campanha (K7).

### K7. Variantes da cascata nos DADOS NOVOS da campanha (confirmação limpa) [medido]
- Como: `datasets_campanha/v1/perfilN/semente_S` com treino e calibração oficiais (links) e, como "teste", os 28
  dias novos da campanha (mesmos de K5); gabarito = linhas oficiais + falhas novas (prefixo N). Parâmetros escolhidos
  na calibração oficial, como sempre. Nenhum modelo nem escolha viu esses dias. Script de montagem em
  `resultados/cascata_campanha/montar_ds_campanha.py`; saída em `resultados/cascata_campanha/<variante>/`.
- Conferência: a cascata oficial offline nesses dados reproduz a campanha ao vivo (perfil3_s5, b = 5 %: revocação
  0,433 nos dois, F1 0,306 × 0,310; b = 0: 0,700 nos dois, F1 0,472 × 0,477; média das casas b = 5 %: 0,408 × 0,411).
  A pequena diferença vem do 1º dia, que o offline avalia e a campanha usa como aquecimento.

| variante (dados novos) | b | F1 | revocação | precisão | FP/dia | AUC-PR evento |
|---|---|---|---|---|---|---|
| oficial: OCSVM + regra → LSTM-AE | 0 | 0,434 | 0,424 | 0,556 | 0,63 | 0,229 |
| | 5 % | 0,408 | 0,377 | 0,532 | 0,60 | 0,323 |
| OCSVM + regra → AE | 5 % | **0,450** | 0,456 | 0,549 | 0,87 | **0,381** |
| OCSVM sem regra → LSTM-AE | 5 % | 0,379 | 0,338 | 0,574 | 0,66 | 0,318 |
| IF + regra → LSTM-AE | 5 % | 0,322 | 0,273 | 0,552 | 0,42 | 0,257 |
| plano original: IF → LSTM-AE | 5 % | 0,280 | 0,224 | 0,534 | 0,48 | 0,230 |

Comparação pareada por casa contra a oficial com b = 5 % (Δ F1; IC 95 % por bootstrap das 15 casas; Wilcoxon):
- oficial b = 0: +0,026 [−0,021; +0,078], 5 melhores/5 iguais/5 piores, p = 0,58 → **sem diferença**.
- OCSVM + regra → AE: +0,042 [+0,009; +0,081], 10/1/4, p = 0,041.
- OCSVM sem regra: −0,029 [−0,070; +0,013], 3/3/9, p = 0,16.
- IF + regra: −0,086 [−0,171; +0,003], 4/0/11, p = 0,041.
- plano original (IF → LSTM-AE): −0,128 [−0,211; −0,044], 2/1/12, p = 0,016.
- AE (b = 5 %) contra o estágio 1 sozinho (b = 0): +0,017, 8/1/6, p = 0,81 (no teste: +0,045, p = 0,17).
No teste (K6), as mesmas comparações: AE +0,056 [−0,007; +0,122] p = 0,13; plano original
−0,155 [−0,264; −0,037] p = 0,030.

Conclusões que podem ir para o TCC:
1. **OCSVM + regra no estágio 1 é a escolha certa**, agora com evidência em dados que ninguém viu: o plano original
   (IF) perde 0,13 de F1 e em 12 de 15 casas. (Os p-valores não têm correção para comparações múltiplas; com 5
   comparações, Bonferroni exigiria p < 0,01 — só o efeito do IF fica perto disso. Reportar como tendência forte.)
2. **O confirmador quase não muda a qualidade**: nem o LSTM-AE nem o AE melhoram de forma clara o estágio 1
   sozinho (b = 0). O AE ficou melhor que o LSTM-AE (+0,04 F1, 10 de 15 casas), mas ao custo de mais alertas falsos
   (0,87 × 0,60 por dia). O que a cascata entrega com certeza é **custo**: o modelo caro roda em ~6 % dos minutos.
3. Recomendação para a escrita: manter a cascata oficial como resultado principal (é o que foi decidido antes do
   teste) e apresentar K6/K7 como análise de sensibilidade da arquitetura. Trocar o confirmador para o AE é uma
   decisão do Kleber/orientador; se trocar, deve ser declarado como decisão posterior ao teste.

### K8. E5 — bateria ao vivo no Pi pela noite (análise até o último dia simulado concluído) [medido]
- Registro `simulador/registros/aovivo_casa_perfil1_20261123_020605.jsonl`; contado desde 2026-01-06 05:00 (hora
  simulada em que o serviço do Pi foi religado); 29,7 dias simulados a 120× (~6 h reais); pacote perfil1_s1, b = 5 %.
  Resultados em `resultados/e5_bateria_noturna/`.
- 158 falhas injetadas pelo painel; **53 detectadas (revocação 0,34), 1 alerta falso em 29,7 dias (0,03 por dia),
  precisão 0,98**; 14 faltas de energia, nenhum alerta falso durante elas; atraso mediano 35 min simulados;
  **latência do sistema (`latencia_sistema_mediana_s` do `detector e5`) mediana 0,11 s real**.
- Onde o sistema funciona e onde não [medido]: falhas em aparelhos COM medidor próprio (geladeira, micro-ondas, TV,
  ferro): 47 de 92 (0,51); SEM medidor próprio (máquina de lavar, chuveiro, air fryer, cafeteira, liquidificador,
  roteador, ventilador) e consumo não explicado: 6 de 66 (0,09). Por tipo: queda 16/39 (geladeira 16/25; roteador
  0/14 — aparelho sem medidor próprio e de potência baixa perto do resto da casa), duração excessiva 13/29, magnitude 9/22, pico 9/29, fora de horário 6/29,
  consumo não explicado 0/10. Destaques: micro-ondas pico 6/6 e fora de horário 4/4; ferro e air fryer duração
  excessiva 5/5 cada.
- Quem decidiu: OCSVM 37, regra 15, LSTM-AE 1 dos 53 detectados; 41 dos 53 apontaram o canal certo.
- Ressalvas: a bateria injeta ~5 falhas por dia simulado, bem mais que o uso real, e várias se sobrepõem no mesmo
  aparelho (contadas como perdidas quando o alerta já estava aberto); por isso a revocação do E5 é um piso. O E5
  mede o sistema de ponta a ponta (MQTT, Pi, painel), não a qualidade do modelo, que é medida em H/I/K5/K7.

### K9. E2 no Raspberry Pi 5 — medida válida (23/11/2026, rodada pelo Kleber) [medido]
Condições: Pi recém-ligado, **com refrigeração**, governador `performance` (2400 MHz conferidos por
`vcgencmd measure_clock arm`), nenhum outro detector rodando, **`throttled=0x0` em todos os pontos**; temperatura
36–46 °C (máx. 46,3 °C com o LSTM-AE em 100 %). Comando `bash e2.sh` (`pi/e2.sh`). Pastas (copiadas para
`resultados/`): `e2_20261123_0912` (código novo) e `e2_20261123_0833` (código antigo, ver abaixo). Ambiente no Pi:
Python 3.11.2, numpy 2.4.6, pandas 3.1.1, scikit-learn 1.9.1, onnxruntime 1.32.0, 4 núcleos, 4 GB.

**1) Latência de UMA inferência (lote 1, 1 thread, 2000 repetições; mediana / p99, em µs):**

| modelo | perfil1_s1 (6 canais) | perfil3_s1 (32 canais) | .onnx por canal | Pi ÷ notebook* |
|---|---|---|---|---|
| regra | 11,9 / 12,8 | 10,9 / 12,3 | 0,1 KB | 4,1× |
| IF | **2179 / 2373** | **2350 / 2550** | 918 / 846 KB | 3,6× |
| OCSVM | 19,7 / 23,6 | 19,5 / 23,9 | 9,8 / 10,7 KB | 4,1× |
| AE | 19,7 / 23,1 | 20,6 / 24,3 | 8,0 / 7,9 KB | 3,6× |
| LSTM-AE | 199,9 / 213,7 | 196,7 / 211,6 | 61,5 / 61,4 KB | 3,8× |

*notebook = VM do Cowork no i9-12900KF, mesma ferramenta, perfil1_s1 (K4). A regra (um Gather) mede o custo fixo de
uma chamada do ONNX Runtime no Pi: ~11 µs; OCSVM e AE custam quase só isso. Cauda curta (p99 ≤ 1,2× a mediana).
O IF custa 110× o OCSVM e 11× o LSTM-AE por inferência (grafo de 2712 nós, K4).

**2) Sistema completo ao vivo (`reproduzir`, partição de teste inteira = 36.000 minutos; ms por minuto da casa):**

| casa | b = 0 (só estágio 1) | b = 5 % (padrão) | b = 100 % (LSTM-AE sempre) | corte da cascata (5 % × 100 %) |
|---|---|---|---|---|
| perfil1_s1, 6 canais | 0,475 | **0,563** | 2,231 | **−75 %** |
| perfil3_s1, 32 canais | 2,461 | **3,217** | 13,163 | **−76 %** |

Partes com b = 5 % (ms/min): perfil 1 — atributos 0,291, estágio 1 0,159, estágio 2 0,078; perfil 3 — atributos
1,563, estágio 1 0,955, estágio 2 0,522. Escalados 5,0 % e 5,6 %. Alertas iguais aos do notebook (24/25/24 e 16/16/16).
Por mensagem com b = 5 %: 57 µs (perfil 1) e 70 µs (perfil 3).

**3) Antes × depois da otimização dos atributos (K3), no mesmo Pi, nas mesmas condições.** A 1ª rodada
(`e2_20261123_0833`) usou sem querer o código ANTIGO: a cópia antiga estava em `~/tcc-pi/detector/*.py` e o Python
achou essa pasta antes da nova (`~/tcc-pi/detector/detector/`). Os .py antigos foram guardados em
`~/tcc-pi/_detector_antigo/`. O `custo` não rodou nessa vez (o comando não existia na versão antiga).

| casa, b | atributos antigo → novo | total antigo → novo (ms/min) |
|---|---|---|
| perfil1, 0 % | 1,124 → 0,289 (3,9×) | 1,319 → 0,475 |
| perfil1, 5 % | 1,125 → 0,291 | 1,406 → 0,563 (2,5×) |
| perfil1, 100 % | 1,191 → 0,316 | 3,154 → 2,231 |
| perfil3, 0 % | 5,756 → 1,493 (3,9×) | 6,876 → 2,461 |
| perfil3, 5 % | 5,843 → 1,563 | 7,658 → 3,217 (2,4×) |
| perfil3, 100 % | 6,137 → 1,750 | 17,746 → 13,163 |

Mesmos alertas nas duas versões (24/25/24 e 16/16) — confirma no Pi a igualdade de K3. Com o código antigo a cascata
cortava 55 % do custo no perfil 1 (3,15 → 1,41) e 57 % no perfil 3 (17,75 → 7,66); com o novo, 75 % e 76 %: **sem a otimização, os atributos escondiam o
ganho da cascata.**

**4) Leitura para o artigo:**
- Tempo real com folga enorme: a casa mais pesada (32 canais) gasta 3,2 ms de CPU por minuto de casa com o padrão
  de 5 % (0,005 % de um núcleo). Estimativa [derivada, a confirmar no E3]: um núcleo processaria ~14 mil mensagens
  por segundo no detector (70 µs por mensagem), bem acima dos ~3.000 msg/s que o gerador do notebook produz — o
  gargalo do E3/E4 deve ser o notebook/rede/MQTT, não o detector.
- O custo do LSTM-AE (200 µs × canais escalados) é o que a cascata corta; o estágio 1 (OCSVM 20 µs + regra 11 µs por
  canal) é praticamente o custo fixo de chamar o ONNX Runtime. Juntar a regra e o OCSVM num grafo só, ou calcular a
  regra em Python, economizaria ~1/3 do estágio 1 (trabalho futuro, pequeno).
- Memória do processo de medida: 291 MB (perfil 1) e 516 MB (perfil 3), incluindo pandas e os dados de teste
  carregados; o serviço ao vivo usou 138 MB (J). Cabe com folga nos 4 GB.

### K10. Protocolo do E3/E4 (teste de carga) — preparado em 23/11/2026, antes de rodar
- **Rede: Wi-Fi** (decisão do Kleber; o cabo disponível está com defeito). Registrar no artigo como condição do teste.
- **Gerador (PC):** `pi/e3_pc.py` com o venv do simulador. Casas virtuais perfil3 (31 canais medidos; 32 com o
  resíduo), uma mensagem por canal a cada 10 s (≈ 3,1 msg/s por casa), 8 processos geradores. Rampa (min:casas):
  0:50, 2:100, 4:200, 6:400, 8:600, 10:800, 12:1000, 14:1300, 16:1600, 18:2000, 20:2500, 22:3000 (até ~9.300 msg/s),
  24 min por rodada. Rodadas: E3 com orçamento fixo 100 %, 5 % e 0; E4 começando em 100 % com o controlador de
  carga ligado (atraso p95 tolerado 2 s). Entre rodadas o roteiro manda `reset` ao detector (descarta as casas).
- **Detector (Pi):** `pi/e3_pi.sh` → `python -m detector servico --carga pacotes/perfil3_s1` (modo de carga): uma
  CasaAoVivo por casa virtual, sessões ONNX compartilhadas; comandos do roteiro pelo tópico
  `casa/sistema/detector/comando`; estado agregado a cada 10 s (msg/s, casas, canais, atraso p50/p95/máx, orçamento,
  % escalado, ms por minuto-casa, CPU, memória, temperatura) em `servico.jsonl`. Coleta paralela: `top` do Mosquitto,
  `vmstat` e temperatura/throttling a cada 30 s.
- **Atraso** = hora do Pi ao processar − `ts` do envio (hora do PC). Os relógios não são sincronizados entre si:
  a análise e o controlador usam o atraso ACIMA da linha de base (menor p50 da rodada).
- **Casas "aquecidas"** [decisão do Claude]: no modo de carga cada casa nasce com a janela de 60 min do LSTM-AE já
  cheia (zeros), senão o estágio 2 só rodaria depois de 1 h de casa e as rodadas de 24 min nunca pagariam o custo do
  LSTM-AE. Só para o E3/E4; os alertas dessas rodadas não valem como detecção (dados reenviados fora de alinhamento
  entre canais). Desligável com `--sem-aquecer`.
- **Critério de saturação** (fixado antes de rodar): um degrau da rampa é sustentado se, depois de 20 s de
  acomodação, o atraso p95 acima da base fica ≤ 2 s e o detector processa ≥ 99 % das mensagens enviadas.
  Capacidade = maior degrau sustentado (em casas, canais e msg/s), por orçamento.
- **Correção no simulador achada no ensaio:** o `Publicador` usava sempre `client_id="casasim"`; dois clientes com o
  mesmo id se derrubam no broker e METADE das mensagens se perdia com 2 geradores. Agora cada gerador tem id
  próprio (`casasim-carga-<prefixo>-<pid>`) e não assina tópicos. O painel continua com "casasim". Sessões
  anteriores tinham um publicador só, então nada do que foi medido antes é afetado.
- Ensaio no ambiente do Claude (x86, 2 núcleos, Mosquitto local): 120 casas a 1 s (3.720 msg/s) com o detector em
  15 % de um núcleo; atraso p95 0,3 s no minuto em que o LSTM-AE roda para todos (b = 100 %). 28 testes do detector
  aprovados (novo: modo de carga, controlador e comandos); simulador 31 + 1 que depende do fastapi (ausente no
  ambiente do Claude, não relacionado).

### K11. E3/E4 — 1ª rodada no Pi (23/11/2026, 10:22–12:01, Wi-Fi) [medido]
Pasta `resultados/e3_20261123_1012` (Pi) + `simulador/registros/e3` (PC); análise `python -m detector e3 ...` →
`analise/e3_degraus.csv`, `e3_resumo.json`, `e4_trajetoria.csv`. Wi-Fi 433 Mb/s, sinal −33 dBm. Governador: o Pi
tinha reiniciado e voltou a `ondemand`; foi posto em `performance` antes da 1ª rodada (o `estado_antes.txt` foi
gravado antes da troca). `throttled=0x0` nas 307 leituras; temperatura máx. 56 °C. Cada rodada: 5,04 milhões de
mensagens enviadas, rampa de 50 a 3.000 casas perfil3 (até 96 mil canais, 9.300 msg/s).

**Pior atraso de decisão acima da base (s) por degrau** (base = menor p50 da rodada, ~0,72 s de diferença de relógio):

| casas (canais) | 50 (1.600) | 200 (6.400) | 400 | 800 | 1.000 (32.000) | 1.600 | 2.000 | 3.000 (96.000) |
|---|---|---|---|---|---|---|---|---|
| b = 100 % | 0,13 | 1,58 | 3,9 | 9,1 | 11,7 | 19,4 | 25,3 | 37,5 |
| b = 5 % (escalou 64 %, ver abaixo) | 0,11 | 1,17 | 2,7 | 6,2 | 8,3 | 13,9 | 18,6 | 27,2 |
| b = 0 (só estágio 1) | 0,04 | 0,08 | 0,33 | 1,10 | 1,61 | 3,99 | 4,30 | 7,08 |
| E4 (controlador, começa em 100 %) | 0,23 | 1,78 | 3,8 | 8,8 | 11,0 | 10,8 | 12,2 | 16,2 |

CPU por minuto de casa (atributos + estágios, medido no serviço): b = 100 % 12,0–12,8 ms; b = 5 % 8,4–9,2 ms;
b = 0 2,0–2,4 ms (batem com o E2: 13,2 e 2,5 ms). Fora da virada do minuto, cada mensagem custa ~40 µs no
detector (MQTT + JSON + atributos): 9.300 msg/s = 37 % de um núcleo. Mosquitto: ≤ 6 % de um núcleo a 9.300 msg/s.
Memória do detector: ~0,6 MB por casa (1,95 GB com 3.000 casas).

**Critério fixado antes (p95 de toda janela ≤ 2 s acima da base e ≥ 99 % processado):** b = 100 % → 100 casas
(3.200 canais); b = 5 % → 200 (6.400); b = 0 → 1.000 (32.000); E4 → 200.

Achados (o que a rodada ensinou):
1. **O atraso vem da virada do minuto, não da vazão.** Todas as casas fecham o minuto juntas (relógio comum) e o
   detector processa o minuto de todas de uma vez: o atraso de decisão ≈ nº de casas × ms por minuto de casa
   (3.000 × 12,5 ms = 37,5 s; 3.000 × 2,4 ms = 7,2 s). Por isso a cascata (menos LSTM-AE) reduz diretamente o
   atraso de alerta. Entre as viradas, o atraso volta à base (~0,005 s acima).
2. **Mensagens PERDIDAS (não só atrasadas)** quando a virada fica longa: processado/enviado na rodada inteira =
   76,2 % (b = 100 %), 83,6 % (b = 5 %), 99,2 % (b = 0), 95,2 % (E4). Causa [hipótese consistente com os números, a
   confirmar no log do Mosquitto]: o detector processa dentro da thread de rede do MQTT; durante a virada ninguém lê
   o socket, a fila do Mosquitto para esse cliente + buffers TCP enchem (a perda aparece quando o acúmulo passa de
   ~40–60 mil mensagens) e o Mosquitto descarta QoS 0. **Correção: fila interna** (a thread de rede só enfileira;
   outra thread processa).
3. **Com b = 5 % o detector escalou 64 % dos minutos-canal (não 5 %)**: o gerador reenvia cada canal com fase
   aleatória e a 10 s por mensagem (o dataset tem 10–60 s), os canais da casa ficam desalinhados (resíduo sem
   sentido) e o OCSVM passa de τ quase sempre. Os números de b = 5 % são de "dados estranhos", não do uso normal.
   **Correção: modo fiel do gerador** (cada casa reenvia o dataset na ordem e com os intervalos originais).
4. **E4 — o controlador funcionou, mas oscila**: desceu de 100 % para 50 % com 400 casas, 10–20 % com 800, 1–5 %
   com 1.000–1.300 e ficou entre 0 e 1 % de 1.600 casas em diante; com 3.000 casas o pior atraso foi 16,2 s (contra
   37,5 s fixo em 100 %) e a perda 4,8 % (contra 24 %). Oscila porque olha janelas de 10 s e o atraso só aparece
   na janela da virada: sobe de novo depois de 3 janelas calmas. **Correção: olhar o pior atraso do último minuto.**
5. **Parada do serviço travou** (o sinal chegou, mas ficou preso ao fechar o MQTT; foi preciso `kill -9`; os
   registros estavam completos). **Correção: gravar a linha final antes de fechar o MQTT e encerrar na hora no 2º
   sinal.**
6. Memória (~0,6 MB por casa, por causa da janela do LSTM-AE guardada como 60 vetores numpy pequenos por canal)
   limita a ~5.000 casas perfil3 nos 4 GB; trabalho futuro: janela em vetor circular (~85 kB por casa).

Estes números ficam como a 1ª rodada (com os defeitos acima declarados). A 2ª rodada, com as 4 correções, é a que
deve medir a capacidade do sistema em uso normal.

### K12. E3/E4 — protocolo da 2ª rodada (fixado em 23/11/2026, antes de rodar)
Correções de K11, todas testadas (28 testes do detector; ensaio ponta a ponta com Mosquitto no ambiente do Claude):
1. **Fila interna no serviço**: a thread de rede do MQTT só enfileira; uma thread de trabalho processa. O atraso é
   medido no processamento (inclui a espera na fila); o tamanho da fila vai para o registro (`fila`).
2. **Controlador v2**: olha o pior atraso do último minuto (6 janelas); desce um nível se passou do limite; sobe um
   nível depois de 3 minutos com o pior atraso < metade do limite; depois de mudar, espera 1 minuto.
3. **Parada**: grava a linha final antes de fechar o MQTT; 2º sinal encerra na hora.
4. **Gerador fiel** (`casasim carga --fiel`, `GeradorFiel`): cada casa virtual reenvia o teste do perfil3_s1 na ordem
   e com os intervalos originais (canais alinhados), a partir de um ponto sorteado; ~0,77 msg/s por casa.
- **Casa nova escala muito** [medido offline, perfil3_s1, 3 pontos de partida, janelas de 10 min]: nos primeiros
  ~30 min de vida 34–44 % dos minutos-canal escalam (atributos de 15–60 min ainda incompletos); depois cai para
  3–16 % conforme a atividade (média do teste inteiro: 5,6 %, E2). Por isso a 2ª rodada MANTÉM a carga.
- **Rampa**: 1.000 → 2.000 → 3.000 → 4.000 casas (2 min cada) e 4.000 casas (128 mil canais, ~3.100 msg/s) mantidas
  até 40 min; "regime" = últimos 15 min. Rodadas: E3f_b1, E3f_b005, E3f_b0 (fixos) e E4f_ctrl (começa em 100 %,
  **limite de 30 s** de atraso: a 1ª rodada mostrou que o atraso de alerta é dominado pela virada do minuto e
  cresce com o nº de casas; 2 s só caberia em poucas centenas de casas perfil3, e o atraso de DETECÇÃO mediano do
  sistema já é de minutos (E5: 35 min simulados), então 30 s de atraso de processamento não muda o uso).
- **Previsão** feita antes [derivada de E2 e K11: custo por minuto de casa = 46 mensagens × ~42 µs + custo da
  cascata]: 4.000 casas com b = 100 % ≈ 4.000 × (1,9 + 13,2) ms ≈ 60 s de CPU por minuto → **no limite de um núcleo**
  (deve acumular fila); b = 5 % (regime) ≈ 4.000 × 5,1 ms ≈ 20 s/min e atraso de virada ≈ 13 s; b = 0 ≈ 17 s/min e
  ≈ 10 s.
- **Critério**: sustentado no regime se processado ≥ 99 % do enviado e a fila não cresce (fila no fim − início do
  regime ≤ 1.000); "atende 30 s" se, além disso, o pior atraso do regime ≤ 30 s.
- **Causa da perda da 1ª rodada CONFIRMADA** no log do Mosquitto do Pi (`/var/log/mosquitto/mosquitto.log`):
  `1795441031: Outgoing messages are being dropped for client detector-1795439552.` (≈ 15 min depois do início da
  rodada b = 100 %, quando a rampa passou de 1.000 casas). O Mosquitto avisa só na 1ª vez.
- **Versão curta (pedido do Kleber, 2 h 50 min era muito):** 4.000 casas desde o início (a rampa já foi medida na 1ª
  rodada); E3f_b1 12 min e E3f_b0 8 min (o custo desses dois não depende da "idade" da casa), E3f_b005 e E4f_ctrl
  35 min (regime = últimos 15 min, casas com 20–35 min de vida — ainda um pouco acima do regime de casas velhas,
  ver a medida offline acima). Total ~1 h 35 min.
- **Versão final escolhida pelo Kleber (~1 h 10 min):** E3f_b1 8 min, E3f_b005 30 min, E4f_ctrl 30 min; E3f_b0 fora
  (b = 0 já validado na 1ª rodada: 2,0–2,4 ms por minuto de casa, igual ao E2). Regime = últimos 15 min (casas com
  15–30 min de vida) e também os últimos 5 min (25–30 min de vida); ambos ainda acima do regime de casas velhas.

### K13. E3/E4 — 2ª rodada no Pi (23/11/2026, 13:35–14:45, Wi-Fi −28 dBm, gerador fiel) [medido]
Pasta `resultados/e3_20261123_1331` (+ `analise/`) e `simulador/registros/e3_fiel`. 4.000 casas perfil3 desde o
início (128 mil canais, ~3.080 msg/s, cadência original). `throttled=0x0` o tempo todo; temperatura máx. 54,9 °C;
memória do detector até 3,35 GB (sem uso de swap). Previsões de K12 entre colchetes.

| rodada | CPU detector (média) | processado | fila máx. | pior atraso acima da base | % escalado | ms por min-casa |
|---|---|---|---|---|---|---|
| E3f b = 100 % (8 min) | 98 % | 97,8 %, fila crescendo (+31 mil) | 140 mil | 51,5 s e subindo | 100 | 12,9 |
| E3f b = 5 % (30 min) | 68–72 % | 99,4 % (regime ≥ 100 %) | 88 mil | 28,5 s (subiu de 11 para 28 s) | 38 | 7,4–7,9 |
| E4f controlador (30 min) | 64 % (regime 54 %) | 100 % | 150 mil | 49,9 s nos picos; 7–11 s fora deles | 34 (regime 16) | 6,6 (regime 5,1) |

1. **b = 100 % não sustenta 4.000 casas** [previsto: ~60 s de CPU por minuto, no limite]: CPU 98 %, fila crescendo,
   atraso subindo sem parar. **b = 5 % sustenta** (fila esvazia entre as viradas; processa tudo) com pior atraso
   28,5 s (< 30 s) — mesmo com casas "jovens" escalando 38 % (não os 5 % de casas velhas).
2. **Casas jovens escalam muito** [confirmado; offline: 34–40 % nos primeiros 30 min, igual ao medido]. O pior atraso
   do b = 5 % subiu de 11 s para 28 s ao longo dos 30 min porque as janelas dos atributos (15/60 min) vão enchendo e
   o custo dos atributos cresce até a casa completar 1 h. Projeção para casas em regime [derivada de E2: 5,6 %
   escalado, 3,2 ms por min-casa + ~1,9 ms de mensagens]: virada ≈ 4.000 × 3,2 ms ≈ 13 s e CPU ≈ 34 %.
3. **Pela vazão, 1 núcleo do Pi atende ~4.000 casas perfil3 (128 mil canais) com a cascata a 5 % e não atende com o
   LSTM-AE sempre ligado** — o ganho de capacidade da cascata medido no Pi. A memória (3,35 GB de 4) é o próximo
   limite (K11, item 6).
4. **E4 — achado de projeto: a memória da vigilância atrasava o controlador.** O controlador desceu de 100 % a 0 em
   8 min (um nível por minuto), mas o % escalado ficou em ~91 % (29 de 32 canais) em todos os níveis de 20 % a 1 %:
   um canal que disparou com o τ baixo de 50 % ficava em vigilância por 30 min (V) mesmo depois de o τ subir. Ao
   subir de 0 para 1 %, essa vigilância antiga voltava a valer e o custo pulava de 0 para ~91 % → atraso de 47–50 s
   → descia de novo (oscilou 0 ↔ 1 % a cada ~5 min). Reproduzido offline (`sequência do E4`: ~90 % no 1 %).
   **Correções (29 testes):** (a) `definir_orcamento` zera a vigilância quando o τ sobe (offline, a mesma sequência
   passa a escalar 2,5–3,8 %); (b) o controlador dobra o tempo calmo exigido para subir (3 → 6 → 12 min) quando uma
   subida é desfeita em até 3 min. Esta rodada do E4 fica registrada como a do defeito; refazer o E4 (30 min).

### K14. E4 refeito com as correções (23/11/2026, 15:54–16:24) [medido]
Pasta `resultados/e3_20261123_1552` (+ `analise/`) e `simulador/registros/e4_fiel_v2`. Mesmas condições da K13
(4.000 casas perfil3 fiéis, ~3.080 msg/s, limite de 30 s, começa em 100 %). `throttled=0x0`; máx. 52,7 °C; 3,3 GB.
- **O controlador convergiu e não oscilou**: 100 % (min 0–1) → 50 % (min 2) → 20 % (min 3) → **10 % do minuto 4 ao
  fim** (26 min estável). Escalados: 100 % → ~91 % (50 % e 20 %, τ ainda baixo para casas jovens) → **33–36 % em
  10 %**. Pior atraso por minuto em 10 %: 21,5–29,4 s (sempre < 30 s); fora das viradas, p95 mediana 12–15 s.
- Processado 100,3 % na rodada (a fila que acumulou nos minutos de 100 % foi esvaziada); fila no regime sem
  crescimento (−10 mil); CPU média 71 % (regime 72,5 %).
- O pior atraso foi subindo devagar em 10 % (21,5 → 29,4 s) porque o custo dos atributos cresce enquanto as janelas
  das casas jovens enchem (K13, item 2); se passasse de 30 s, o controlador desceria para 5 %.
- **Comparação com a 1ª tentativa (K13, com o defeito):** antes, oscilava 0 ↔ 1 % com picos de 47–50 s; agora fica em
  10 % com o pior atraso sempre dentro do limite. As correções (vigilância zerada ao baixar o orçamento + subida
  com espera crescente) resolveram.

**Síntese do E3/E4 para o artigo** (perfil3, 1 núcleo do Pi 5, Wi-Fi):
- O custo por minuto de casa (12,4 ms com LSTM-AE sempre, 2,0–2,4 ms só estágio 1) mede-se igual no E2 e no E3.
- O atraso de alerta é dominado pela virada do minuto: ≈ nº de casas × custo por minuto de casa (K11).
- Com 4.000 casas (128 mil canais, 3.080 msg/s): LSTM-AE sempre ligado NÃO sustenta (CPU 98 %, fila crescente);
  cascata a 5 % sustenta com pior atraso 28,5 s; o controlador acha sozinho um orçamento (10 %) que cumpre 30 s.
- Engenharia que a carga revelou: fila interna (sem ela o Mosquitto descartava até 24 % das mensagens,
  confirmado no log dele), vigilância × controlador, casas jovens escalam mais, memória 0,6–0,8 MB por casa (3,3 GB com 4.000 casas).

### K15. E6 (opcional) — protocolo, fixado antes de rodar (23/11/2026)
- "E num dispositivo mais limitado?": CPU do Pi limitada por software a **1,5 GHz** (`scaling_max_freq`; o normal é
  2,4 GHz), governador `performance`, mesmo cenário do E4 (4.000 casas perfil3 fiéis, ~3.080 msg/s, Wi-Fi).
- Rodadas (`e3_pc.py --fiel --rodadas E6_b1 E6_ctrl`): E6_b1 orçamento 100 % (6 min) e E6_ctrl controlador com
  limite de 30 s (22 min). ~30 min no total.
- **Previsão** [derivada]: custo por minuto de casa escala com o clock (~2,4/1,5 = 1,6×). A 2,4 GHz o b = 100 % já
  saturava; a 1,5 GHz satura mais cedo. O controlador deve descer ABAIXO dos 10 % do E4 (5 % ou menos), porque
  10 % ali já usava ~70 % da CPU e dava 21–29 s de pior atraso (× 1,6 passaria de 30 s).

### K16. E6 — CPU do Pi limitada a 1,5 GHz (23/11/2026, 16:33–17:03) [medido]
Pasta `resultados/e3_20261123_1632` (+ `analise/`) e `simulador/registros/e6`. `scaling_max_freq` = 1.500.000
(conferido: `scaling_cur_freq` = 1500000), governador `performance`; `throttled=0x0` nas 64 leituras; máx. 41 °C;
memória até 3,3 GB. Depois: `scaling_max_freq` devolvido a 2.400.000. Mesmo cenário do E4 (4.000 casas fiéis).
- **b = 100 % a 1,5 GHz (6 min):** muito além da capacidade — processou 74 % do que chegou, fila +261 mil, pior atraso
  131 s e subindo, CPU 110 % (fila + thread de rede). Custo 17,8 ms por minuto de casa (12,9 ms a 2,4 GHz: 1,38×,
  menos que a razão de clock 1,6× — parte do custo não escala com a CPU).
- **Controlador a 1,5 GHz (22 min):** desceu 100 → 50 → 20 → 10 → 5 → **2 %** (min 0–8), esvaziou a fila acumulada no
  min 9 e ficou em 2 % por 9 min com pior atraso 25–29 s; depois foi a 1 % (min 17) e a 0 (min 21) quando o pior
  atraso encostou em 30,5 s (as janelas das casas jovens enchendo, K13). Nos últimos 5 min: tudo processado
  (100,6 %), CPU 82 %, escalados 12–16 %.
- **Previsão de K15 confirmada:** no Pi "mais fraco" o controlador escolheu sozinho um orçamento menor (2 % → 1 %) que
  no E4 a 2,4 GHz (10 %), mantendo o atraso no limite. É o argumento da cascata adaptativa: o mesmo pacote se ajusta
  ao hardware sem recalibrar.
- **Defeito de bancada achado:** o comando `reset` do roteiro entrava na fila interna atrás de ~380 mil mensagens da
  rodada b = 100 % e só foi aplicado 94 s depois (o início do E6_ctrl teve 1,5 min ainda com a carga da rodada
  anterior; o pico de 150–176 s dos min 0–1 inclui isso). Corrigido (comandos passam por fora da fila; teste ok);
  não muda a conclusão. Também: partindo de sobrecarga, descer um nível por minuto demora (8 min até 2 %);
  trabalho futuro: descer vários níveis quando o atraso passa muito do limite.

### K17. Fechamento da parte 2 (23/11/2026)
- **Testes no ambiente oficial (Windows do Kleber, Python 3.11, versões travadas), depois de todas as mudanças do
  dia:** detector **29 passed** (88 s); simulador **32 passed** (1 aviso de depreciação do starlette, sem efeito).
- **Pacote para o artigo:** `resultados/pacote_artigo/` — tabelas T1–T9, figuras F1–F7 (300 dpi, legíveis em preto e
  branco), `TABELAS_E_FIGURAS.md`, `FIDELIDADE_DO_SIMULADOR.md` e o `LEIAME.md` com o roteiro das seções 4–6 e os
  números-chave. Gerado só a partir dos resultados gravados (`scripts/gerar_pacote.py`).
- **Realismo × casa real (novo):** casa Boa Energia (Poli-USP, SP, fev/2020, por hora) tem o porte do perfil 2
  (313 × 291 kWh/mês), variação entre dias parecida (CV 0,22 × 0,13–0,24) e pico às 18 h (simulado: 19–20 h), mas
  consumo mais espalhado no dia (pico/média 1,67 × 3,3–3,7; correlação da forma 0,34–0,49): o simulador reproduz a
  casa média (EPE, CPFL), não uma casa específica. Achado: o `BoaEnergia.csv` está em M/D/AAAA, não DD/MM como diz o
  README da base.
- **Referência Hundman et al. (2018)** conferida e acrescentada a `tcc artigo/dados_pesquisa.md`.
- **Pi 4 → Pi 5** corrigido no README do simulador e no LEIAME do catálogo; README do detector atualizado.
- Decisões do Kleber: estágio 2 = LSTM-AE; dado real por aparelho = limitação (com a seção de fidelidade);
  Telegram/ação = trabalho futuro; git para depois.

## F. Pendências e decisões em aberto
1. ~~Rodada oficial no notebook~~ (feita em 22/11/2026, seção H).
2. ~~Estágio 1 da cascata~~: OCSVM + regra (H7).
3. ~~Hundman et al. (2018)~~: conferido no texto do artigo (arXiv v3) e no Crossref; regra de avaliação igual à nossa (1 VP por evento; 1 FP por alerta que não toca evento); acrescentado a `tcc artigo/dados_pesquisa.md` (23/11/2026).
4. ~~E2 no Pi~~: medido em 23/11/2026 (K9), válido (`throttled=0x0`).
5. ~~Confirmador do estágio 2~~: **decisão do Kleber (23/11/2026): fica o LSTM-AE** (o oficial, decidido antes do
   teste). O AE entra no artigo como análise de sensibilidade (K6/K7).
6. Fragilidade da regra a perda de mensagens e deriva (K5): só como limitação + trabalho futuro (regra sobre energia).
7. ~~Detector antigo no Pi~~: atualizado em 23/11/2026 (K9).
8. **Decisão do Kleber (23/11/2026):** Telegram e ação automática ficam como **trabalho futuro** (pouco acrescentam
   ao documento; a contribuição científica já está medida em E1–E5 e o alerta no painel fecha o ciclo da demo).
   Ordem: E6 (opcional, ~30 min) e depois a escrita do artigo (seções 4–6; revisar 1–3, Pi 4 → Pi 5; Hundman 2018).
9. **Dado real — decisão do Kleber (23/11/2026):** declarar como limitação, explicando bem que o simulador não usa
   valores inventados: cada número tem origem registrada (PBE/Inmetro, fabricante, loja, derivado ou assumido e
   documentado) e foi validado contra EPE, CPFL/ANEEL e uma casa real (Boa Energia). Material em
   `resultados/pacote_artigo/FIDELIDADE_DO_SIMULADOR.md`. Testar o detector em bases reais (IFES, ONS, ANEEL) não vale
   a pena: nenhuma tem dado por aparelho e por minuto.
