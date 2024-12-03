#!/bin/bash

DATE=$(date '+%Y-%m-%d %H-%M')
SCRIPT_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")
source "$SCRIPT_DIR/devices.sh"
commands='echo $HOSTNAME $(/usr/sbin/ifconfig eth0 | grep netmask | cut -d " " -f 10) $(/usr/sbin/ifconfig eth0 | grep ether | cut -d " " -f 10) $(nv sh platform | grep serial-number | cut -d " " -f 3) $(nv sh platform | grep product-name | cut -d " " -f 4) $(cat /etc/lsb-release  | grep RELEASE | cut -d "=" -f2) $(uptime -p | sed "s/,//g; s/ /-/g") '
echo "DEVICE-NAME ETH0-IP ETH0-MAC SERIAL MODEL VERSION UPTIME" > ~/cable-check/assets.txt
unreachable_hosts=()
unreachable_info=()
ping_test() {
    local device=$1
    ping -c 1 -W 1 "$device" > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        unreachable_hosts+=("$device $hostname")
        unreachable_info+=("$hostname")
        return 1
    fi
    return 0
}
execute_commands() {
    local device=$1
    local user=$2
    local hostname=$3
    for command in "${commands[@]}"; do
        ssh -o StrictHostKeyChecking=no -T -q "$user@$device" $command 2>/dev/null >> ~/cable-check/assets.txt
    done
}
for device in "${!devices[@]}"; do
    IFS=' ' read -r user hostname <<< "${devices[$device]}"
    ping_test "$device" "$hostname"
    if [ $? -eq 0 ]; then
        execute_commands "$device" "$user" "$hostname" &
        sleep 0.1
    fi
done
wait
column -t ~/cable-check/assets.txt > ~/cable-check/asset
rm -rf ~/cable-check/assets.txt
sort -t'.' -k1,1n -k2,2n -k3,3n -k4,4n ~/cable-check/asset > ~/cable-check/assets.ini
rm -rf ~/cable-check/asset
for hostname in "${unreachable_info[@]}"; do
    printf "%s\t No-Info\n" "$hostname" >> ~/cable-check/assets.ini
done
echo -e "\nCreated on $DATE" >> ~/cable-check/assets.ini
sudo cp ~/cable-check/assets.ini /var/www/html/
exit 0

