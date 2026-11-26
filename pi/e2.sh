#!/bin/bash
# E2 — custo no Raspberry Pi 5. Rodar NO PI, dentro de ~/tcc-pi:   bash e2.sh
# Antes: (1) Pi com dissipador/ventoinha e recém-ligado; (2) serviço do detector PARADO (ele disputa a CPU);
#        (3) governador em "performance" (ver E2_NO_PI.md). O script só mede; não muda nada no sistema.
# Saída: pasta e2_AAAAMMDD_HHMM com um .json/.txt por medida e estado.txt (temperatura e throttling antes/depois).
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH="$PWD/detector"
OUT="e2_$(date +%Y%m%d_%H%M)"
mkdir -p "$OUT"

estado() {
  echo "== $1  $(date '+%F %T')"
  echo "governador: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
  echo "freq_mhz: $(( $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq) / 1000 ))"
  vcgencmd measure_temp
  vcgencmd get_throttled
  uptime
}

estado "antes" | tee "$OUT/estado.txt"
python -m detector ambiente > "$OUT/ambiente.json"

# 1) Latência de UMA inferência por modelo (lote 1, 1 thread), atributos reais de 1 dia do teste
for c in perfil1/semente_1 perfil3/semente_1; do
  n="${c/\//_}"
  echo "-- custo $n"
  python -m detector custo --casa "baselines/$c" --dados "dados/$c" --saida "$OUT/custo_$n.json" | tee "$OUT/custo_$n.txt"
  estado "depois de custo $n" | tee -a "$OUT/estado.txt"
done

# 2) Sistema completo ao vivo (atributos + cascata), partição de teste inteira, orçamentos 0, 5 % e 100 %
for c in perfil1 perfil3; do
  echo "-- reproduzir ${c}_s1"
  python -m detector reproduzir --pacote "pacotes/${c}_s1" --dados "dados/$c/semente_1" --orcamento 0 0.05 1 \
    | tee "$OUT/reproduzir_${c}_s1.txt"
  estado "depois de reproduzir ${c}_s1" | tee -a "$OUT/estado.txt"
done

echo "PRONTO: resultados em ~/tcc-pi/$OUT"
