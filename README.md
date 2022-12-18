Note: I created this project to learn programming. I currently use `networkmanager-openvpn` with Gnome to manage VPNs from the GUI, hence archiving this repo.

![RepositoryBanner](https://i.imgur.com/LWbfiUO.png)

[![Stargazers][stars-shield]][stars-url]
[![Forks][forks-shield]][forks-url]
[![Contributors][contributors-shield]][contributors-url]
[![Issues][issues-shield]][issues-url]
[![GPLMIT License][license-shield]][license-url]

# NordVPN Linux Client [Unofficial]

The original NordVPN Linux client sucks, so I decided to make an open-source linux client for NordVPN based on OpenVPN. This client manages the openvpn configuration files and authentication, along with connection. It has not all the commands that are provided with the official NordVPN client (kill-switch etc.), but they will be added in future.

## Requires

* [Python-3.6+](https://python.org)

  ```sh
    $ sudo apt install python3
    # or
    $ sudo pacman -S python3
  ```

* [OpenVPN](https://openvpn.net)

  ```sh
      $ sudo apt install openvpn
      # or
      $ sudo pacman -S openvpn
  ```

* Unzip

  ```sh
      $ sudo apt install unzip
      # or
      $ sudo pacman -S unzip
  ```

## Installation

To get a local copy up and running follow these simple steps.

1. Clone the repository to your machine and change directory

  ```sh
    $ git clone https://github.com/priyansh-anand/nordvpn-linux.git
    $ cd nordvpn-linux
  ```

2. Install the nordvpn client and sync the ovpn files

  ```sh
    $ sudo ./install.sh
      [*] Installing NordVPN Linux Client [Unofficial]
      [*] Copying python scripts to /opt/nvpn/bin
      [+] Installing required python packages
      [*] Copying configuration files to /opt/nvpn/config
      [+] Creating login file at /opt/nvpn/login
      [*] Settings permissions for directories
      [+] Installing and enabling nvpn-deamon.service
      [+] Adding nordvpn & nvpn to path
      [+] NordVPN Linux Client successfully installed

    $ nordvpn sync-ovpn
      [+] NordVPN .ovpn files downloaded & extracted
  ```

## Uninstallation

It's just one command away from uninstallation

```sh
  $ sudo ./uninstall.sh
    [*] Uninstalling NordVPN Linux Client [Unofficial]
    [*] Removing /opt/nvpn/bin
    [+] Removing nvpn from path
    [+] Disabling and removing nvpn-deamon.service
    [+] NordVPN Linux Client successfully uninstalled
```

## Usage

Binary name : ```nordvpn``` or ```nvpn```

You always use ```help``` to get all the supported commands.

Commands supported:

* connect, c [country/server]: Connects you to NordVPN, if you don't provide a server/country, then it will automatically connect to closest one.

  ```sh
  $ nordvpn c
    [*] Closest country: India
    [*] Connected to NordVPN[IN96]

  $ nordvpn c us
    [*] Connected to NordVPN[US6471]
  ```

* disconnect, d: Disconnects you from NordVPN

  ```sh
  $ nordvpn d
    [*] Disconnected from NordVPN
  ```

* status, s: Get the current status of NordVPN connection

  ```sh
  $ nordvpn s
    [+] You're connected to NordVPN[US7813]
  ```

* login: Logs you in to NordVPN

  ```sh
  $ nordvpn login
    [*] Enter email: pr1y4nsh@protonmail.com
    [*] Enter password: **********
    [+] Saved login information, you can connect to NordVPN now
  ```

* logout: Logs you out from NordVPN

  ```sh
  $ nordvpn logout
    [+] Logged out from NordVPN
  ```

* sync-ovpn: Syncs the .ovpn files from NordVPN server
  You need to run this before connecting to NordVPN the first time or to update the NordVPN servers list

  ```sh
    $ nordvpn sync-ovpn
      [+] NordVPN .ovpn files downloaded & extracted
  ```

* help: Shows this info on terminal

## Contributing

Contributions are what make the open source community such an amazing place to be learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

Distributed under the GPL License. See `LICENSE` for more information.

## Contact

Priyansh Anand -  pr1y4nsh@protonmail.com

Project Link: [https://github.com/priyansh-anand/nordvpn-linux](https://github.com/priyansh-anand/nordvpn-linux)

[contributors-shield]: https://img.shields.io/github/contributors/priyansh-anand/nordvpn-linux.svg?style=for-the-badge
[contributors-url]: https://github.com/priyansh-anand/nordvpn-linux/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/priyansh-anand/nordvpn-linux.svg?style=for-the-badge
[forks-url]: https://github.com/priyansh-anand/nordvpn-linux/network/members
[stars-shield]: https://img.shields.io/github/stars/priyansh-anand/nordvpn-linux.svg?style=for-the-badge
[stars-url]: https://github.com/priyansh-anand/nordvpn-linux/stargazers
[issues-shield]: https://img.shields.io/github/issues/priyansh-anand/nordvpn-linux.svg?style=for-the-badge
[issues-url]: https://github.com/priyansh-anand/nordvpn-linux/issues
[license-shield]: https://img.shields.io/github/license/priyansh-anand/nordvpn-linux.svg?style=for-the-badge
[license-url]: https://github.com/priyansh-anand/nordvpn-linux/blob/master/LICENSE.txt
