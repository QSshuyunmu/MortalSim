#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天凤天梯实时看板 · 本地版

在您自己的电脑上运行，读取「已同步到本地的」天梯数据库，随时查看榜单。
不依赖任何第三方库，仅需 Python 3.8+ 标准库。

数据来源（两个文件，都来自 Google Drive 的 tenhouarena 文件夹）：
  ladder_results.db    逐半庄对局明细（Cell 6 每 5 批快照一次）
  ladder_state.json    各账号的段位/PT/R 快照（同样每 5 批一次）

找文件的顺序：
  1) --db / --state 显式指定的路径
  2) 当前目录
  3) Windows 下载文件夹
  4) Google Drive 桌面版常见同步位置（G 盘虚拟盘符 / 用户目录）
  5) Colab 路径（脚本也能在 Colab 里用）

用法示例：
  python ladder_watch_local.py                      # 自动找文件，每 30 秒刷新
  python ladder_watch_local.py --once               # 只打印一次
  python ladder_watch_local.py -n 10                # 每 10 秒刷新
  python ladder_watch_local.py --db "D:\\数据\\ladder_results.db"
  python ladder_watch_local.py -w 160               # 指定输出宽度（默认自动探测）
"""
import os
import sys
import json
import time
import sqlite3
import datetime
import argparse
import unicodedata
from pathlib import Path

# Windows 控制台常见 GBK 编码：强制 UTF-8 输出，避免中文/制表符报错
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOM_CN = {'houou': '凤凰卓', 'tokujou': '特上卓', 'joukyuu': '上级卓', 'ippan': '一般卓'}
DAN = {1: '初段', 2: '二段', 3: '三段', 4: '四段', 5: '五段',
       6: '六段', 7: '七段', 8: '八段', 9: '九段', 10: '十段', 11: '天凤位'}

HOME = Path.home()
DIR_NAMES = ['tenhouarena', 'tenhou_arena', 'tenhou_ranked_ladder']


def _candidate_dirs():
    """可能存放数据文件的目录，按优先级。"""
    out = []
    out.append(Path.cwd())                                   # 当前目录
    out.append(HOME / 'Downloads')                           # 浏览器下载
    out.append(HOME / 'Desktop')                             # 桌面
    # Google Drive 桌面版（新版虚拟盘符 G:，或经典用户目录同步）
    for letter in ('G', 'H'):
        for sub in ('My Drive', 'MyDrive'):
            out.append(Path(f'{letter}:/') / sub)
    for base in (HOME / 'Google Drive', HOME / 'MyDrive', HOME / 'GoogleDrive'):
        out.append(base)
        out.append(base / 'My Drive')
    return out


def find_file(name):
    """按优先级搜索数据文件，返回 Path 或 None。"""
    for d in _candidate_dirs():
        p = d / name
        if p.exists():
            return p
        # tenhouarena 等子文件夹
        for sub in DIR_NAMES:
            p2 = d / sub / name
            if p2.exists():
                return p2
    # Colab 路径兜底
    for p in (f'/content/{name}', f'/content/drive/MyDrive/tenhouarena/{name}'):
        if os.path.exists(p):
            return Path(p)
    return None


def dw(s):
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in str(s))


def pad(s, w, al='<'):
    s = str(s)
    f = max(0, w - dw(s))
    return s + ' ' * f if al == '<' else ' ' * f + s


def clip(s, w):
    s = str(s)
    if dw(s) <= w:
        return s
    o, c = [], 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        if c + cw > w - 1:
            break
        o.append(ch)
        c += cw
    return ''.join(o) + '~'


def sep(label, W):
    pre = f'-- [{label}] '
    return pre + '-' * max(0, W - dw(pre))


PT_EXPR = ("SUM(CASE WHEN room='houou' AND rank=1 THEN 90 WHEN room='houou' AND rank=2 THEN 45 "
           "WHEN room='tokujou' AND rank=1 THEN 75 WHEN room='tokujou' AND rank=2 THEN 30 "
           "WHEN room='joukyuu' AND rank=1 THEN 60 WHEN room='joukyuu' AND rank=2 THEN 15 "
           "WHEN room='ippan' AND rank=1 THEN 30 WHEN room='ippan' AND rank=2 THEN 15 ELSE 0 END)")


def stable(r1, r2, r4, room):
    if r4 <= 0:
        return None
    return ((6.0 * r1 + 3.0 * r2) if room == 'houou' else (5.0 * r1 + 2.0 * r2)) / r4 - 2.0


def collect(db_path, state_path):
    """读库 + 读状态快照。数据库被占用/损坏时抛异常，由调用方兜住。"""
    con = sqlite3.connect(str(db_path), timeout=5)
    try:
        rows = con.execute(f"""
            SELECT avatar_id, model_id, room, COUNT(*),
                   SUM(rank=1), SUM(rank=2), SUM(rank=3), SUM(rank=4),
                   SUM(score<0), {PT_EXPR}, SUM(score)
            FROM ladder_games GROUP BY avatar_id, room""").fetchall()
        meta = con.execute(
            'SELECT COUNT(*), MIN(seed_idx), MAX(seed_idx) FROM ladder_games').fetchone()
    finally:
        con.close()

    by = {}
    for aid, mid, room, g, r1, r2, r3, r4, fly, _pp, sc in rows:
        d = by.setdefault(aid, {'m': mid, 'g': 0, 'r1': 0, 'r2': 0, 'r3': 0, 'r4': 0,
                                'fly': 0, 'sc': 0})
        d['g'] += g
        d['r1'] += r1
        d['r2'] += r2
        d['r3'] += r3
        d['r4'] += r4
        d['fly'] += fly
        d['sc'] += sc

    st = None
    if state_path and Path(state_path).exists():
        try:
            st = json.loads(Path(state_path).read_text(encoding='utf-8'))
        except Exception:
            st = None
    for aid, d in by.items():
        s = (st or {}).get('players', {}).get(aid, {})
        d['dan'] = s.get('dan')
        d['pt'] = s.get('pt')
        d['R'] = s.get('rating')
        d['th'] = s.get('is_tenhou', False)
    return by, meta, st


def draw(by, meta, st, db_path, state_path, W):
    clamped = W < 48
    W = max(W, 48)
    cmp_ = W < 110
    line = '=' * min(W, 118)
    o = [line,
         '天凤天梯实时看板(本地)  ' + datetime.datetime.now().strftime('%m-%d %H:%M:%S'),
         line]

    n, smin, smax = meta
    o.append(clip(f'  已落库 {n // 4} 半庄   seed {smin} -> {smax}', W))
    try:
        mt = datetime.datetime.fromtimestamp(Path(db_path).stat().st_mtime)
        sz = Path(db_path).stat().st_size / 1024 / 1024
        o.append(clip(f'  数据文件: {db_path}', W))
        o.append(clip(f'            {sz:.1f} MB，更新于 {mt:%m-%d %H:%M:%S}'
                      f'{"  [已截断显示]" if clamped else ""}', W))
    except OSError:
        o.append(clip(f'  数据文件: {db_path}', W))
    if st:
        o.append(clip(f'  段位快照: {state_path}', W))
        o.append(clip(f'            (快照于 {st.get("saved_at")}；'
                      f'快照每 5 批写一次，胜率为实时值)', W))
    else:
        o.append('  段位快照: 未找到 -> 段位/PT/R 列留空（不影响胜率与安定段位）')
    if clamped:
        o.append(clip(f'  [提示] 终端过窄，按 48 列渲染', W))
    o.append(line)

    grp = {'houou': [], 'tokujou': [], 'other': []}
    for aid, d in by.items():
        dan, R = d['dan'], d['R']
        if d['th'] or (dan and dan >= 7 and (R or 0) >= 2000):
            grp['houou'].append((aid, d))
        elif dan and dan >= 4 and (R or 0) >= 1800:
            grp['tokujou'].append((aid, d))
        else:
            grp['other'].append((aid, d))

    for key, label in (('houou', '凤凰卓'), ('tokujou', '特上卓'), ('other', '其他/上级')):
        lst = grp[key]
        if not lst:
            continue
        lst.sort(key=lambda t: (t[1]['dan'] or 0, t[1]['R'] or 0), reverse=True)
        o.append('')
        o.append(sep(f'{label} {len(lst)}席', W))
        if cmp_:
            h = (pad('账号', 13) + pad('段位', 5, '>') + pad('半庄', 5, '>') +
                 pad('1位', 5, '>') + pad('4位', 6, '>') +
                 pad('凤安', 6, '>') + pad('特安', 6, '>'))
            o.append(h)
            o.append('-' * dw(h))
            for aid, d in lst:
                g = d['g'] or 1
                dan = d['dan']
                ds = '天凤位' if d['th'] else (DAN.get(dan, '?') if dan else '-')
                fh = stable(d['r1'], d['r2'], d['r4'], 'houou')
                ft = stable(d['r1'], d['r2'], d['r4'], 'tokujou')
                o.append(pad(aid, 13) + pad(ds, 5, '>') + pad(d['g'], 5, '>') +
                         pad(f'{d["r1"] / g * 100:.1f}', 5, '>') +
                         pad(f'{d["r4"] / g * 100:.1f}', 6, '>') +
                         pad(f'{fh:.2f}' if fh else '-', 6, '>') +
                         pad(f'{ft:.2f}' if ft else '-', 6, '>'))
        else:
            h = (pad('账号', 14) + pad('物理模型', 20) + pad('段位', 6, '>') +
                 pad('PT', 9, '>') + pad('R', 7, '>') + pad('半庄', 6, '>') +
                 pad('1位', 6, '>') + pad('2位', 6, '>') + pad('3位', 6, '>') +
                 pad('4位', 6, '>') + pad('被飞', 6, '>') +
                 pad('凤安', 6, '>') + pad('特安', 6, '>'))
            o.append(h)
            o.append('-' * dw(h))
            for aid, d in lst:
                g = d['g'] or 1
                dan = d['dan']
                ds = '天凤位' if d['th'] else (DAN.get(dan, '?') if dan else '-')
                pts = '-' if dan is None else ('冻结' if d['th'] else f'{d["pt"]}/{400 * dan}')
                fh = stable(d['r1'], d['r2'], d['r4'], 'houou')
                ft = stable(d['r1'], d['r2'], d['r4'], 'tokujou')
                o.append(pad(aid, 14) + pad(d['m'], 20) + pad(ds, 6, '>') + pad(pts, 9, '>') +
                         pad(f'{d["R"]:.1f}' if d['R'] is not None else '-', 7, '>') +
                         pad(d['g'], 6, '>') +
                         pad(f'{d["r1"] / g * 100:.1f}', 6, '>') +
                         pad(f'{d["r2"] / g * 100:.1f}', 6, '>') +
                         pad(f'{d["r3"] / g * 100:.1f}', 6, '>') +
                         pad(f'{d["r4"] / g * 100:.1f}', 6, '>') +
                         pad(f'{d["fly"] / g * 100:.1f}', 6, '>') +
                         pad(f'{fh:.2f}' if fh else '-', 6, '>') +
                         pad(f'{ft:.2f}' if ft else '-', 6, '>'))
    o.append('')
    o.append(line)
    return '\n'.join(o)


HELP_TXT = """未找到数据文件。请任选其一：

  方式 A（推荐，全自动）：安装 Google Drive 桌面版并登录，
      等待 tenhouarena/ladder_results.db 同步到本地后重新运行本脚本。

  方式 B（免安装）：浏览器打开 drive.google.com，
      在 My Drive/tenhouarena 里下载这两个文件到任意文件夹：
        ladder_results.db     （对局明细）
        ladder_state.json     （段位快照，可选）
      然后运行：
        python ladder_watch_local.py --db "文件路径\\ladder_results.db"

  脚本搜索过的位置：
{dirs}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=None, help='ladder_results.db 的本地路径')
    ap.add_argument('--state', default=None, help='ladder_state.json 的本地路径')
    ap.add_argument('--once', action='store_true', help='只打印一次')
    ap.add_argument('-n', '--interval', type=int, default=30, help='刷新间隔秒数')
    ap.add_argument('-w', '--width', type=int, default=0, help='输出宽度（0=自动探测）')
    a = ap.parse_args()

    W = a.width or shutil_width()

    db_path = Path(a.db) if a.db else find_file('ladder_results.db')
    if db_path is None or not Path(db_path).exists():
        dirs = '\n'.join(f'    {d}' for d in _candidate_dirs())
        print(HELP_TXT.format(dirs=dirs))
        return 1
    db_path = Path(db_path)

    state_path = Path(a.state) if a.state else None
    if state_path is None:
        # 优先在数据文件同目录找状态快照
        sib = db_path.parent / 'ladder_state.json'
        state_path = sib if sib.exists() else find_file('ladder_state.json')

    last_good = None
    while True:
        try:
            by, meta, st = collect(db_path, state_path)
            text = draw(by, meta, st, db_path, state_path, W)
            last_good = text
        except sqlite3.OperationalError as e:
            text = (last_good or '') + f'\n!! 数据文件暂时不可读（可能正在同步）: {e}\n'
        except Exception as e:
            text = (last_good or '') + f'\n!! 读取失败: {type(e).__name__}: {e}\n'

        if a.once:
            print(text)
            return 0
        sys.stdout.write('\033[2J\033[H')
        print(text)
        time.sleep(a.interval)


def shutil_width():
    try:
        import shutil
        return shutil.get_terminal_size(fallback=(120, 30)).columns
    except Exception:
        return 120


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已退出看板')
