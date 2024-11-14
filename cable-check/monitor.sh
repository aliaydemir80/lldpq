#!/bin/bash
DATE=$(date '+%Y-%m-%d %H-%M')
SCRIPT_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")
source "$SCRIPT_DIR/devices.sh"
execute_commands() {
    local device=$1
    local user=$2
    local hostname=$3
    cat <<EOF > monitor-results/${hostname}.html
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head>
    <link rel="shortcut icon" href="/png/favicon.ico">
    <title>..::nvidia::..</title>
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <link rel="stylesheet" type="text/css" href="/css/styles2.css">
    <style>.interface-info {color: green;margin-top: 20px;}</style>
</head>
<body>
    <h1></h1>
    <h1><font color="#b57614">Port Monitoring ${hostname}</font></h1>
    <h3></h3>
EOF
#    ssh -o StrictHostKeyChecking=no -T -q "$user@$device" "bwm-ng -o html" >> monitor-results/${hostname}.html
#    sed -i 's/"bwm-ng-header">bwm-ng bwm-ng v0.6.3 (refresh 5s); input: \/proc\/net\/dev/ /g' monitor-results/${hostname}.html
#    echo "" >> monitor-results/${hostname}.html

    echo "<h3 class='interface-info'>" >> monitor-results/${hostname}.html
    echo "<pre>" >> monitor-results/${hostname}.html

    ssh -o StrictHostKeyChecking=no -T -q "$user@$device" "nv show interface | sed -E '1 s/^port/<span style=\"color:green;\">Interface<\/span>/; 1,2! s/^(\S+)/<span style=\"color:steelblue;\">\1<\/span>/;  s/ up /<span style=\"color:lime;\"> up <\/span>/g; s/ down /<span style=\"color:red;\"> down <\/span>/g'" >> monitor-results/${hostname}.html

    echo "<h1></h1><h1><font color="#b57614">Port VLAN Mapping ${hostname}</font></h1><h3></h3>" >> monitor-results/${hostname}.html
    ssh -o StrictHostKeyChecking=no -T -q "$user@$device" "nv show bridge port-vlan | cut -c12- | sed -E '1 s/^port/<span style=\"color:green;\">port<\/span>/; 2! s/^(\s{0,2})([a-zA-Z_]\S*)/\1<span style=\"color:steelblue;\">\2<\/span>/; s/\btagged\b/<span style=\"color:tomato;\">tagged<\/span>/g'" >> monitor-results/${hostname}.html

    echo "<h1></h1><h1><font color="#b57614">ARP Table ${hostname}</font></h1><h3></h3>" >> monitor-results/${hostname}.html
    ssh -o StrictHostKeyChecking=no -T -q "$user@$device" "ip neighbour | grep -E -v 'fe80' | sort -t '.' -k1,1n -k2,2n -k3,3n -k4,4n | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)/<span style=\"color:tomato;\">\1<\/span>/; s/dev ([^ ]+)/dev <span style=\"color:steelblue;\">\1<\/span>/; s/lladdr ([0-9a-f:]+)/lladdr <span style=\"color:tomato;\">\1<\/span>/'" >> monitor-results/${hostname}.html

    echo "<h1></h1><h1><font color="#b57614">MAC Table ${hostname}</font></h1><h3></h3>" >> monitor-results/${hostname}.html
    ssh -o StrictHostKeyChecking=no -T -q "$user@$device" "sudo bridge fdb | grep -E -v '00:00:00:00:00:00' | sort | sed -E 's/^([0-9a-f:]+)/<span style=\"color:tomato;\">\1<\/span>/; s/dev ([^ ]+)/dev <span style=\"color:steelblue;\">\1<\/span>/; s/vlan ([0-9]+)/vlan <span style=\"color:red;\">\1<\/span>/; s/dst ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)/dst <span style=\"color:lime;\">\1<\/span>/'" >> monitor-results/${hostname}.html

    echo "<h1></h1><h1><font color="#b57614">BGP STATUS ${hostname}</font></h1><h3></h3>" >> monitor-results/${hostname}.html
    ssh -o StrictHostKeyChecking=no -T -q "$user@$device" "sudo vtysh -c \"show bgp vrf all sum\" | sed -E 's/(VRF\s+)([a-zA-Z0-9_-]+)/\1<span style=\"color:tomato;\">\2<\/span>/g; s/Total number of neighbors ([0-9]+)/Total number of neighbors <span style=\"color:steelblue;\">\1<\/span>/g; s/(\S+)\s+(\S+)\s+Summary/<span style=\"color:lime;\">\1 \2<\/span> Summary/g; s/\b(Active|Idle)\b/<span style=\"color:red;\">\1<\/span>/g'" >> monitor-results/${hostname}.html

    echo "</h3>" >> monitor-results/${hostname}.html
    echo "</pre>" >> monitor-results/${hostname}.html
    echo -e "<span style=\"color:tomato;\">Created on $DATE</span>" >> monitor-results/${hostname}.html
    echo "</body></html>" >> monitor-results/${hostname}.html
}

for device in "${!devices[@]}"; do
    IFS=' ' read -r user hostname <<< "${devices[$device]}"
    execute_commands "$device" "$user" "$hostname" &
    sleep 0.1
done
wait
sudo cp -r monitor-results/ /var/www/html/
exit 0
