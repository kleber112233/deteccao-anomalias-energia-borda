# Datasets congelados v1 (simulador casasim)

Gerados por `simulador/ferramentas/gerar_datasets.py` (mesmo comando refaz exatamente os mesmos arquivos: tudo é
determinístico pela semente). Hashes SHA-256 de cada arquivo e do código de entrada estão em `manifesto.json`.

| | perfil1 | perfil2 | perfil3 |
|---|---|---|---|
| canais medidos | 5 | 15 | 31 |
| kWh/mês equivalente (5 sementes) | 147–163 | 288–303 | 967–1192 |

- 3 perfis × 5 sementes × 120 dias. A semente S começa em 05/01/2026 + 73·(S−1) dias, para que juntas cubram o ano.
- Divisão temporal por semente: 72 dias de **treino** (sem falha injetada), 24 de **calibração** e 24 de **teste**.
- Calibração e teste: 17 falhas cada (≈5 por semana), com os 7 tipos em proporções iguais e 60% delas num aparelho
  que tem medidor próprio. Total: 510 falhas (90 de magnitude, fora de horário e duração excessiva; 60 dos demais).
- Faltas de energia da rede (0 a 2 por conjunto) aparecem também no treino; no gabarito têm `alvo = rede` e
  `falha_id` começando por `R`. Não são defeito de aparelho.
- **Não use** as colunas `anomalia`, `falha_id`, `falha_tipo`, `canal_direto` como entrada do detector.
  `casasim.datasets.carregar(pasta, "treino")` já as remove.
- perfil3 nas sementes 4 e 5 (primavera/verão) passa um pouco da faixa anual de 694–1157 kWh/mês por causa do ar-condicionado;
  a faixa vale para a média do ano.
