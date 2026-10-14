# Compatibility entry point for the guided Windows setup and startup manager.
& (Join-Path $PSScriptRoot 'windows_app.ps1') -Action Setup
