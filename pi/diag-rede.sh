#!/bin/sh
# Diagnostico de rede do Pi (TCC). Uso: diag-rede.sh [segundos de espera] [arquivo de saida]
# Grava em /boot/firmware/diag-rede.txt, que fica na parte do cartao que o Windows consegue ler.
# Serve para descobrir por que o Pi some da rede depois de reiniciar, mesmo sem monitor.
# Nao grava a senha do Wi-Fi. E temporario: depois do diagnostico, desative com
#   sudo systemctl disable diag-rede.service
ESPERA="${1:-90}"
SAIDA="${2:-/boot/firmware/diag-rede.txt}"
sleep "$ESPERA"
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') | kernel $(uname -r) | ligado ha $(cut -d' ' -f1 /proc/uptime) s ====="
  echo "--- enderecos";           ip -br addr
  echo "--- dispositivos";        nmcli device status
  echo "--- conexoes";            nmcli -f NAME,TYPE,AUTOCONNECT,STATE connection show
  echo "--- redes wifi visiveis"; nmcli -f SSID,CHAN,SIGNAL,SECURITY device wifi list
  echo "--- rfkill";              rfkill list
  echo "--- pais do wifi";        iw reg get | head -n 8
  echo "--- enlace wifi";         iw dev wlan0 link
  echo "--- servicos com falha";  systemctl --failed --no-pager
  echo "--- registro (wifi e rede)"
  journalctl -b --no-pager | grep -i -E "wlan|brcm|cfg80211|rfkill|regdom|wpa_supplicant|NetworkManager|netplan" | tail -n 200
  echo
} >> "$SAIDA" 2>&1
sync
