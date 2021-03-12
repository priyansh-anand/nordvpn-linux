#!/bin/python3

import logging
import os
import signal
import socket
import sys
from configparser import ConfigParser
from subprocess import PIPE, STDOUT, Popen

DEAMON_CONFIG_FILE = "/opt/nvpn/config/nordvpnd.conf"


class VPNDeamon:
    def __init__(self, deamon_config: str) -> None:
        # State of the VPN
        self.status = "DISCONNECTED"

        # Load the config file
        self.deamon_config = ConfigParser()
        self.deamon_config.read(deamon_config)

        # Setup the logger class for logging
        self.setup_logging()

        # This will be the OpenVPN process
        self.vpn: Popen

        # Get the socket file path from the config loaded
        self.socket_fp = self.deamon_config["IPC"]["IPC_SOCKET_ADDRESS"]

        # Remove the socket file if it exists, then bind the socket to that file path and set 777 permissions to the socket
        if os.path.exists(self.socket_fp):
            os.remove(self.socket_fp)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(self.socket_fp)
        os.chmod(self.socket_fp, 0o777)

    def setup_logging(self) -> None:
        log_file = self.deamon_config["LOG"]["LOG_FILE"]
        logging.basicConfig(
            filename=log_file, format="[%(levelname)s] - [%(filename)s:%(lineno)3s - %(funcName)15s()] - %(message)s",
            level=logging.DEBUG)

    def setup_vpn_proc(self, conf: str) -> None:
        # Create an openvpn process
        try:
            self.vpn = Popen(["openvpn", conf], stdout=PIPE, stderr=STDOUT, stdin=PIPE)
            if self.vpn is None:
                logging.error("openvpn process is None")
                sys.exit()
        except Exception as ex:
            logging.error("{} - Cannot create openvpn process".format(ex), exc_info=True)
            sys.exit()

    def connect(self, conf: str, server_name: str) -> str:
        # Setup the openvpn process first
        self.setup_vpn_proc(conf)

        # Get the stdout from the openvpn process, and process it
        for line in iter(self.vpn.stdout.readline, b""):
            line = line.decode("UTF-8")
            logging.debug(line[:-1])

            line = line.upper()
            if "AUTH_FAILED" in line:
                return "AUTH_ERROR"
            if "INITIALIZATION SEQUENCE COMPLETED" in line:
                self.status = server_name
                return "SUCCESS"
            if "OPERATION NOT PERMITTED" in line:
                return "DEAMON_ERROR"

        return "DEAMON_ERROR"

    def disconnect(self) -> str:
        # Kill the openvpn process, effectively disconnecting the vpn
        try:
            if self.vpn:
                self.vpn.kill()
                self.vpn.wait()

            self.status = "DISCONNECTED"
            return "SUCCESS"
        except:
            return "DEAMON_ERROR"

    def ipc(self) -> None:
        # function for IPC (Inter-process Communication)
        logging.debug("[*] VPN-Deamon started")

        # Listen upto 5 connections
        self.socket.listen(5)
        while True:
            # Accept any incoming connection
            conn, _ = self.socket.accept()
            try:
                while True:
                    # Receive message from the client
                    msg = conn.recv(1024).decode("UTF-8")
                    if not msg:
                        break
                    logging.debug("<msg received>: {}".format(msg))

                    # Process message sent by client
                    if msg.startswith("CONNECT"):
                        _, conf, server_name = msg.split(" ")
                        ret_code = self.connect(conf, server_name).encode("UTF-8")
                        conn.send(ret_code)

                        logging.debug("<msg sent>: {}".format(ret_code.decode("UTF-8")))

                    elif msg.startswith("DISCONNECT"):
                        ret_code = self.disconnect().encode("UTF-8")
                        conn.send(ret_code)

                        logging.debug("<msg sent>: {}".format(ret_code.decode("UTF-8")))

                    elif msg.startswith("STATUS"):
                        conn.send(self.status.encode("UTF-8"))
                        logging.debug("<msg sent>: {}".format(self.status.encode("UTF-8")))

                    else:
                        conn.send(b"NOT_IMPLEMENTED")

            except Exception as ex:
                logging.error("{}".format(ex), exc_info=True)
            finally:
                conn.close()

    def __del__(self) -> None:
        # This function will be called when this instance will be deleted
        # Close the socket and remove the socket file
        self.socket.close()
        logging.debug("[*] VPN-Deamon closed")
        os.remove(self.socket_fp)


def kill_self(signal_num, frame):
    global vpn
    del vpn

    sys.exit()


def main():
    global vpn
    signal.signal(signal.SIGINT, kill_self)

    vpn = VPNDeamon(DEAMON_CONFIG_FILE)
    vpn.ipc()


if __name__ == "__main__":
    vpn = None
    main()
