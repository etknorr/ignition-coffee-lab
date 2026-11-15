# MQTT service

An Eclipse Mosquitto broker for the Roastery's MQTT transport
slot. The app models the feed transport flexibly (RoasterSource):
the Pico W monitor already publishes bean temperature over MQTT
(topic `roastery/sr800/temp`), and this broker is where it lands
in the packaged stack.

Ignition has no built in MQTT client, so the broker alone does
not move values into tags: a bridge (the Cirrus Link MQTT Engine
modules, or a small client service) subscribes here and writes
the RoasterSource Mqtt slot's BeanTempF member; setting
ActiveSource to Mqtt then makes the console follow it. The lab
gateway models the slot with a memory tag at
mqtt://localhost:1883; in this stack the broker is reachable from
the gateway container as `mqtt-roastery:1883` on the proxy
network and from the LAN on the host's 1883 port.

Config: `mosquitto.conf` (anonymous, persistence on; local
network posture only, see the comment in the file).
