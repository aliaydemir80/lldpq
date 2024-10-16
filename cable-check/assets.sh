#!/bin/bash

DATE=$(date '+%Y-%m-%d--%H-%M')

source ./devices.sh

commands='echo $HOSTNAME $(/usr/sbin/ifconfig eth0 | grep netmask | cut -d " " -f 10) $(/usr/sbin/ifconfig eth0 | grep ether | cut -d " " -f 10) $(nv sh platform | grep serial-number | cut -d " " -f 3) $(nv sh platform | grep product-name | cut -d " " -f 4) $(cat /etc/lsb-release  | grep RELEASE | cut -d "=" -f2) '

#echo "========================================================================================" > ~/cable-check/assets.txt
echo "DEVICE-NAME ETH0-IP ETH0-MAC SERIAL MODEL VERSION" > ~/cable-check/assets.txt
#echo "========================================================================================" >> ~/cable-check/assets.txt

unreachable_hosts=()

ping_test() {
    local device=$1
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

echo ""
echo -e "\e[1;34mAll commands have been executed...\e[0m"
echo ""
if [ ${#unreachable_hosts[@]} -ne 0 ]; then
    echo -e "\e[0;36mUnreachable hosts:\e[0m"
    echo ""
    for host in "${unreachable_hosts[@]}"; do
        IFS=' ' read -r ip hostname <<< "$host"
        printf "\e[31m[%-14s]\t\e[0;31m[%-1s]\e[0m\n" "$ip" "$hostname"
        #echo -e "\e[0;31m[ $ip ]\t\e[1;31m[ $hostname ]\e[0m"
    done
    echo ""
else
    echo -e "\e[0;32mAll hosts are reachable.\e[0m"
    echo ""
fi
column -t ~/cable-check/assets.txt > ~/cable-check/asset
rm -rf ~/cable-check/assets.txt
sort -t'.' -k1,1n -k2,2n -k3,3n -k4,4n ~/cable-check/asset > ~/cable-check/assets
rm -rf ~/cable-check/asset
echo -e "\nCreated on $DATE" >> ~/cable-check/assets
sudo cp ~/cable-check/assets /var/www/html/
exit 0
