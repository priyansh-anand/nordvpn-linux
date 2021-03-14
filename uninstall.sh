echo "[*] Uninstalling NordVPN Linux Client [Unofficial]"
{
    echo "[*] Removing /opt/nordvpn/bin"
    sudo rm -r /opt/nordvpn

    echo "[+] Removing nordvpn from path"
    sudo rm /bin/nordvpn

    echo "[+] Disabling and removing nordvpn-deamon.service"
    sudo systemctl stop nordvpn-deamon.service && sudo systemctl disable nordvpn-deamon.service && sudo rm /etc/systemd/system/nordvpn-deamon.service

    echo "[+] NordVPN Linux Client successfully uninstalled"
} || {
    echo "[-] NordVPN Linux Client failed to uninstall"
}