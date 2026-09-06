@echo off
rem Start riichi-vision OCR service on port 8000 (independent module).
cd /d E:\riichi-vision
E:\riichi-vision\.venv\Scripts\python.exe -m uvicorn riichi_vision.app:app --app-dir backend --host 127.0.0.1 --port 8000
