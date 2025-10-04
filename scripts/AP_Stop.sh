#!/bin/bash

sudo nmcli device disconnect wlan0
sudo systemctl start dhcpcd.service		# Starting Wifi Client