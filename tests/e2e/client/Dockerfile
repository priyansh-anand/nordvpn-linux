# SPDX-License-Identifier: GPL-3.0-only
FROM debian:12
ENV container=docker DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      systemd systemd-sysv systemd-resolved dbus openvpn python3 curl ca-certificates \
      iproute2 procps \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home alice \
 && useradd --create-home mallory
COPY e2e-trust.sh /usr/local/sbin/e2e-trust
COPY e2e-trust.service /etc/systemd/system/e2e-trust.service
RUN chmod 0755 /usr/local/sbin/e2e-trust \
 && systemctl enable e2e-trust.service systemd-resolved.service \
 && systemctl mask getty.target systemd-udevd.service systemd-udevd-control.socket \
      systemd-udevd-kernel.socket
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
