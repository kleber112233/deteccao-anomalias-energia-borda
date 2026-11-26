"""Saída MQTT (contrato em docs/CONTRATO_MQTT.md). Funciona sem broker: guarda as últimas mensagens em memória."""
from __future__ import annotations
import json
from collections import deque

PROIBIDAS = {"anomalia", "falha_id", "falha_tipo", "canal_direto", "gabarito", "rotulo", "falha"}
TOPICO_ALERTAS = "casa/sistema/alertas"


class Publicador:
    def __init__(self, host: str | None = None, porta: int = 1883, casa: str = "+", ao_comando=None, ao_alerta=None,
                 client_id: str = "casasim", assinar: bool = True):
        self.ultimas: deque = deque(maxlen=300)
        self.enviadas = 0
        self.ativo, self.erro, self._cli = False, None, None
        self.ao_comando, self.ao_alerta = ao_comando, ao_alerta
        if not host:
            return
        try:
            import paho.mqtt.client as mqtt
            try:
                cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            except AttributeError:                       # paho-mqtt 1.x
                cli = mqtt.Client(client_id=client_id)
            cli.on_message = self._msg
            cli.connect(host, porta, keepalive=30)
            if assinar:
                cli.subscribe([(f"casa/{casa}/+/+/comando", 1), (TOPICO_ALERTAS, 1)])
            cli.loop_start()
            self._cli, self.ativo = cli, True
        except Exception as e:                           # sem broker: segue só com o painel
            self.erro = f"{type(e).__name__}: {e}"

    def _msg(self, cli, userdata, msg):
        try:
            dados = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        if msg.topic == TOPICO_ALERTAS:
            if self.ao_alerta:
                self.ao_alerta(dados)
        elif msg.topic.endswith("/comando") and self.ao_comando:
            partes = msg.topic.split("/")
            self.ao_comando(partes[3], dados)

    def publicar(self, topico: str, payload: dict, qos: int = 0) -> None:
        vazou = PROIBIDAS & set(payload)
        if vazou:                                        # trava de segurança: o gabarito nunca sai pelo MQTT
            raise ValueError(f"campo de gabarito no MQTT: {sorted(vazou)}")
        self.enviadas += 1
        self.ultimas.append((topico, payload))
        if self._cli is not None:
            self._cli.publish(topico, json.dumps(payload, ensure_ascii=False), qos=qos)

    def fechar(self) -> None:
        if self._cli is not None:
            self._cli.loop_stop()
            self._cli.disconnect()
            self._cli, self.ativo = None, False
