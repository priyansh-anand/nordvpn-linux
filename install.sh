echo "[*] Installing NordVPN Linux Client [Unofficial]"
{
    echo "[*] Copying python scripts to /opt/nvpn/bin"
    sudo mkdir -p /opt/nvpn/bin &&
    sudo cp $(dirname $0)/src/*.py /opt/nvpn/bin &&
    sudo chmod +x /opt/nvpn/bin/* &&

    echo "[+] Installing required python packages" &&
    pip3 install -r $(dirname $0)/src/requirements.txt &&

    echo "[*] Copying configuration files to /opt/nvpn/config" &&
    sudo mkdir -p /opt/nvpn/config &&
    sudo cp $(dirname $0)/config/*.conf /opt/nvpn/config &&

    echo "[+] Creating login file at /opt/nvpn/login" &&
    sudo touch /opt/nvpn/login &&

    echo "[*] Settings permissions for directories" &&
    sudo chmod -R 777 /opt/nvpn && sudo chmod 755 /opt/nvpn/config/nordvpnd.conf &&

    echo "[+] Installing and enabling nvpn-deamon.service" &&
    sudo cp $(dirname $0)/src/nvpn-deamon.service /etc/systemd/system &&
    sudo systemctl enable nvpn-deamon.service &&
    sudo systemctl restart nvpn-deamon.service &&

    echo "[+] Adding nvpn to path" &&
    sudo ln -sf /opt/nvpn/bin/vpn.py /bin/nvpn &&

    echo "[+] NordVPN Linux Client successfully installed"
} || {
    echo "[-] NordVPN Linux Client failed to install"
}