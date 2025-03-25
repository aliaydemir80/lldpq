#!/bin/bash

SCRIPT_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")
source "$SCRIPT_DIR/devices.sh"
unreachable_hosts=()

ping_test() {
    local device=$1
    local hostname=$2
    ping -c 1 -W 1 "$device" > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        unreachable_hosts+=("$device $hostname")
        return 1
    fi
    return 0
}

execute_commands() {
    local device=$1
    local user=$2
    local hostname=$3
    ssh -q -o StrictHostKeyChecking=no "${user}@${device}" "sudo cat /var/log/linkstate" > linkstate-results/${hostname}-linkstate.ini
}

for device in "${!devices[@]}"; do
    IFS=' ' read -r user hostname <<< "${devices[$device]}"
    ping_test "$device" "$hostname"
    if [ $? -eq 0 ]; then
        execute_commands "$device" "$user" "$hostname" &
    else
        echo -e "\e[0;31m${hostname} (${device}) is unreachable\e[0m"
    fi
done

wait

echo ""
echo -e "\e[1;34mAll commands have been executed...\e[0m"
echo ""
if [ ${#unreachable_hosts[@]} -ne 0 ]; then
    echo -e "\e[0;36mUnreachable hosts:\e[0m"
    echo ""
    for host in "${unreachable_hosts[@]}"; do
        IFS=' ' read -r ip hostname <<< "$host"
        printf "\e[31m[%-14s]\t\e[0;31m[%-1s]\e[0m\n" "$ip" "$hostname"
        #echo -e "\e[0;31m[${ip}]\t\e[1;31m[${hostname}]\e[0m"
    done
    echo ""
else
    echo -e "\e[0;32mAll hosts are reachable.\e[0m"
    echo ""
fi
exit 0
