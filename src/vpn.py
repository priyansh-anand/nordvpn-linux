#!/bin/python3

import os
import random
import shutil
import socket
import string
import sys
from configparser import ConfigParser
from getpass import getpass

import progress_py
import requests

CREDS_FILE = "/opt/nordvpn/login"
CONFIG_FILE = "/opt/nordvpn/config/nordvpn.conf"
DEAMON_CONFIG_FILE = "/opt/nordvpn/config/nordvpnd.conf"


class Utils:
    LOCATION_API = "http://ip-api.com/json/?fields=status,countryCode,country"

    @staticmethod
    def readable_size(size: float) -> str:
        sizes = ["B", "KB", "MB", "GB", "TB", "PB"]

        ind = 0
        while size > 1024:
            size /= 1024
            ind += 1

        return "{:.2f}{}".format(size, sizes[ind])

    @staticmethod
    def random_string(size: int) -> str:
        return "".join(random.choices(string.ascii_letters + string.digits, k=size))


class VPN:
    def __init__(self, config: str, deamon_config: str) -> None:
        self.config = ConfigParser()
        self.deamon_config = ConfigParser()

        try:
            self.config.read(config)
        except:
            print("[!] Cannot load configuration file")
            print("    > Cannot read config file at {}".format(config))
            sys.exit(0)

        try:
            self.deamon_config.read(deamon_config)
        except:
            print("[!] Cannot load deamon configuration file")
            print("    > Cannot read config file at {}".format(deamon_config))
            sys.exit(0)

    def sync_ovpn_conf(self) -> None:
        try:
            progress_bar = progress_py.ProgressBar()
            confs = requests.get(self.config["CONF"]["CONF_URL"], stream=True)

            downloaded_size = 0
            total_size = int(confs.headers["Content-Length"])
            progress_bar.set_msg("{:.2f}% {{progress}} {}/{} - Downloading NordVPN .ovpn files".format(
                100*downloaded_size / total_size, Utils.readable_size(downloaded_size), Utils.readable_size(total_size)))
            progress_bar.start()

            if os.path.exists(self.config["CONF"]["CONF_DIR"]):
                shutil.rmtree(self.config["CONF"]["CONF_DIR"])

            zip_name = os.path.join("/tmp/", Utils.random_string(10))
            conf_f = open("{}".format(zip_name), "wb")
            for chunk in confs.iter_content(51200):
                conf_f.write(chunk)
                downloaded_size += len(chunk)

                progress_bar.percent_completed = 100 * downloaded_size/total_size
                progress_bar.set_msg("{:.2f}% {{progress}} {}/{} - Downloading NordVPN .ovpn files".format(
                    100 * downloaded_size / total_size, Utils.readable_size(downloaded_size), Utils.readable_size(total_size)))

            conf_f.close()
            progress_bar.stop()

            spinner = progress_py.Spinner(msg="Unzipping NordVPN .ovpn files")
            spinner.start()

            unzip_ret_code = os.system("unzip {} -d {} > /dev/null 2>&1".format(zip_name,
                                                                                self.config["CONF"]["CONF_DIR"]))
            if unzip_ret_code != 0:
                raise RuntimeError

            spinner.stop(clean=True)
            print("[+] NordVPN .ovpn files downloaded & extracted")
        except:
            print("[!] NordVPN .ovpn files failed to download or extract")
            sys.exit()

    def _ipc_deamon(self, command: bytes) -> str:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.deamon_config["IPC"]["IPC_SOCKET_ADDRESS"])
            sock.send(command)

            resp = sock.recv(1024).decode("UTF-8")
            sock.close()

            return resp
        except KeyboardInterrupt:
            self._disconnect()
            return "CANCELLED"
        except:
            return "DEAMON_DOWN"

    def _connect(self, conf: str, server_name: str) -> str:
        return self._ipc_deamon(b"CONNECT " + conf.encode("UTF-8") + b" " + server_name.encode("UTF-8"))

    def _disconnect(self) -> None:
        return self._ipc_deamon(b"DISCONNECT")

    def _status(self) -> None:
        return self._ipc_deamon(b"STATUS")

    def connect(self, server_prefix: str) -> None:
        try:
            if self.config["DEFAULT"]["CREDS_FILE"] == "/dev/null":
                print("[!] You're not logged in")
                print("    > Try 'nordvpn login' to login to NordVPN")
                sys.exit(0)

            mode = "udp"
            if self.config["DEFAULT"]["MODE"].upper() == "TCP":
                mode = "tcp"
        except KeyError:
            print("[!] Invalid configuration")
            print("    > Check the configuration file at {}".format(CONFIG_FILE))
            sys.exit(0)

        try:
            servers = os.listdir(os.path.join(self.config["CONF"]["CONF_DIR"], "ovpn_{}".format(mode)))
            servers = [server for server in servers if server.startswith(server_prefix)]

            if "{}.nordvpn.com.{}.ovpn".format(server_prefix, mode) in servers:
                server = "{}.nordvpn.com.{}.ovpn".format(server_prefix, mode)
            else:
                server = random.choice(servers)
            server_name = server.split(".")[0].upper()
        except FileNotFoundError:
            print("[!] NordVPN .ovpn config files not found")
            print("    > Check the directory: {}".format(self.config["CONF"]["CONF_DIR"]))
            print("    > Hint: Try using 'nordvpn sync-ovpn' to sync the NordVPN .ovpn files to this directory")
            sys.exit(0)
        except IndexError:
            print("[!] No server .ovpn file found with prefix: {}".format(server_prefix))
            print("    > Check the directory: {}".format(self.config["CONF"]["CONF_DIR"]))
            print("    > Hint: Try using 'nordvpn sync-ovpn' to sync the NordVPN .ovpn files to this directory")
            sys.exit(0)

        spinner = progress_py.Spinner("Connecting to Nordvpn [{}]".format(server_name))
        spinner.start()

        try:
            conf = os.path.join(self.config["CONF"]["CONF_DIR"], "ovpn_{}".format(mode), server)
            conf_data = open(conf).read()
            conf_data += "\nauth-user-pass {}".format(self.config["DEFAULT"]["CREDS_FILE"])

        except FileNotFoundError:
            print("[!] NordVPN .ovpn file not found at {}".format(conf))
            print("    > Check the directory: {}".format(self.config["CONF"]["CONF_DIR"]))
            sys.exit(0)

        try:
            conf_temp = os.path.join("/tmp/", Utils.random_string(10))
            conf_temp_f = open(conf_temp, "w")
            conf_temp_f.write(conf_data)
            conf_temp_f.close()
        except:
            print("[!] Cannot write NordVPN .ovpn file to {}".format(conf_temp))
            print("    > Check the permissions of /tmp directory")

        resp = self._connect(conf_temp, server_name)

        spinner.stop(clean=True)

        if resp == "SUCCESS":
            print("[+] Connected to NordVPN[{}]".format(server_name))
        elif resp == "AUTH_ERROR":
            print("[!] Invalid credentials for NordVPN")
        elif resp == "DEAMON_ERROR":
            print("[!] Runtime error in NordVPN Deamon")
        elif resp == "DEAMON_DOWN":
            print("[!] NordVPN Deamon is not running")
        elif resp == "CANCELLED":
            print("[*] Stopped connecting to NordVPN")
        else:
            print("[!] Unexpected NordVPN Deamon error")

    def connect_auto(self) -> None:
        self._disconnect()

        spinner = progress_py.Spinner("Locating closest country")
        spinner.start()

        try:
            resp = requests.get(Utils.LOCATION_API)
        except KeyboardInterrupt:
            spinner.stop(clean=True)
            print("[*] Stopped connecting to NordVPN")
            sys.exit()
        except:
            print("[!] Cannot fetch {}".format(Utils.LOCATION_API))
            resp = None

        if resp and resp.status_code == 200 and resp.json()["status"] == "success":
            server_prefix = resp.json()["countryCode"]
            spinner.stop(clean=True)
            print("[*] Closest country: {}".format(resp.json()["country"]))
        else:
            spinner.stop(clean=True)
            print("[!] Cannot auto-connect to nearest country's VPN")
            server_prefix = input("[*] Please enter Country Code/Server Name to connect: ")

        server_prefix = server_prefix.lower()
        self.connect(server_prefix)

    def disconnect(self) -> None:
        spinner = progress_py.Spinner("Disconnecting from NordVPN")
        spinner.start()

        resp = self._disconnect()

        spinner.stop(clean=True)
        if resp == "SUCCESS":
            print("[+] Disconnected from NordVPN")
        else:
            print("[!] Cannot disconnect from NordVPN")

    def status(self) -> None:
        spinner = progress_py.Spinner("Getting NordVPN status")
        spinner.start()

        resp = self._status()

        spinner.stop(clean=True)
        if resp == "DISCONNECTED":
            print("[-] You're not connected to NordVPN")
        else:
            print("[+] You're connected to NordVPN[{}]".format(resp))

    def login(self) -> None:
        username = input("[*] Enter email: ")
        password = getpass("[*] Enter password: ")

        try:
            with open(CREDS_FILE, "w+") as f:
                f.write("{}\n{}".format(username, password))

            self.config["DEFAULT"]["CREDS_FILE"] = CREDS_FILE
            with open(CONFIG_FILE, "w+") as f:
                self.config.write(f)

            print("[+] Saved login information, you can connect to NordVPN now")
        except:
            print("[!] Cannot login to NordVPN")
            print("    > Cannot write to the directory /opt/nordvpn | Check permissions")

    def logout(self) -> None:
        try:
            self.config["DEFAULT"]["CREDS_FILE"] = "/dev/null"
            with open(CONFIG_FILE, "w+") as f:
                self.config.write(f)
                f.close()

            print("[+] Logged out from NordVPN")
        except:
            print("[!] Cannot logout from NordVPN")
            print("    > Cannot write to the directory /opt/nordvpn | Check permissions")

    def cli(self) -> None:
        if len(sys.argv) > 1:
            command = sys.argv[1]

            if command == "c" or command == "connect":
                if len(sys.argv) > 2:
                    server_prefix = sys.argv[2]
                    self.connect(server_prefix)
                else:
                    self.connect_auto()
            elif command == "d" or command == "disconnect":
                self.disconnect()
            elif command == "s" or command == "status":
                self.status()
            elif command == "sync-ovpn":
                self.sync_ovpn_conf()
            elif command == "login":
                self.login()
            elif command == "logout":
                self.logout()
            elif command == "help":
                self.help()
            else:
                print("[!] Invalid command")
                print("    > Try 'nordvpn help'")
        else:
            self.help()

    def help(self) -> None:
        print("[*] NordVpn Linux client [nordvpn/nvpn]")
        print("[+] Commands:")
        print("\tlogin \t\t\t\tLogs you in")
        print("\tlogout\t\t\t\tLogs you out")
        print("\tconnect, c [country/server]\tConnects you to VPN, can also provide country/server name after this")
        print("\tdisconnect, d\t\t\tDisconnects you from VPN")
        print("\tstatus, s\t\t\tGet the current status of NordVPN connection")
        print("\tsync-ovpn\t\t\tSyncs the .ovpn files from NordVPN server")


if __name__ == '__main__':
    vpn = VPN(CONFIG_FILE, DEAMON_CONFIG_FILE)
    vpn.cli()
