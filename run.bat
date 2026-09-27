@echo off
cd /d "%~dp0"
echo Starting osu! Map AI Generator...
start http://127.0.0.1:5173/generator.html
cmd /k "npm run generator:dev"