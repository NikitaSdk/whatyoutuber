@echo off
rem Запуск тем Python, в котором уже стоит конвертер «Видео → текст».
set "CONV=%~dp0..\MP4-TXT\.venv\Scripts\python.exe"
if exist "%CONV%" (
  "%CONV%" "%~dp0main.py" %*
) else (
  python "%~dp0main.py" %*
)
