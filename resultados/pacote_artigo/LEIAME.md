# Pacote de resultados para o artigo (ponte para a etapa 3)

Gerado em 23/11/2026, quando a parte 2 (detector no Raspberry Pi 5) foi encerrada. Tudo aqui sai dos arquivos já
gravados em `TCC/resultados/` — nada foi treinado nem medido de novo. Para refazer:

    python scripts/realismo_boa_energia.py <TCC> <este pacote>/tabelas      (pandas + pyarrow)
    python scripts/gerar_pacote.py <TCC> <este pacote>                       (pandas + matplotlib + tabulate)

| arquivo | o que é |
|---|---|
| `TABELAS_E_FIGURAS.md` | todas as tabelas já em Markdown, com o arquivo de origem de cada uma |
| `tabelas/T*.csv` | tabelas finais (T1 a T9) |
| `figuras/F*.png` | figuras em 300 dpi (F1 a F7), com legendas e marcadores que funcionam em preto e branco |
| `FIDELIDADE_DO_SIMULADOR.md` | de onde vem cada número do simulador + validação contra EPE, CPFL/ANEEL e uma casa real; parágrafo sugerido para o artigo |
| `scripts/` | os dois scripts que geram o pacote |

## Decisões já tomadas (não reabrir)
- Estágio 1 da cascata = **OCSVM + regra de limiar fixo**; estágio 2 = **LSTM-AE** (Kleber, 22 e 23/11/2026). O AE
  como confirmador entra só como análise de sensibilidade (T3).
- **Dado real por aparelho = limitação**, com a seção de fidelidade do simulador (Kleber, 23/11/2026).
- **Telegram e ação automática = trabalho futuro** (Kleber, 23/11/2026).
- A placa é um **Raspberry Pi 5 (4 GB)** — os textos antigos que falam em Pi 4 estão errados.

## Roteiro sugerido para as seções 4–6 do artigo (o que vai onde)

**4. Materiais e métodos**
- 4.1 Casa simulada e dados → `FIDELIDADE_DO_SIMULADOR.md`; `simulador/DIARIO.md`; `datasets/v1/LEIAME.md`
  (3 perfis × 5 sementes × 120 dias; divisão temporal 60/20/20; 510 falhas, 7 tipos).
- 4.2 Atributos e modelos → DIARIO do detector, seções B e D (um modelo por canal + canal virtual `residuo`; grade
  de 1 min; hiperparâmetros fixados a priori).
- 4.3 Avaliação por evento → seção C + Hundman et al. (2018) (`tcc artigo/dados_pesquisa.md`, atualização de
  23/11/2026): 1 VP por evento; 1 FP por alerta que não toca evento; tolerância −5/+30 min.
- 4.4 Cascata e orçamento → seção I (desenho decidido só na calibração; teste usado uma vez).
- 4.5 Versão no Pi e serviço MQTT → seções J e K10/K12 (fila interna, controlador de carga).
- 4.6 Bancada e experimentos E1–E6 → K4, K10, K12, K15 (Pi 5 a 2,4 GHz, governador performance, refrigeração,
  `throttled=0x0` conferido; Wi-Fi; E6 a 1,5 GHz).

**5. Resultados**
- E1 qualidade: T1, T1b, T1c, F1 (baselines); T2, F2 (cascata por orçamento); T4, F3 (dados novos e robustez);
  T3 (arquitetura — exploratório no teste e confirmado nos dados novos, com teste pareado em K7).
- E2 custo no Pi: T5, F4 (uma inferência); T6 (sistema por minuto; a otimização dos atributos foi 3,9×).
- E3 capacidade: T7, F5 (atraso ≈ nº de casas × custo por casa); T8 (4.000 casas: LSTM-AE sempre não sustenta,
  cascata a 5 % sustenta).
- E4/E6 adaptação: F6 + T8 (o controlador escolhe 10 % a 2,4 GHz e 2→1 % a 1,5 GHz, mantendo ~30 s).
- E5 ponta a ponta: T9 (1 alerta falso em 29,7 dias; latência do sistema 0,11 s).

**6. Discussão, limitações e trabalhos futuros** (tudo já anotado no DIARIO do detector)
- O ganho da cascata é de **custo/capacidade**, não de qualidade (K5, K7): só o estágio 1 tem F1 igual ou maior.
- Casas sem medidor próprio e consumo não explicado são o ponto fraco (T1c, T9).
- A regra de limiar fixo é frágil a perda de mensagens e a deriva de calibração (K5, F3) → regra sobre energia.
- Casas recém-ligadas escalam mais (K13); memória de 0,6–0,8 MB por casa (K11/K13); controlador lento ao sair de
  sobrecarga (K16); comandos fora da fila (K16).
- Lições de engenharia que a carga revelou (K11–K14): o Mosquitto descartava mensagens (confirmado no log dele),
  vigilância × controlador, gerador irreal.
- Dado real por aparelho (limitação); Telegram e ação automática; dispositivo físico pelo mesmo contrato MQTT.

## Números-chave (para o resumo/abstract)
- 15 casas (3 perfis × 5 sementes), 5 baselines; melhor baseline OCSVM: AUC-PR por evento 0,43 (T1).
- Cascata OCSVM + regra → LSTM-AE: F1 0,484 com 5 % escalado — o mesmo que escalando 100 % (0,484) e acima do
  LSTM-AE sozinho (0,345) — a ~8 % do custo do LSTM-AE sempre ligado (T2); em 28 dias novos, 0,41 (T3/T4).
- Raspberry Pi 5: OCSVM 20 µs, LSTM-AE 200 µs por inferência (T5); 4.000 casas perfil3 = 128 mil canais e ~3.080
  msg/s: LSTM-AE sempre ligado não sustenta, cascata sustenta com pior atraso de 28,5 s (T8).
- Controlador: 10 % de orçamento a 2,4 GHz e 1–2 % a 1,5 GHz, mesmo pacote, sem recalibrar (F6).
- Ponta a ponta: precisão 0,98 e 1 alerta falso em 29,7 dias simulados; latência do sistema 0,11 s (T9).

## Pendências que não bloqueiam a escrita
- Conferir a premissa de 5 h/dia da etiqueta de TV (Portaria Inmetro 377/2021) e o DEC/FEC da CPFL Paulista.
- Revisar as seções 1–3 já entregues: trocar Pi 4 → Pi 5 e o trecho de `tflite-runtime` (o TCC usa ONNX Runtime).
- Repositório git (o Kleber decidiu deixar para depois).
