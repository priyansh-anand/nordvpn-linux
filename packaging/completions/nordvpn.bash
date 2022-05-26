# SPDX-License-Identifier: GPL-3.0-only
# shellcheck shell=bash
# Bash completion for nordvpn.

_nordvpn_reply() {
    mapfile -t COMPREPLY < <(compgen -W "$1" -- "$2")
}

_nordvpn() {
    local cur=${COMP_WORDS[COMP_CWORD]}
    if (( COMP_CWORD == 1 )); then
        _nordvpn_reply "login logout connect c disconnect d status s countries settings set --version --help" "$cur"
        return
    fi
    case ${COMP_WORDS[1]} in
        connect|c)
            if (( COMP_CWORD == 2 )); then
                _nordvpn_reply "$(nordvpn countries --plain 2>/dev/null)" "$cur"
            fi
            ;;
        status|s|settings) _nordvpn_reply "--json" "$cur" ;;
        countries) _nordvpn_reply "--json --plain" "$cur" ;;
        login) _nordvpn_reply "--username --password-stdin" "$cur" ;;
        set)
            if (( COMP_CWORD == 2 )); then
                _nordvpn_reply "protocol dns" "$cur"
            elif (( COMP_CWORD == 3 )); then
                case ${COMP_WORDS[2]} in
                    protocol) _nordvpn_reply "udp tcp" "$cur" ;;
                    dns) _nordvpn_reply "on off" "$cur" ;;
                esac
            fi
            ;;
    esac
}

complete -F _nordvpn nordvpn
