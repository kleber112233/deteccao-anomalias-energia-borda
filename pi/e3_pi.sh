#!/bin/bash
# E3/E4 — lado do Pi. Rodar NO PI, dentro de ~/tcc-pi:   bash e3_pi.sh
# Deixa o detector em modo de carga (casas virtuais "carga*" com o modelo perfil3_s1) ouvindo o MQTT, mais a
# coleta de CPU do Mosquitto e do sistema a cada 10 s. Quem conduz as rodadas é o roteiro do PC (e3_pc.py).
# Para parar tudo no fim:   bash e3_pi.sh parar
set -e
cd "$(dirname "$0")"
if [ "$1" = "parar" ]; then
  [ -f e3_pids.txt ] && kill $(cat e3_pids.txt) 2>/dev/null || true
  rm -f e3_pids.txt
  sleep 12; pgrep -af "detector servico" || echo "parado"; exit 0
fi
source .venv/bin/activate
export PYTHONPATH="$PWD/detector"
OUT="e3_$(date +%Y%m%d_%H%M)"
mkdir -p "$OUT"
{
  echo "== antes $(date '+%F %T')"
  echo "governador: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
  vcgencmd measure_temp; vcgencmd get_throttled; uptime; free -m
  iwconfig 2>/dev/null | grep -E "ESSID|Bit Rate|Signal" || true
} | tee "$OUT/estado_antes.txt"
top -b -d 10 -p "$(pgrep -d, mosquitto)" > "$OUT/mosquitto_top.txt" 2>&1 &
echo $! > e3_pids.txt
vmstat -t 10 > "$OUT/vmstat.txt" 2>&1 &
echo $! >> e3_pids.txt
( while sleep 30; do echo "$(date '+%T') $(vcgencmd measure_temp) $(vcgencmd get_throttled)"; done ) > "$OUT/temperatura.txt" 2>&1 &
echo $! >> e3_pids.txt
nohup python -m detector servico --carga pacotes/perfil3_s1 --orcamento 1.0 --registro "$OUT/servico.jsonl" \
  > "$OUT/servico.log" 2>&1 &
echo $! >> e3_pids.txt
sleep 3
echo "detector em modo de carga rodando; resultados em ~/tcc-pi/$OUT"
echo "acompanhar:  tail -f ~/tcc-pi/$OUT/servico.log | grep -v ALERTA"
