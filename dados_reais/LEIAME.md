# Dados reais brasileiros (17/11/2026)

Detalhes de cada fonte e referência ABNT em `../tcc artigo/fontes_brasileiras.md`.

| Pasta | O que é | Situação |
| --- | --- | --- |
| `boa_energia/` | Casa brasileira (Poli-USP): consumo total, chuveiro, ar-condicionado, iluminação e temperatura, **por hora**. `BoaEnergia.csv` = 02/02–03/03/2020; `raw/` = 16/12/2019–14/01/2020 (um arquivo por dia; colunas na mesma ordem do CSV, sem cabeçalho). Valores em kVAh estimados pela corrente. Licença do repositório: GPL-3.0 (`LICENSE_OKIoT.txt`) | Baixado do GitHub `vthayashi/OKIoT` |
| `brazil_smart_home_testbed/` | Mesma origem. Eventos de luz (ON/OFF) e presença (PIR) por cômodo; ago, set e out/2019; um arquivo por dia (`timestamp_unix  cômodo  evento`) | Baixado |
| `lit_dataset_simulado/` | UTFPR. **Atenção: não são medições.** São os parâmetros e combinações de acionamento usados para gerar o subconjunto simulado (arquivos .mat do MATLAB). Guardado só como referência; o LIT real (15 kHz) está com o site fora do ar | Baixado do GitHub `hellenancelmo/Simulated-LIT-dataset` |
| `aneel_ctr/curvas_b1_normalizadas.json` | **Extrato** das curvas de carga residenciais (B1) de 15 min das campanhas de medição das distribuidoras: forma média da CPFL Paulista 2023 (10 consumidores tipo) e média de 62 distribuidoras, por tipo de dia | Extraído no navegador (o portal da ANEEL é bloqueado pela rede do computador). Método no próprio arquivo |

## Para baixar à mão (bloqueados pela rede deste computador para o Claude)

Abra no navegador e salve na pasta indicada:

| Arquivo | Link | Tamanho | Salvar em |
| --- | --- | --- | --- |
| ANEEL, curvas completas (Parquet) | https://dadosabertos.aneel.gov.br/dataset/ctr-curva-de-carga → "ctr-curvas-carga-consumidor-tipo.parquet" | 34 MB | `aneel_ctr/` |
| IFES Serra, consumo e demanda (15 min, 2022–2026) | https://data.mendeley.com/datasets/c9sb8cyn86/2 → "Download All" | 79,7 MB | `ifes_serra/` |
| ONS, curva de carga horária (um CSV por ano; baixe 2023 a 2025) | https://dados.ons.org.br/dataset/curva-carga | ~1–2 MB por ano | `ons_curva_carga/` |

Depois de baixar, avise na sessão que eu integro esses dados nos testes.
