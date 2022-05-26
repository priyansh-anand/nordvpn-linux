# SPDX-License-Identifier: GPL-3.0-only
# Fish completion for nordvpn.

set -l commands login logout connect c disconnect d status s countries settings set

complete -c nordvpn -f
complete -c nordvpn -l version -d 'Show the version'
complete -c nordvpn -n "not __fish_seen_subcommand_from $commands" -a login -d 'Save your NordVPN service credentials'
complete -c nordvpn -n "not __fish_seen_subcommand_from $commands" -a logout -d 'Disconnect and forget the saved credentials'
complete -c nordvpn -n "not __fish_seen_subcommand_from $commands" -a 'connect c' -d 'Connect to NordVPN'
complete -c nordvpn -n "not __fish_seen_subcommand_from $commands" -a 'disconnect d' -d 'Disconnect from NordVPN'
complete -c nordvpn -n "not __fish_seen_subcommand_from $commands" -a 'status s' -d 'Show the connection status'
complete -c nordvpn -n "not __fish_seen_subcommand_from $commands" -a countries -d 'List the countries you can connect to'
complete -c nordvpn -n "not __fish_seen_subcommand_from $commands" -a settings -d 'Show the current settings'
complete -c nordvpn -n "not __fish_seen_subcommand_from $commands" -a set -d 'Change a setting'

complete -c nordvpn -n "__fish_seen_subcommand_from connect c" -a "(nordvpn countries --plain 2>/dev/null)"
complete -c nordvpn -n "__fish_seen_subcommand_from status s settings" -l json -d 'Machine-readable output'
complete -c nordvpn -n "__fish_seen_subcommand_from countries" -l json -d 'Machine-readable output'
complete -c nordvpn -n "__fish_seen_subcommand_from countries" -l plain -d 'Country codes only'
complete -c nordvpn -n "__fish_seen_subcommand_from login" -l username -r -d 'Service username'
complete -c nordvpn -n "__fish_seen_subcommand_from login" -l password-stdin -d 'Read the password from stdin'
complete -c nordvpn -n "__fish_seen_subcommand_from set; and not __fish_seen_subcommand_from protocol dns" -a 'protocol dns'
complete -c nordvpn -n "__fish_seen_subcommand_from set; and __fish_seen_subcommand_from protocol" -a 'udp tcp'
complete -c nordvpn -n "__fish_seen_subcommand_from set; and __fish_seen_subcommand_from dns" -a 'on off'
