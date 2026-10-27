@echo off
rem Abre o terminal de modelos no Windows PowerShell sem depender da política de execução.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0modelos.ps1" %*
