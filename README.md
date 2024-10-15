![](assets/nvidia.png)

# 🚀️ LLDP-Check



## [01]  install and runn "nginx"

sudo apt install nginx

sudo systemctl enable --now nginx



## [02]  move files (cd LLDP-Check/)

sudo mv bin/* /usr/local/bin/

sudo mv etc/* /etc/

sudo mv html/* /var/www/html/

sudo mv cable-check ~/cable-check 



## [03]  edit necesary files

sudo nano /etc/ip_list    

sudo nano /etc/nccm.yml   (edit the end)

sudo nano ~/cable-check/devices.sh

sudo nano ~/cable-check/topology.dot



## [04]  edit nginx config

Add the "/hstr" folder

sudo nano /etc/nginx/sites-enabled/default


        server_name _;


        location / {
                try_files $uri $uri/ =404;
        }

#insert the following exactly in place of the above

        location /hstr/ {
            autoindex on;
            autoindex_exact_size off;
            autoindex_localtime on;
        }


sudo systemctl restart nginx



## [05]  add cron job

sudo nano /etc/crontab


0 * * * * cumulus /usr/local/bin/lldp-check



 
# 🚀️ run the LLDP-Check

Before running 'cable-check', 'ssh-copy-id' must be done on all devices.

lldp-check

zzh

pping

