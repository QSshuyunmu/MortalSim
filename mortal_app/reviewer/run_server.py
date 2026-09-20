import sys, time
from pathlib import Path
for p in [r"D:\tenhoulib\MortalSim", r"D:\tenhoulib"]:
    if p not in sys.path: sys.path.insert(0, p)

from mortal_app.reviewer.web_server import start_review_server_bg

server = start_review_server_bg(50718)
while True:
    time.sleep(1)
