:: 启动网络悬浮窗（静默，无命令行窗口）
@echo off
cd /d "%~dp0"
:: 使用 pythonw.exe（无窗口 Python）+ start /b 避免创建新控制台
start "" /b pythonw.exe "%~dp0network_overlay.pyw"
