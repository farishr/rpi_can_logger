#!/bin/bash

# Start the NetworkManager service
sudo systemctl start NetworkManager.service

# Create a WiFi hotspot with specified SSID and password
sudo nmcli device wifi hotspot ssid can_logger password password
