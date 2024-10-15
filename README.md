![](assets/nvidia.png)

# 🚀️ LLDP-Check

## [00] git clone  

git clone https://github.com/aliaydemir80/lldp-check.git

cd lldp-check



## [01]  install and runn "nginx"

sudo apt install nginx

sudo systemctl enable --now nginx



## [02]  move files (cd LLDP-Check/)

sudo cp -r etc/* /etc

sudo cp -r html/* /var/www/html/

mv bin/* /usr/local/bin/

cp -r cable-check ~/cable-check 



## [03]  edit necesary files

sudo nano /etc/ip_list    

sudo nano /etc/nccm.yml   (edit the end)

nano ~/cable-check/devices.sh

nano ~/cable-check/topology.dot



## [04]  restart nginx service

sudo systemctl restart nginx



## [05]  add cron job

echo "0 * * * * cumulus /usr/local/bin/lldp-check" | sudo tee -a /etc/crontab



 
# run the LLDP-Check 🚀️

Before running lldp-check', 'ssh-copy-id' must be done on all devices.

lldp-check

zzh

pping

