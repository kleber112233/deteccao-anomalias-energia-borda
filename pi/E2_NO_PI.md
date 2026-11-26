# E2 no Raspberry Pi — passo a passo (preparado pelo Claude em 23/11/2026)

O que mede: (1) a latência de UMA inferência de cada modelo (regra, IF, OCSVM, AE, LSTM-AE), por canal, com
atributos reais; (2) o custo do sistema completo ao vivo (atributos + cascata) por minuto de casa, com orçamento
0, 5 % e 100 %, nas casas perfil1_s1 (6 canais) e perfil3_s1 (31 canais). Tempo total estimado: 15–30 min no Pi.

Arquivo a copiar: `resultados\_transferencia\e2_pi.tar` (código novo do detector + modelos + dados das 2 casas +
`e2.sh`). Ele substitui a pasta `~/tcc-pi/detector` antiga (a versão do Pi ainda é a anterior à otimização K3).

> **No repositório público:** o `e2_pi.tar` (81 MB) não foi publicado, porque reúne modelos e dados que podem ser
> regerados. Para montá-lo, junte numa pasta: `detector/` (README, `pyproject.toml`, `requirements.txt` e o pacote
> `detector/detector`); `pacotes/perfil1_s1` e `pacotes/perfil3_s1` (de `pi/pacotes`); `baselines/perfil1/semente_1`
> e `baselines/perfil3/semente_1` (de `resultados/baselines_v1`, com os `.onnx` regerados por
> `python -m detector baselines`); `dados/perfil1/semente_1` e `dados/perfil3/semente_1` (de `datasets/v1`,
> regerados por `simulador/ferramentas/gerar_datasets.py`); e `pi/e2.sh`. Dentro dessa pasta, rode `tar cf e2_pi.tar *`.
> Os resultados desta medição estão em `resultados/e2_20261123_0912`.

## Antes de começar
- Dissipador/ventoinha no Pi (na última medida ele chegou a 82,6 °C e reduziu o clock: `throttled=0xe0000`).
- Reinicie o Pi para zerar os contadores de throttling.

## Passo 1 — PC (`PS C:\>`): copiar o pacote para o Pi
    scp C:\Users\klebe\Desktop\faculdade\TCC\resultados\_transferencia\e2_pi.tar kleber_tcc@192.168.0.57:~/tcc-pi/
Esperado: uma linha `e2_pi.tar 100% ...`.

## Passo 2 — Pi (`kleber_tcc@pi-tcc`): desempacotar
    cd ~/tcc-pi && tar xf e2_pi.tar && ls
Esperado: aparecem `baselines  dados  detector  e2.sh  pacotes` (além do que já existia).

## Passo 3 — Pi: parar o serviço do detector (se estiver rodando), para não disputar a CPU
Se ele roda num terminal, `Ctrl+C` nesse terminal. Se roda como serviço do systemd:
    sudo systemctl stop detector
Esperado: nenhuma saída. Confira com `htop` que nenhum `python` está usando CPU.

## Passo 4 — Pi: governador da CPU em "performance" (clock fixo, medida estável)
    echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
Esperado: imprime `performance`. Volta sozinho para o padrão quando o Pi reiniciar.

## Passo 5 — Pi: rodar o E2
    cd ~/tcc-pi && bash e2.sh
Esperado: para cada casa, 5 linhas `regra/if/ocsvm/ae/lstm_ae mediana=... us`, depois 3 linhas JSON por casa (uma
por orçamento) com `ms_por_minuto`, e no fim `PRONTO: resultados em ~/tcc-pi/e2_AAAAMMDD_HHMM`.
Durante a rodada, se quiser acompanhar a temperatura em outro terminal: `watch -n 5 vcgencmd measure_temp`.

## Passo 6 — PC: trazer os resultados de volta (troque o nome da pasta pelo que apareceu no passo 5)
    scp -r kleber_tcc@192.168.0.57:~/tcc-pi/e2_AAAAMMDD_HHMM C:\Users\klebe\Desktop\faculdade\TCC\resultados\
Esperado: lista de arquivos copiados (custo_*.json, reproduzir_*.txt, estado.txt, ambiente.json).

Depois é só avisar o Claude: ele lê a pasta, confere `estado.txt` (se `throttled` não for `0x0`, a medida não vale)
e escreve o E2 no DIARIO.

## Referência (não é o E2): mesma ferramenta no notebook (VM do Cowork no i9-12900KF), 23/11/2026
Mediana por inferência, perfil1_s1: regra 2,9 µs; IF 600 µs; OCSVM 4,8 µs; AE 5,4 µs; LSTM-AE 52 µs.
