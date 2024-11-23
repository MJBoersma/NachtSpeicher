""" MQTT wrapper around paho, to make message publishing in the main program simple """
import json
import os
import logging
import paho.mqtt.client as paho

class Client():
    """ MQTT client object """
    def __init__(self):
        """ Setup the client, do not yet connect. Read configuration from json file """
        self.enabled = False
        if not os.path.exists('mqtt.cfg'):
            logging.info("""mqtt.cfg not found, running without publishing MQTT. Example:
            {
             "server": "192.168.2.10",
             "topicNT": "heating/NT",
             "topicLevel": "heating/level",
             "clientname": "pino",
             "port": 1883
            }""")
            return
        with open('mqtt.cfg', encoding="utf-8") as file:
            parms = json.load(file)
        for (k,v) in parms.items():
            setattr(self, k, v)
        self.pahoclient = paho.Client(parms["clientname"], clean_session=False)
        self.connected = False
        self.enabled = True

    def publish(self, NT, level):
        """ Connect if necessary, then publish the message @msg. """
        if not self.enabled:
            return
        if not self.connected:
            try:
                self.pahoclient.connect(self.server, self.port, 30)
                self.pahoclient.loop_start()
                self.connected = True
                logging.info('MQTT connection established')
            except Exception:
                logging.info('MQTT connection failed')
        self.pahoclient.publish(self.topicNT,NT)
        self.pahoclient.publish(self.topicLevel,f"{level:.1f}")
