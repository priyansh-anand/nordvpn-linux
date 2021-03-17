echo "[*] Installing NordVPN Linux Client [Unofficial]"
{
    echo "[*] Copying scripts to /opt/nordvpn/bin"
    sudo mkdir -p /opt/nordvpn/bin &&
    sudo cp $(dirname $0)/src/* /opt/nordvpn/bin &&
    sudo chmod +x /opt/nordvpn/bin/* &&

    echo "[+] Installing required python packages" &&
    pip3 install -r $(dirname $0)/misc/requirements.txt &&

    echo "[*] Copying configuration files to /opt/nordvpn/config" &&
    sudo mkdir -p /opt/nordvpn/config &&
    sudo cp $(dirname $0)/config/*.conf /opt/nordvpn/config &&

    echo "[+] Creating login file at /opt/nordvpn/login" &&
    sudo touch /opt/nordvpn/login &&

    echo "[*] Settings permissions for directories" &&
    sudo chmod 777 /opt/nordvpn &&
    sudo chmod 666 /opt/nordvpn/login &&
    sudo chmod 666 /opt/nordvpn/config/nordvpn.conf &&
    sudo chmod 644 /opt/nordvpn/config/nordvpnd.conf &&

    echo "[+] Installing and enabling nordvpn-deamon.service" &&
    sudo cp $(dirname $0)/misc/nordvpn-deamon.service /etc/systemd/system &&
    sudo systemctl enable nordvpn-deamon.service &&
    sudo systemctl restart nordvpn-deamon.service &&

    echo "[+] Adding nordvpn to path" &&
    sudo ln -sf /opt/nordvpn/bin/vpn.py /bin/nvpn &&
    sudo ln -sf /opt/nordvpn/bin/vpn.py /bin/nordvpn &&

    echo "[+] Enabling auto-completion for nordvpn" &&
    echo "source /opt/nordvpn/bin/nvpn_completion.sh" >> ~/.bashrc

    echo "[+] NordVPN Linux Client successfully installed"
} || {
    echo "[-] NordVPN Linux Client failed to install"
}