echo "[*] Uninstalling NordVPN Linux Client [Unofficial]"
{
    echo "[*] Removing /opt/nvpn/bin"
    sudo rm -r /opt/nvpn

    echo "[+] Removing nvpn from path"
    sudo rm /bin/nvpn

    echo "[+] Disabling and removing nvpn-deamon.service"
    sudo systemctl stop nvpn-deamon.service && sudo systemctl disable nvpn-deamon.service && sudo rm /etc/systemd/system/nvpn-deamon.service

    echo "[+] NordVPN Linux Client successfully uninstalled"
} || {
    echo "[-] NordVPN Linux Client failed to uninstall"
}