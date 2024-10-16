![](assets/nvidia.png)

# 🚀️ LLDPq

## [00] git clone  

git clone https://github.com/aliaydemir80/lldpq.git

cd lldpq

```install nginx, copy files, edit 4 files, then run```


## [01]  install and runn "nginx"
```
sudo apt install nginx

sudo systemctl enable --now nginx
```


## [02]  copy files (cd lldpq/)
```
sudo cp -r etc/* /etc

sudo cp -r html/* /var/www/html/

sudo cp bin/* /usr/local/bin/

cp -r cable-check ~/cable-check 
```


## [03]  edit necesary files
```
sudo nano /etc/ip_list    
```
```
sudo nano /etc/nccm.yml   (edit the end)
```
[edit the end of the nccm.yml file]
```
nano ~/cable-check/devices.sh
```
```
nano ~/cable-check/topology.dot
```


## [04]  restart nginx service
```
sudo systemctl restart nginx
```


## [05]  add cron job
```
echo "0 * * * * cumulus /usr/local/bin/lldpq" | sudo tee -a /etc/crontab
```


 
# run the LLDPq 🚀️

Before running lldp-check', 'ssh-copy-id' must be done on all devices.
```
lldpq
```
```
zzh
```
```
pping
```
