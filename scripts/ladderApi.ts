// src/replay_ui/src/api/ladderApi.ts
import { ApiError } from './replayApi';
import type {
  ArchiveSummaryResponse,
  LadderAccountDetail,
  LadderModelDetail,
  LadderResponse,
  LadderSeasonConfig,
  LadderSeasonsResponse,
  MatchupsResponse,
  SeasonPreflightReport,
  SeasonRuntimeManifest,
  SeasonRuntimeStatusResponse,
} from '../types/ladder';

const API_BASE = '/api';

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: 'no-store',
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body);
  }
  return res.json();
}

export const ladderApi = {
  /** 已注册的评测赛季（含默认赛季与每赛季 readiness） */
  listSeasons: (signal?: AbortSignal): Promise<LadderSeasonsResponse> =>
    api('/ladder/seasons', { signal }),

  /** 赛季天梯榜：账号排名 + 模型展示性聚合 */
  getLadder: (seasonId: string, sort = 'pt', signal?: AbortSignal): Promise<LadderResponse> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}?sort=${encodeURIComponent(sort)}`, { signal }),

  /** 账号详情：聚合指标 + 曲线 + 最近对局 */
  getAccount: (seasonId: string, accountId: string, recentGames = 50, signal?: AbortSignal): Promise<LadderAccountDetail> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/accounts/${encodeURIComponent(accountId)}?recent_games=${recentGames}`, { signal }),

  /** 模型详情：账号横向对比 + 可选联赛聚合 */
  getModel: (seasonId: string, modelId: string, signal?: AbortSignal): Promise<LadderModelDetail> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/models/${encodeURIComponent(modelId)}`, { signal }),

  /** 模型两两同桌对决胜率与 PT 关系矩阵 */
  getMatchups: (seasonId: string, signal?: AbortSignal): Promise<MatchupsResponse> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/matchups`, { signal }),

  // ---- R11-E Season Manager（canonical runtime registry 写侧） ----
  getSeasonConfig: (seasonId: string): Promise<LadderSeasonConfig> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/config`),
  getSeasonPreflight: (seasonId: string): Promise<SeasonPreflightReport> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/preflight`),
  getSeasonManifest: (seasonId: string): Promise<SeasonRuntimeManifest> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/manifest`),
  createSeason: (payload: { season_id: string; title?: string }): Promise<LadderSeasonConfig> =>
    api('/ladder/seasons', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  startSeason: (seasonId: string): Promise<LadderSeasonConfig> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/start`, { method: 'POST' }),
  completeSeason: (seasonId: string): Promise<LadderSeasonConfig> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/complete`, { method: 'POST' }),
  archiveSeason: (seasonId: string): Promise<LadderSeasonConfig> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/archive`, { method: 'POST' }),
  setDefaultSeason: (seasonId: string): Promise<LadderSeasonConfig> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/set-default`, { method: 'POST' }),
  setSeasonEnrollment: (seasonId: string, accountIds: string[]): Promise<LadderSeasonConfig> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/enrollment`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_ids: accountIds }),
    }),
  deleteSeason: (seasonId: string): Promise<{ season_id: string; deleted: boolean }> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}`, { method: 'DELETE' }),

  // ---- R14-B Runtime Process Supervision ----
  spawnSeasonRuntime: (seasonId: string): Promise<SeasonRuntimeStatusResponse> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/runtime/spawn`, { method: 'POST' }),
  stopSeasonRuntime: (seasonId: string): Promise<SeasonRuntimeStatusResponse> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/runtime/stop`, { method: 'POST' }),
  getSeasonRuntimeStatus: (seasonId: string): Promise<SeasonRuntimeStatusResponse> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/runtime/status`),

  // ---- R14-D Season Finalize & Archive Summary（只读消费冻结 API） ----
  /** R14-D canonical 结束路径：running → completed + sealed archive summary（与 /complete frozen 路径一致） */
  finalizeSeason: (seasonId: string): Promise<LadderSeasonConfig> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/finalize`, { method: 'POST' }),
  /** 只读终局摘要：completed/archived 返回 sealed（persisted 权威）；running 返回 preview（实时预览） */
  getArchiveSummary: (seasonId: string, signal?: AbortSignal): Promise<ArchiveSummaryResponse> =>
    api(`/ladder/seasons/${encodeURIComponent(seasonId)}/archive-summary`, { signal }),
};
