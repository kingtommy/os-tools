@echo off
:: IP Tray — Disconnect AWS VPN
:: Kills the OpenVPN tunnel process to drop the VPN connection.
taskkill /F /IM acvc-openvpn.exe >nul 2>&1
taskkill /F /IM AWSVPNClient.exe >nul 2>&1
