@echo off
REM Build completo do AutoEditor para Windows (executável + instalador).
REM Requer Python 3.10+ e Inno Setup instalados (apenas para gerar o instalador).

python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements-dev.txt
python scripts\build_executable.py
echo.
echo Se o Inno Setup estiver instalado, o instalador estara em dist\AutoEditorSetup-1.0.0.exe
pause
