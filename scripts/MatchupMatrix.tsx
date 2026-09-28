import React, { useState } from 'react';
import type { MatchupsData, MatchupCell } from '../../types/ladder';

interface Props {
  matchups: MatchupsData;
}

type RoomScope = 'all' | 'houou' | 'tokujou';

export const MatchupMatrix: React.FC<Props> = ({ matchups }) => {
  const [roomScope, setRoomScope] = useState<RoomScope>('all');
  const [hoveredPair, setHoveredPair] = useState<{ a: string; b: string; cell: MatchupCell } | null>(null);

  const models = matchups.models || [];
  const matrix = matchups.matrix || {};

  // 获取指定房间范围下的 cell 统计
  const getCellStats = (mA: string, mB: string) => {
    const raw = matrix[mA]?.[mB];
    if (!raw) return null;

    if (roomScope === 'all') {
      return {
        games: raw.games,
        wins_a: raw.wins_a,
        wins_b: raw.wins_b,
        win_rate: raw.win_rate,
        avg_pt_diff: raw.avg_pt_diff,
        total_pt_diff: raw.total_pt_diff,
        rawCell: raw,
      };
    }

    const rStats = raw.rooms?.[roomScope];
    if (!rStats) {
      return {
        games: 0,
        wins_a: 0,
        wins_b: 0,
        win_rate: 0.5,
        avg_pt_diff: 0.0,
        total_pt_diff: 0,
        rawCell: raw,
      };
    }

    return {
      games: rStats.games,
      wins_a: rStats.wins_a,
      wins_b: rStats.wins_b,
      win_rate: rStats.win_rate,
      avg_pt_diff: raw.avg_pt_diff, // pt diff 保持全量
      total_pt_diff: raw.total_pt_diff,
      rawCell: raw,
    };
  };

  // 根据胜率计算背景热力色
  const getCellBgColor = (winRate: number, games: number) => {
    if (games === 0) return 'transparent';
    const diff = winRate - 0.5; // -0.5 ~ +0.5
    if (Math.abs(diff) < 0.005) return 'rgba(150, 150, 150, 0.08)';

    // 缩放到 0 ~ 1（差值 0.15 即胜率 65% 时达到最高浓度）
    const intensity = Math.min(1, Math.abs(diff) / 0.15);
    const alpha = 0.08 + intensity * 0.35; // 0.08 ~ 0.43

    if (diff > 0) {
      // 优势：翡翠绿
      return `rgba(34, 197, 94, ${alpha.toFixed(2)})`;
    } else {
      // 劣势：玫瑰红
      return `rgba(239, 68, 68, ${alpha.toFixed(2)})`;
    }
  };

  // 模型别名简化显示
  const formatModelName = (name: string) => {
    return name
      .replace('distill_', 'd_')
      .replace('_infer', '')
      .replace('_clone_v1', '')
      .replace('_consensus_v3', '_cs_v3');
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 头部控制栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
            物理模型两两同桌对决矩阵（Head-to-Head Matchup）
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            口径：同桌对决中，若 A 顺位高于 B（名次更靠前）记 A 胜；格内第一行显示 A 胜率，第二行显示场均相对 PT 差（A 净收益）。
          </div>
        </div>

        {/* 房间范围切换 */}
        <div style={{ display: 'flex', gap: 6, background: 'var(--bg-muted, rgba(0,0,0,0.04))', padding: 3, borderRadius: 6 }}>
          {(['all', 'houou', 'tokujou'] as RoomScope[]).map((scope) => {
            const labels: Record<RoomScope, string> = {
              all: '全卓对战 (全部)',
              houou: '凤凰卓 (高段位)',
              tokujou: '特上卓 (中坚层)',
            };
            const active = roomScope === scope;
            return (
              <button
                key={scope}
                type="button"
                onClick={() => setRoomScope(scope)}
                style={{
                  padding: '4px 10px',
                  fontSize: 12,
                  fontWeight: active ? 600 : 400,
                  borderRadius: 4,
                  border: 'none',
                  background: active ? 'var(--bg-surface, #fff)' : 'transparent',
                  color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                  boxShadow: active ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                {labels[scope]}
              </button>
            );
          })}
        </div>
      </div>

      {/* 矩阵表格容器 */}
      <div style={{ overflowX: 'auto', border: '1px solid var(--border-subtle, rgba(0,0,0,0.1))', borderRadius: 8, background: 'var(--bg-surface, #fff)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, textAlign: 'center', minWidth: 980 }}>
          <thead>
            <tr style={{ background: 'var(--bg-muted, rgba(0,0,0,0.02))', borderBottom: '2px solid var(--border-subtle, rgba(0,0,0,0.1))' }}>
              <th style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', minWidth: 150 }}>
                胜方 (行) \ 负方 (列)
              </th>
              {models.map((mB) => (
                <th key={mB} style={{ padding: '8px 4px', fontWeight: 600, color: 'var(--text-secondary)', width: 75 }} title={mB}>
                  {formatModelName(mB)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {models.map((mA) => (
              <tr key={mA} style={{ borderBottom: '1px solid var(--border-subtle, rgba(0,0,0,0.06))' }}>
                {/* 纵坐标：模型 A */}
                <td style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap' }} title={mA}>
                  {formatModelName(mA)}
                </td>

                {/* 各列：模型 B */}
                {models.map((mB) => {
                  if (mA === mB) {
                    return (
                      <td key={mB} style={{ padding: '6px 2px', background: 'rgba(0,0,0,0.02)', color: 'var(--text-muted, #aaa)' }}>
                        —
                      </td>
                    );
                  }

                  const stats = getCellStats(mA, mB);
                  if (!stats || stats.games === 0) {
                    return (
                      <td key={mB} style={{ padding: '6px 2px', color: 'var(--text-muted, #ccc)' }} title="双方无同桌交手记录">
                        0局
                      </td>
                    );
                  }

                  const isAdvantage = stats.win_rate >= 0.5;
                  const winRatePct = (stats.win_rate * 100).toFixed(1);
                  const ptDiffStr = `${stats.avg_pt_diff >= 0 ? '+' : ''}${stats.avg_pt_diff.toFixed(1)}`;
                  const bgColor = getCellBgColor(stats.win_rate, stats.games);

                  return (
                    <td
                      key={mB}
                      onMouseEnter={() => setHoveredPair({ a: mA, b: mB, cell: stats.rawCell })}
                      onMouseLeave={() => setHoveredPair(null)}
                      style={{
                        padding: '5px 2px',
                        background: bgColor,
                        cursor: 'pointer',
                        transition: 'background 0.1s ease',
                      }}
                    >
                      <div style={{ fontWeight: 700, color: isAdvantage ? '#15803d' : '#b91c1c', lineHeight: 1.1 }}>
                        {winRatePct}%
                      </div>
                      <div style={{ fontSize: 9, color: stats.avg_pt_diff >= 0 ? '#166534' : '#991b1b', opacity: 0.85, marginTop: 1 }}>
                        {ptDiffStr}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 悬浮微观详情卡片 */}
      {hoveredPair ? (
        <div
          style={{
            padding: 12,
            background: 'var(--bg-surface, #fff)',
            border: '1px solid var(--border-subtle, rgba(0,0,0,0.15))',
            borderRadius: 6,
            boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: 12,
          }}
        >
          <div>
            <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{hoveredPair.a}</span>
            <span style={{ margin: '0 8px', color: 'var(--text-secondary)' }}>vs</span>
            <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{hoveredPair.b}</span>
            <span style={{ marginLeft: 16, color: 'var(--text-secondary)' }}>
              双方同桌：<strong style={{ color: 'var(--text-primary)' }}>{hoveredPair.cell.games}</strong> 半庄
            </span>
          </div>

          <div style={{ display: 'flex', gap: 20 }}>
            <div>
              胜负战绩：<strong>{hoveredPair.cell.wins_a}</strong> 胜 / <strong>{hoveredPair.cell.wins_b}</strong> 负
              （胜率 <strong>{(hoveredPair.cell.win_rate * 100).toFixed(1)}%</strong>）
            </div>
            <div>
              场均 PT 净差：
              <strong style={{ color: hoveredPair.cell.avg_pt_diff >= 0 ? '#15803d' : '#b91c1c' }}>
                {hoveredPair.cell.avg_pt_diff >= 0 ? '+' : ''}
                {hoveredPair.cell.avg_pt_diff.toFixed(2)} pt
              </strong>
            </div>
            <div>
              累计 PT 输送差额：
              <strong style={{ color: hoveredPair.cell.total_pt_diff >= 0 ? '#15803d' : '#b91c1c' }}>
                {hoveredPair.cell.total_pt_diff >= 0 ? '+' : ''}
                {hoveredPair.cell.total_pt_diff} pt
              </strong>
            </div>
            {hoveredPair.cell.rooms && (
              <div style={{ color: 'var(--text-secondary)' }}>
                凤凰 <strong>{hoveredPair.cell.rooms.houou.games}</strong> 局 / 特上 <strong>{hoveredPair.cell.rooms.tokujou.games}</strong> 局
              </div>
            )}
          </div>
        </div>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--text-muted, #888)', fontStyle: 'italic', padding: '4px 0' }}>
          💡 提示：将鼠标悬停在表格任意单元格上方，可查看两款模型的详细对战胜负手、PT 累计输送量与分房间交手记录。
        </div>
      )}
    </div>
  );
};
