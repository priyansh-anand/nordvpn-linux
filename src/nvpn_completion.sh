CONF_DIR="/opt/nordvpn/ovpn_config/ovpn_udp"

function completitions() {
    ATC=()
    if [[ "$COMP_CWORD" == "1" ]]; then {
        ATC+=("c" "d" "s" "connect" "disconnect" "status" "login" "logout" "sync-ovpn" "help")
    } elif [[ "$COMP_CWORD" == "2" ]]; then {
        CMD=${COMP_WORDS[1]}
        if [[ $CMD == "c" || $CMD == "connect" ]]; then {
            country_inp=${COMP_WORDS[2]//[0-9]/}
            server_num_inp=${COMP_WORDS[2]//[a-zA-Z]/}

            for conf in "$CONF_DIR"/*; do {
                IFS='/'; conf_file=($conf); unset IFS;
                IFS='.'; server=(${conf_file[-1]}); unset IFS;
                country=${server//[0-9]/}

                if [[ -n $server_num_inp || $country == $country_inp ]]; then {
                    ATC+=("${server}")
                } else {
                    ATC+=("${server//[0-9]/}")
                } fi
            } done
        } fi
    } else {
        return;
    } fi

    COMPREPLY=()
    for atc in ${ATC[@]}; do {
        if [[ $atc == ${COMP_WORDS[$COMP_CWORD]}* ]]; then {
            COMPREPLY+=($atc)
        } fi
    } done
}

complete -F completitions nvpn
complete -F completitions nordvpn
