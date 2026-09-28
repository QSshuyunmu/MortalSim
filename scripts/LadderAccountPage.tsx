// src/replay_ui/src/pages/LadderAccountPage.tsx
// 账号详情：PT/Rating 曲线、顺位分布、行为指标、最近对局。
import { useMemo, type CSSProperties } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ladderApi } from '../api/ladderApi';
import { LadderSeasonNotice } from '../components/Ladder/LadderSeasonNotice';
import { LadderSeasonContextBanner } from '../components/Ladder/LadderSeasonContextBanner';
import { LadderSnapshotStatus } from '../components/Ladder/LadderSnapshotStatus';
import { PageHeader, PageShell, SectionTitle } from '../components/Layout/PageScaffold';
import { TrendChart } from '../components/Ladder/TrendChart';
import { useLadderSeasonCatalog } from '../hooks/useLadderSeasonCatalog';
import { useVisibleLiveQuery } from '../hooks/useVisibleLiveQuery';
import { routes, withLadderSeason } from '../routes';
import type { LadderAccountDetail, LadderAccountRow, LadderSeasonScoring } from '../types/ladder';
import { modelDisplayName } from '../utils/modelDisplay';
import { fmtPt, fmtRate, fmtRating, fmtSignedInt } from '../utils/ladderFormat';

const RECENT_GAMES_LIMIT = 50;

export function LadderAccountPage() {
  const { accountId } = useParams();
  const navigate = useNavigate();

  const catalog = useLadderSeasonCatalog();
  const { seasons, activeSeasonId, loading: catalogLoading } = catalog;

  // 完整 LadderAccountDetail 为单一原子状态：snapshot 更新时 account/curve/
  // rank_distribution/recent_games/season 一起替换，避免跨 snapshot 混合。
  const detailQuery = useVisibleLiveQuery<LadderAccountDetail>({
    enabled: Boolean(activeSeasonId && accountId),
    queryKey: `account:${activeSeasonId ?? ''}:${accountId ?? ''}:${RECENT_GAMES_LIMIT}`,
    load: useMemo(
      () => (signal: AbortSignal) => {
        if (!activeSeasonId || !accountId) return Promise.reject(new Error('missing season or account'));
        return ladderApi.getAccount(activeSeasonId, accountId, RECENT_GAMES_LIMIT, signal);
      },
      [activeSeasonId, accountId],
    ),
  });
  const detail = detailQuery.data;
  const loading = detailQuery.loading;

  const account = detail?.account;
  const activeSeason = seasons.find((s) => s.season_id === activeSeasonId);
  const seasonProblem = activeSeason?.readiness?.state !== 'ready' ? activeSeason?.readiness : null;
  // 未就绪抑制裸 409（结构化 Notice 展示原因）；catalog 500 / 实体 404 仍显示 alert
  const visibleError = catalog.error ?? (seasonProblem ? null : detailQuery.error);
  const backToLadder = () => navigate(withLadderSeason(routes.ladder, activeSeasonId));
  const openModel = () => {
    if (account) navigate(withLadderSeason(routes.ladderModel(account.model_id), activeSeasonId));
  };

  const ptTarget = account?.pt_target ?? null;
  const ptProgress = ptTarget !== null && ptTarget > 0 && account
    ? Math.max(0, Math.min(100, (account.pt_current / ptTarget) * 100))
    : 0;
  // 仅当本账号的对局记录含个人计分档位时，才展示"计分档位"列
  const hasTierData = detail?.recent_games.some((game) => Boolean(game.pt_tier)) ?? false;

  return (
    <PageShell width={1180}>
      {/* R11-F Repair：season-context banner（历史/非当前/无正式赛季）三页统一 */}
      <LadderSeasonContextBanner
        activeSeasonId={activeSeasonId}
        activeSeason={activeSeason}
        defaultSeasonId={catalog.defaultSeasonId}
        defaultSeason={seasons.find((s) => s.season_id === catalog.defaultSeasonId)}
      />
      <PageHeader
        eyebrow="Account Profile"
        title={account?.display_name ?? '账号详情'}
        description={detail ? `${detail.season.title || detail.season.season_id} · ${modelDisplayName(account?.model_id ?? '')}` : undefined}
        actions={(
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="button" onClick={backToLadder} className="btn-secondary" style={actionButtonStyle}>
              返回天梯
            </button>
            {account && (
              <button type="button" onClick={openModel} className="btn-secondary" style={actionButtonStyle}>
                模型详情
              </button>
            )}
          </div>
        )}
      />

      {/* 赛季目录错误与账号查询错误统一展示；未就绪抑制裸 409（结构化 Notice 展示） */}
      {visibleError && (
        <div role="alert" style={{ color: 'var(--error)', fontSize: 13, marginBottom: 10 }}>{visibleError}</div>
      )}
      {(!visibleError && catalogLoading && !detailQuery.error) || (loading && activeSeasonId && accountId) ? (
        <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: 20, textAlign: 'center' }}>加载中...</div>
      ) : null}

      {/* 无默认 / 未就绪：结构化状态展示（实体 payload 成功时主体优先，不遮挡） */}
      {!catalogLoading && !visibleError && !detail && !(loading && activeSeasonId && accountId) && (
        <LadderSeasonNotice
          seasons={seasons}
          activeSeason={seasons.find((s) => s.season_id === activeSeasonId)}
          defaultSeasonId={catalog.defaultSeasonId}
        />
      )}

      {!loading && detail && account && (
        <>
          {/* 账号概览 */}
          <section className="card" style={{ padding: 14, marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
              <div style={{ minWidth: 260 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-primary)' }}>{account.display_name}</span>
                  {account.rank_name && (
                    <span style={rankBadgeStyle}>
                      {account.rank_name}
                      {account.tenhou_reached ? ' 👑' : ''}
                    </span>
                  )}
                  {account.promotions ? <span style={progressionBadgeStyle('promotion')}>升段 ×{account.promotions}</span> : null}
                  {account.demotions ? <span style={progressionBadgeStyle('demotion')}>降段 ×{account.demotions}</span> : null}
                  {account.highest_rank_id && account.highest_rank_id !== account.rank_id && (
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>历史最高 {account.highest_rank_id}</span>
                  )}
                </div>
                <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
                  模型 <button type="button" onClick={openModel} style={linkButtonStyle}>{modelDisplayName(account.model_id)}</button>
                </div>
                {account.checkpoint && (
                  <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-muted)', fontFamily: 'Menlo, Consolas, monospace', wordBreak: 'break-all' }}>
                    {account.checkpoint}
                  </div>
                )}
                <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
                  对局数 <b style={{ color: 'var(--text-primary)' }}>{account.games}</b>
                  {detail.season.scoring && (
                    <span style={{ color: 'var(--text-muted)' }}> · {scoringProfileLabel(detail.season.scoring)}</span>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'flex-start' }}>
                <div style={{ minWidth: 200 }}>
                  {ptTarget === null ? (
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--success)' }}>天凤位 · 不再计算 PT</div>
                  ) : (
                    <>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>
                        PT（{fmtPt(account.pt_current)} / {fmtPt(ptTarget)}）
                      </div>
                      <div style={{ height: 8, borderRadius: 4, background: 'var(--page-bg)', border: '1px solid var(--border)', overflow: 'hidden' }}>
                        <div style={{ width: `${ptProgress}%`, height: '100%', background: (account?.pt_current ?? 0) < ptTarget ? 'var(--accent)' : 'var(--success)' }} />
                      </div>
                      <div style={{ marginTop: 3, fontSize: 11, color: 'var(--text-muted)' }}>
                        {account.pt_current >= ptTarget ? '已达到升段 PT' : `距升段还差 ${fmtPt(ptTarget - account.pt_current)}`}
                      </div>
                    </>
                  )}
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Rating</div>
                  <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--text-primary)', fontFamily: 'Menlo, Consolas, monospace' }}>
                    {fmtRating(account.rating)}
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* PT / Rating 曲线 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12, marginBottom: 12 }}>
            <section className="card" style={{ padding: 12 }}>
              <TrendChart title="PT 曲线" points={detail.curve.map((point) => point.pt)} formatValue={fmtPt} />
            </section>
            <section className="card" style={{ padding: 12 }}>
              <TrendChart title="Rating 曲线" points={detail.curve.map((point) => point.rating)} formatValue={fmtRating} color="var(--seat-2)" />
            </section>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12, marginBottom: 12 }}>
            {/* 顺位分布 */}
            <section className="card" style={{ padding: 12 }}>
              <SectionTitle title="顺位分布" />
              {detail.rank_distribution.map((count, index) => {
                const total = Math.max(1, account.games);
                const pct = (count / total) * 100;
                return (
                  <div key={index} style={{ display: 'grid', gridTemplateColumns: '44px 1fr 76px', gap: 8, alignItems: 'center', marginBottom: 5 }}>
                    <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{['一位', '二位', '三位', '四位'][index]}</span>
                    <div style={{ height: 7, borderRadius: 4, background: 'var(--page-bg)', border: '1px solid var(--border)', overflow: 'hidden' }}>
                      <div style={{ width: `${pct}%`, height: '100%', background: index === 0 ? 'var(--success)' : index === 3 ? 'var(--error)' : 'var(--accent)' }} />
                    </div>
                    <span style={{ fontSize: 11, color: 'var(--text-primary)', textAlign: 'right', fontFamily: 'Menlo, Consolas, monospace' }}>
                      {count} · {pct.toFixed(1)}%
                    </span>
                  </div>
                );
              })}
            </section>

            {/* 行为指标 */}
            <section className="card" style={{ padding: 12 }}>
              <SectionTitle title="行为与风格指标" description={statsCoverageLabel(account)} />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 14px', fontSize: 12 }}>
                {[
                  ['和率', fmtRate(account.agari_rate)],
                  ['放铳率', fmtRate(account.houjuu_rate)],
                  ['副露率', fmtRate(account.fuuro_rate)],
                  ['立直率', fmtRate(account.riichi_rate)],
                  ['副露后和率', fmtRate(account.agari_rate_after_fuuro)],
                  ['副露后放铳率', fmtRate(account.houjuu_rate_after_fuuro)],
                  ['立直后和率', fmtRate(account.agari_rate_after_riichi)],
                  ['立直后放铳率', fmtRate(account.houjuu_rate_after_riichi)],
                  ['平均和牌打点', account.avg_point_per_agari ? `${Math.round(account.avg_point_per_agari).toLocaleString()} 点` : '—'],
                  ['平均放铳失点', account.avg_point_per_houjuu ? `${Math.round(account.avg_point_per_houjuu).toLocaleString()} 点` : '—'],
                  ['和铳收益比', account.gain_loss_ratio ? account.gain_loss_ratio.toFixed(2) : '—'],
                  ['默听和牌率', fmtRate(account.dama_agari_rate)],
                  ['被飞率', fmtRate(account.tobi_rate)],
                  ['流局率', fmtRate(account.ryukyoku_rate)],
                  ['平均立直巡目', account.avg_riichi_jun ? `${account.avg_riichi_jun.toFixed(1)} 巡` : '—'],
                  ['平均和了巡目', account.avg_agari_jun ? `${account.avg_agari_jun.toFixed(1)} 巡` : '—'],
                  ['平均放铳巡目', account.avg_houjuu_jun ? `${account.avg_houjuu_jun.toFixed(1)} 巡` : '—'],
                  ['总分数变化', fmtSignedInt(account.total_delta_score)],
                  ['累计PTΔ', account.total_pt_delta === null || account.total_pt_delta === undefined ? '—' : fmtSignedInt(account.total_pt_delta)],
                  ['平均每场PTΔ', account.avg_pt_delta === null || account.avg_pt_delta === undefined ? '—' : (account.avg_pt_delta >= 0 ? '+' : '') + account.avg_pt_delta.toFixed(1)],
                  ['统计总局数', account.stats_rounds ? `${account.stats_rounds.toLocaleString()} 局 (${account.stats_games ?? 0} 半庄)` : '—'],
                ].map(([label, value]) => (
                  <div key={label} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, borderBottom: '1px dashed var(--border)', paddingBottom: 3 }}>
                    <span style={{ color: 'var(--text-muted)' }}>{label}</span>
                    <span style={{ color: 'var(--text-primary)', fontWeight: 700, fontFamily: 'Menlo, Consolas, monospace' }}>{value}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>

          {/* 最近对局 */}
          <section className="card" style={{ padding: 12 }}>
            <SectionTitle title={`最近对局（${detail.recent_games.length} 场）`} description="按时间倒序，仅展示最近场次，不加载全部牌谱。" />
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                    <th style={thStyle}>场次</th>
                    <th style={thStyle}>顺位</th>
                    <th style={thStyle}>段位变化</th>
                    {hasTierData && <th style={thStyle}>计分档位</th>}
                    <th style={{ ...thStyle, textAlign: 'right' }}>终局分</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>分数Δ</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>PTΔ</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>PT</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Rating</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.recent_games.map((game) => (
                    <tr key={game.game_index} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ ...tdStyle, fontFamily: 'Menlo, Consolas, monospace' }}>#{game.game_index}</td>
                      <td style={{ ...tdStyle, fontWeight: 800, color: game.rank === 1 ? 'var(--success)' : game.rank === 4 ? 'var(--error)' : 'var(--text-primary)' }}>
                        {game.rank} 位
                      </td>
                      <td style={{ ...tdStyle }}>
                        {game.rank_before && game.rank_after ? (
                          <span>
                            {game.rank_before}
                            <span style={{ color: 'var(--text-muted)' }}> → </span>
                            {game.rank_after}
                            {game.transition === 'promotion' && <span style={{ color: 'var(--success)' }}> ⬆</span>}
                            {game.transition === 'demotion' && <span style={{ color: 'var(--error)' }}> ⬇</span>}
                            {game.transition === 'tenhou' && <span style={{ color: 'var(--accent)' }}> 👑</span>}
                          </span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>—</span>
                        )}
                      </td>
                      {hasTierData && (
                        <td style={{ ...tdStyle, color: 'var(--text-muted)' }}>
                          {game.pt_tier ? tierDisplay(game.pt_tier, game.positive_pt) : '—'}
                        </td>
                      )}
                      <td style={{ ...tdStyle, ...numStyle }}>{game.final_score.toLocaleString()}</td>
                      <td style={{ ...tdStyle, ...numStyle }}>{fmtSignedInt(game.score_delta)}</td>
                      <td style={{ ...tdStyle, ...numStyle }}>{fmtSignedInt(game.pt_delta)}</td>
                      <td style={{ ...tdStyle, ...numStyle }}>{fmtPt(game.pt_after)}</td>
                      <td style={{ ...tdStyle, ...numStyle }}>{fmtRating(game.rating_after)}</td>
                    </tr>
                  ))}
                  {detail.recent_games.length === 0 && (
                    <tr><td colSpan={hasTierData ? 9 : 8} style={{ ...tdStyle, color: 'var(--text-muted)', textAlign: 'center', padding: 14 }}>暂无对局记录</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {/* 快照状态：数据更新时间 / snapshot ID / 已计入场数 */}
          <LadderSnapshotStatus season={detail.season} refreshing={detailQuery.refreshing} />
        </>
      )}
    </PageShell>
  );
}

const actionButtonStyle: CSSProperties = {
  height: 32,
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  padding: '0 12px',
};

const rankBadgeStyle: CSSProperties = {
  border: '1px solid var(--accent-border)',
  borderRadius: 4,
  background: 'var(--accent-bg)',
  color: 'var(--accent)',
  fontSize: 11,
  fontWeight: 800,
  padding: '2px 6px',
};

const progressionBadgeStyle = (kind: 'promotion' | 'demotion'): CSSProperties => ({
  border: `1px solid ${kind === 'promotion' ? 'rgba(79,195,138,0.45)' : 'rgba(240,112,112,0.45)'}`,
  borderRadius: 4,
  background: kind === 'promotion' ? 'rgba(79,195,138,0.10)' : 'rgba(240,112,112,0.10)',
  color: kind === 'promotion' ? 'var(--success)' : 'var(--negative)',
  fontSize: 11,
  fontWeight: 700,
  padding: '2px 6px',
});

const TIER_ZH: Record<string, string> = {
  'ippan-equivalent': '一般',
  'joukyuu-equivalent': '上级',
  'tokujou-equivalent': '特上',
  'houou-equivalent': '凤凰',
};

function tierDisplay(tier: string, positivePt?: number[] | null): string {
  const name = TIER_ZH[tier] ?? tier.replace('-equivalent', '');
  if (positivePt && positivePt.length === 3) {
    return `${name}档 · +${positivePt[0]}/+${positivePt[1]}/${positivePt[2]}`;
  }
  return `${name}档`;
}

function scoringProfileLabel(scoring: LadderSeasonScoring): string {
  if (scoring.system === 'tenhou_rank_progression') {
    return `天凤式段位进度 ${scoring.version || ''} · 个人档位结算`;
  }
  if (scoring.system) {
    return [scoring.system, scoring.version, scoring.tier_policy].filter(Boolean).join(' · ');
  }
  return scoring.pt_profile || 'legacy';
}

// R12-A：详细牌谱统计覆盖率披露——行为指标的分母只含实际算出完整统计的场数。
function statsCoverageLabel(account: LadderAccountRow): string | undefined {
  if (account.stats_total_games === null || account.stats_total_games === undefined) {
    return undefined;
  }
  const games = account.stats_games ?? 0;
  const coverage = account.stats_coverage;
  const suffix = coverage === null || coverage === undefined ? '' : `（${Math.round(coverage * 100)}% 覆盖）`;
  return `详细牌谱统计：${games} / ${account.stats_total_games} 场${suffix}`;
}

const linkButtonStyle: CSSProperties = {
  border: 'none',
  background: 'none',
  padding: 0,
  color: 'var(--accent)',
  fontSize: 12,
  fontWeight: 700,
  cursor: 'pointer',
  textDecoration: 'underline',
};

const thStyle: CSSProperties = {
  padding: '6px 8px',
  fontSize: 11,
  fontWeight: 700,
  whiteSpace: 'nowrap',
};

const tdStyle: CSSProperties = {
  padding: '6px 8px',
  color: 'var(--text-primary)',
  whiteSpace: 'nowrap',
};

const numStyle: CSSProperties = {
  textAlign: 'right',
  fontFamily: 'Menlo, Consolas, monospace',
};

