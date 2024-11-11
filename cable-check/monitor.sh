#!/bin/bash

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
    ssh -o StrictHostKeyChecking=no -T -q "$user@$device" "nv show interface" >> monitor-results/${hostname}.html
    echo "</h3>" >> monitor-results/${hostname}.html
    echo "</pre>" >> monitor-results/${hostname}.html
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
