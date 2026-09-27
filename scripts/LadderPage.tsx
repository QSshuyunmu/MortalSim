// src/replay_ui/src/pages/LadderPage.tsx
// 天梯榜：赛季账号排名 + 模型展示性聚合。
import { useMemo, useState, type CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';
import { ladderApi } from '../api/ladderApi';
import { LadderSnapshotStatus } from '../components/Ladder/LadderSnapshotStatus';
import { LadderSeasonNotice } from '../components/Ladder/LadderSeasonNotice';
import { LadderSeasonContextBanner } from '../components/Ladder/LadderSeasonContextBanner';
import { PageHeader, PageShell } from '../components/Layout/PageScaffold';
import { useLadderSeasonCatalog } from '../hooks/useLadderSeasonCatalog';
import { useVisibleLiveQuery } from '../hooks/useVisibleLiveQuery';
import { routes, withLadderSeason } from '../routes';
import type { LadderAccountRow, LadderModelSummary, LadderResponse, LadderSeasonScoring } from '../types/ladder';
import { modelDisplayName } from '../utils/modelDisplay';
import { fmtPt, fmtRank, fmtRate, fmtRating } from '../utils/ladderFormat';

const SORT_OPTIONS = [
  { value: 'rank', label: '按段位' },
  { value: 'rating', label: '按 Rating' },
  { value: 'avg_rank', label: '按平均顺位' },
  { value: 'games', label: '按场数' },
];

export function LadderPage() {
  const navigate = useNavigate();
  const [sort, setSort] = useState('rank');
  // R11-F：正式榜以账号为主体；模型汇总为二级分析视图
  const [tab, setTab] = useState<'accounts' | 'models'>('accounts');

  const catalog = useLadderSeasonCatalog();
  const { seasons, activeSeasonId, loading: catalogLoading } = catalog;

  // 共享可见性实时查询：页面可见时每 30 秒静默刷新，hidden 跳过，
  // 恢复可见立即刷新，轮询失败保留旧数据，queryKey 变化清空旧实体重新加载。
  const ladderQuery = useVisibleLiveQuery<LadderResponse>({
    enabled: Boolean(activeSeasonId),
    queryKey: `ladder:${activeSeasonId ?? ''}:${sort}`,
    load: useMemo(
      () => (signal: AbortSignal) => {
        if (!activeSeasonId) return Promise.reject(new Error('no active season'));
        return ladderApi.getLadder(activeSeasonId, sort, signal);
      },
      [activeSeasonId, sort],
    ),
  });
  const ladder = ladderQuery.data;
  const loading = ladderQuery.loading;

  const switchSeason = (seasonId: string) => {
    if (!seasonId) return;
    navigate(`${routes.ladder}?season=${encodeURIComponent(seasonId)}`);
  };

  const openAccount = (row: LadderAccountRow) => {
    navigate(withLadderSeason(routes.ladderAccount(row.account_id), activeSeasonId));
  };

  const openModel = (model: LadderModelSummary) => {
    navigate(withLadderSeason(routes.ladderModel(model.model_id), activeSeasonId));
  };

  // 赛季目录错误与榜单查询错误统一展示（查询轮询失败不进入 query.error）
  const activeSeason = seasons.find((s) => s.season_id === activeSeasonId);
  const seasonProblem = activeSeason?.readiness?.state !== 'ready' ? activeSeason?.readiness : null;
  // 未就绪时抑制裸 409 alert（结构化 Notice 已展示原因）；真正 404/500 仍显示
  const visibleError = catalog.error ?? (seasonProblem ? null : ladderQuery.error);
  const catalogLoaded = !catalog.loading;
  // R11-F：completed/archived 是历史赛季，选择器里明显标识（banner 由
  // LadderSeasonContextBanner 统一处理）
  const isHistoricalSeason = (season: { status?: string }) =>
    season.status === 'completed' || season.status === 'archived';

  return (
    <PageShell width={1240}>
      <PageHeader
        eyebrow="Model Ladder"
        title="天梯榜"
        description={ladder?.season.notes || ladder?.season.title || '赛季账号 PT / Rating 排名。'}
        actions={(
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {seasons.length > 0 && (
              <select
                value={activeSeasonId ?? ''}
                onChange={(event) => switchSeason(event.target.value)}
                style={selectStyle}
              >
                {!catalog.defaultSeasonId && seasons.length > 1 && (
                  <option value="">选择赛季…</option>
                )}
                {seasons.map((season) => (
                  <option key={season.season_id} value={season.season_id}>
                    {season.title || season.season_id}
                    {season.is_default ? '（当前）' : ''}
                    {isHistoricalSeason(season) ? ' · 历史赛季' : ''}
                    {season.data_ready === false ? ' · 未就绪' : ''}
                  </option>
                ))}
              </select>
            )}
            {/* R11-F：账号排名（正式） / 模型汇总（二级分析） */}
            <div style={{ display: 'flex', gap: 4 }}>
              {([
                ['accounts', '账号排名'],
                ['models', '模型汇总'],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setTab(value)}
                  style={sortButtonStyle(tab === value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              {SORT_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setSort(option.value)}
                  style={sortButtonStyle(sort === option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        )}
      />

      {/* R11-F Repair：统一的 season-context banner——显式 ?season= 查看非 default
          赛季（含 running）时，明确它不是当前正式榜；default=null 也持续提示。 */}
      {catalogLoaded && activeSeasonId && (
        <LadderSeasonContextBanner
          activeSeasonId={activeSeasonId}
          activeSeason={activeSeason}
          defaultSeasonId={catalog.defaultSeasonId}
          defaultSeason={seasons.find((s) => s.season_id === catalog.defaultSeasonId)}
        />
      )}

      {visibleError && <div role="alert" style={{ color: 'var(--error)', fontSize: 13, marginBottom: 10 }}>{visibleError}</div>}
      {(!visibleError && catalogLoading) || (loading && activeSeasonId) ? (
        <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: 20, textAlign: 'center' }}>加载中...</div>
      ) : null}

      {/* 无默认且多赛季：要求用户选择，不自动请求数组首项 */}
      {catalogLoaded && !activeSeasonId && !visibleError && (
        <LadderSeasonNotice
          seasons={seasons}
          activeSeason={undefined}
          defaultSeasonId={catalog.defaultSeasonId}
        />
      )}

      {/* 默认赛季未就绪 / 数据损坏：结构化原因展示（主体可继续轮询恢复） */}
      {!loading && !ladder && activeSeasonId && (
        <LadderSeasonNotice
          seasons={seasons}
          activeSeason={seasons.find((s) => s.season_id === activeSeasonId)}
          defaultSeasonId={catalog.defaultSeasonId}
        />
      )}

      {!loading && ladder && (
        <>
          {/* 模型汇总（二级分析视图；不出现 #1/#2 正式名次） */}
          {tab === 'models' && (
            <>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                模型汇总（二级聚合——同一模型多个账号各自独立排名，此处只做分析，不是正式名次）
                <span style={{ marginLeft: 6 }}>点击模型卡片查看账号明细 →</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10, marginBottom: 12 }}>
                {ladder.models.map((model) => (
                  <button
                    key={model.model_id}
                    type="button"
                    onClick={() => openModel(model)}
                    style={modelCardStyle}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 800, color: 'var(--text-primary)' }}>{modelDisplayName(model.model_id)}</span>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{model.accounts} 账号 · {model.games} 场</span>
                    </div>
                    <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
                      {model.avg_pt !== null && (
                        <span>均PT <b style={modelValueStyle}>{fmtPt(model.avg_pt)}</b></span>
                      )}
                      <span>最高 <b style={modelValueStyle}>{model.highest_rank_name || model.highest_rank_id || '—'}</b></span>
                      <span>中位 <b style={modelValueStyle}>{model.median_rank_name || '—'}</b></span>
                      <span>均R <b style={modelValueStyle}>{fmtRating(model.avg_rating)}</b></span>
                      <span>均顺位 <b style={modelValueStyle}>{fmtRank(model.avg_rank)}</b></span>
                    </div>
                    {model.rank_distribution && Object.keys(model.rank_distribution).length > 0 && (
                      <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                        {Object.entries(model.rank_distribution).map(([name, count]) => (
                          <span key={name} style={{ fontSize: 10, color: 'var(--text-muted)', border: '1px solid var(--border)', borderRadius: 4, padding: '1px 5px' }}>
                            {name} ×{count}
                          </span>
                        ))}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </>
          )}

          {/* 账号天梯（正式排名主体） */}
          {tab === 'accounts' && (
            <>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                账号排名（正式）——每个 Account 独立排名；同模型账号不合并。
              </div>
              <div style={{ border: '1px solid var(--border)', borderRadius: 7, overflowX: 'auto', background: 'var(--card-bg)' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, minWidth: 1060 }}>
                  <thead>
                    <tr style={{ color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                      <th style={thStyle}>排名</th>
                      <th style={thStyle}>账号</th>
                      <th style={thStyle}>模型</th>
                      <th style={thStyle}>段位</th>
                      <th style={thStyle}>最高段</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>凤局</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>凤安定</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>特局</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>特安定</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>PT</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>升段进度</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Rating</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>场数</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>平均顺位</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>一位率</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>四位率</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>和率</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>放铳率</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>副露率</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>立直率</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ladder.accounts.map((row) => (
                      <tr
                        key={row.account_id}
                        onClick={() => openAccount(row)}
                        style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                        title={`查看 ${row.display_name} 账号详情`}
                      >
                        <td style={{ ...tdStyle, fontWeight: 800, color: 'var(--text-muted)' }}>{row.rank_position}</td>
                        <td style={{ ...tdStyle, fontWeight: 800, color: 'var(--accent)' }}>{row.display_name}</td>
                        <td style={{ ...tdStyle, color: 'var(--text-secondary)' }}>{modelDisplayName(row.model_id)}</td>
                        <td style={{ ...tdStyle, fontWeight: 800 }}>
                          {row.rank_name || '七段'}
                          {row.tenhou_reached ? ' 👑' : ''}
                        </td>
                        <td style={{ ...tdStyle, color: 'var(--text-secondary)' }}>
                          {row.highest_rank_name || row.rank_name || '—'}
                        </td>
                        <td style={{ ...tdStyle, ...numStyle, color: 'var(--text-secondary)' }}
                            title={stableDanTitle(row, 'houou')}>
                          {row.games_houou ?? 0}
                        </td>
                        <td style={{ ...tdStyle, ...numStyle, color: 'var(--text-secondary)' }}
                            title={stableDanTitle(row, 'houou')}>
                          {row.stable_dan_houou !== null && row.stable_dan_houou !== undefined
                            ? row.stable_dan_houou.toFixed(2) : '—'}
                        </td>
                        <td style={{ ...tdStyle, ...numStyle, color: 'var(--text-secondary)' }}
                            title={stableDanTitle(row, 'tokujou')}>
                          {row.games_tokujou ?? 0}
                        </td>
                        <td style={{ ...tdStyle, ...numStyle, color: 'var(--text-secondary)' }}
                            title={stableDanTitle(row, 'tokujou')}>
                          {row.stable_dan_tokujou !== null && row.stable_dan_tokujou !== undefined
                            ? row.stable_dan_tokujou.toFixed(2) : '—'}
                        </td>
                        <td style={{ ...tdStyle, ...numStyle, fontWeight: 800 }}>
                          {row.pt_target !== null ? fmtPt(row.pt_current) : '—'}
                        </td>
                        <td style={{ ...tdStyle, ...numStyle }}>
                          {row.pt_target !== null && row.pt_target > 0 ? (
                            <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                              {fmtPt(row.pt_current)}/{fmtPt(row.pt_target)}
                            </span>
                          ) : (
                            <span style={{ color: 'var(--success)' }}>天凤位</span>
                          )}
                        </td>
                        <td style={{ ...tdStyle, ...numStyle }}>{fmtRating(row.rating)}</td>
                        <td style={{ ...tdStyle, ...numStyle }}>{row.games}</td>
                        <td style={{ ...tdStyle, ...numStyle }}>{fmtRank(row.avg_rank)}</td>
                        <td style={{ ...tdStyle, ...numStyle }}>{fmtRate(row.rank_1_rate)}</td>
                        <td style={{ ...tdStyle, ...numStyle }}>{fmtRate(row.rank_4_rate)}</td>
                        <td style={{ ...tdStyle, ...numStyle }} title={statsCoverageTitle(row)}>{fmtRate(row.agari_rate)}</td>
                        <td style={{ ...tdStyle, ...numStyle }} title={statsCoverageTitle(row)}>{fmtRate(row.houjuu_rate)}</td>
                        <td style={{ ...tdStyle, ...numStyle }} title={statsCoverageTitle(row)}>{fmtRate(row.fuuro_rate)}</td>
                        <td style={{ ...tdStyle, ...numStyle }} title={statsCoverageTitle(row)}>{fmtRate(row.riichi_rate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {ladder.season.scoring && (
            <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
              {scoringLabel(ladder.season.scoring)}
            </div>
          )}

          {/* 快照状态：数据更新时间 / snapshot ID / 已计入场数 */}
          <LadderSnapshotStatus season={ladder.season} refreshing={ladderQuery.refreshing} />
        </>
      )}
    </PageShell>
  );
}

// R12-A：行为指标列悬停披露统计覆盖率（分母只含实际算出的完整牌谱场数）。
function statsCoverageTitle(row: LadderAccountRow): string | undefined {
  if (row.stats_total_games === null || row.stats_total_games === undefined) {
    return undefined;
  }
  const coverage = row.stats_coverage;
  const suffix = coverage === null || coverage === undefined ? '' : `（${Math.round(coverage * 100)}% 覆盖）`;
  return `详细牌谱统计：${row.stats_games ?? 0} / ${row.stats_total_games} 场${suffix}`;
}

/** 分卓安定段的说明：公式、样本量，以及未达门槛的原因。 */
function stableDanTitle(row: LadderAccountRow, room: 'houou' | 'tokujou'): string {
  const isHouou = room === 'houou';
  const roomName = isHouou ? '凤凰卓' : '特上卓';
  const formula = isHouou ? '(6×一位 + 3×二位) / 四位 − 2' : '(5×一位 + 2×二位) / 四位 − 2';
  const games = (isHouou ? row.games_houou : row.games_tokujou) ?? 0;
  const value = isHouou ? row.stable_dan_houou : row.stable_dan_tokujou;
  const head = `${roomName}安定段位 = ${formula}`;
  if (value === null || value === undefined) {
    return `${head}\n该卓 ${games} 局，未达样本门槛（需 ≥100 局且 ≥25 次四位）；`
      + `四位次数过少会使估计误差超过 ±3 段，故留空。`;
  }
  return `${head}\n基于该卓内 ${games} 局实测（未跨卓混算）。`;
}

function scoringLabel(scoring: LadderSeasonScoring): string {
  if (scoring.system === 'tenhou_rank_progression') {
    return `天凤式段位进度 ${scoring.version || ''} · 个人档位结算`;
  }
  if (scoring.system) {
    const parts = [scoring.system, scoring.version, scoring.tier_policy, scoring.game_length].filter(Boolean);
    return parts.join(' · ');
  }
  const parts: string[] = [scoring.pt_profile || 'pt'];
  if (scoring.pt_rank_deltas) parts.push(`PT ${scoring.pt_rank_deltas.join('/')}`);
  if (scoring.pt_initial != null) parts.push(`初始 ${scoring.pt_initial}`);
  if (scoring.pt_target != null) parts.push(`目标 ${scoring.pt_target}`);
  if (scoring.rank_name) parts.push(scoring.rank_name);
  return parts.join(' · ');
}

const selectStyle: CSSProperties = {
  height: 30,
  border: '1px solid var(--border)',
  borderRadius: 6,
  background: 'var(--card-bg)',
  color: 'var(--text-primary)',
  fontSize: 12,
  padding: '0 8px',
};

const sortButtonStyle = (active: boolean): CSSProperties => ({
  height: 30,
  padding: '0 10px',
  borderRadius: 6,
  border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
  background: active ? 'var(--accent-bg)' : 'var(--card-bg)',
  color: active ? 'var(--accent)' : 'var(--text-secondary)',
  fontSize: 12,
  fontWeight: active ? 800 : 600,
  cursor: 'pointer',
});

const modelCardStyle: CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 7,
  background: 'var(--card-bg)',
  padding: '10px 12px',
  textAlign: 'left',
  cursor: 'pointer',
};

const modelValueStyle: CSSProperties = { color: 'var(--text-primary)' };

const thStyle: CSSProperties = {
  padding: '7px 8px',
  fontSize: 11,
  fontWeight: 700,
  whiteSpace: 'nowrap',
};

const tdStyle: CSSProperties = {
  padding: '7px 8px',
  color: 'var(--text-primary)',
  whiteSpace: 'nowrap',
};

const numStyle: CSSProperties = {
  textAlign: 'right',
  fontFamily: 'Menlo, Consolas, monospace',
};
