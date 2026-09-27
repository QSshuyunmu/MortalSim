// src/replay_ui/src/types/ladder.ts
// Model Ladder & Account Profiles 类型契约（与 /api/ladder/* 响应对齐）。

import type { AccountType, ControllerType, FrozenExecutionProvenance } from './participants';

export type LadderReadinessState = 'ready' | 'not_published' | 'invalid' | 'registry_mismatch';

export interface LadderSeasonReadiness {
  state: LadderReadinessState;
  code: string;
  message: string;
  detail?: string;
  retryable: boolean;
}

export type LadderDefaultSource = 'registry' | 'single_season' | null;

export interface HumanRuntimeSpec {
  kind: 'human';
  controller_type: 'human_ui';
}

export interface LocalArtifactRuntimeSpec {
  kind: 'local_artifact';
  controller_type: 'local_model';
  model_identity_id: string;
  model_artifact_id: string;
  artifact_path: string;
  resolved_checkpoint_path: string;
  artifact_hash?: string | null;
}

export interface ExternalRevisionRuntimeSpec {
  kind: 'external_revision';
  controller_type: 'external_agent';
  model_identity_id: string;
  external_revision_id: string;
  provider: string;
  version: string;
  external_ref?: string | null;
}

export type RuntimeSpecUnion = HumanRuntimeSpec | LocalArtifactRuntimeSpec | ExternalRevisionRuntimeSpec;

export interface SeasonRuntimeParticipant {
  account_id: string;
  display_name: string;
  account_type: AccountType;
  controller_type: ControllerType;
  model_identity_id?: string | null;
  execution_provenance: FrozenExecutionProvenance;
  runtime_spec: RuntimeSpecUnion;
}

export interface SeasonRuntimeManifest {
  schema_version: 'keqing.season.runtime_manifest.v1';
  manifest_id: string;
  season_id: string;
  season_authority_hash: string;
  materialization: 'frozen' | 'projected_legacy';
  participants: SeasonRuntimeParticipant[];
  scoring_summary: Record<string, unknown>;
  generated_at?: string | null;
}

export interface PreflightIssue {
  code: string;
  message: string;
  severity: 'error' | 'warning';
  account_id?: string | null;
  model_identity_id?: string | null;
  detail?: string | null;
}

export type ProcessState = 'pending' | 'starting' | 'healthy' | 'stopped' | 'failed';

export interface SeasonRuntimeProcessRecord {
  runtime_id: string;
  season_id: string;
  manifest_id: string;
  account_id: string;
  controller_type: ControllerType;
  pid?: number | null;
  state: ProcessState;
  started_at?: string | null;
  stopped_at?: string | null;
  exit_code?: number | null;
  failure_reason?: string | null;
  command?: string[];
  log_path?: string | null;
}

export interface SeasonRuntimeStatusResponse {
  season_id: string;
  manifest_id: string;
  season_status: string;
  processes: SeasonRuntimeProcessRecord[];
  is_active: boolean;
}

export interface SeasonPreflightReport {
  season_id: string;
  season_status: string;
  can_start: boolean;
  state: 'ready' | 'blocked';
  issues: PreflightIssue[];
  manifest?: SeasonRuntimeManifest | null;
}

// ---- R14-D Archive Summary（与 runtime/archive_summary.py 对齐） ----

export interface ArchiveAccountStats {
  account_id: string;
  games: number;
  rank_sum: number;
  first_places: number;
  second_places: number;
  third_places: number;
  fourth_places: number;
}

export interface ArchiveMatchSummary {
  total_matches: number;
  active_matches: number;
  void_matches: number;
  rating_eligible_matches: number;
  runtime_bound_matches: number;
  total_revisions: number;
  first_match_occurred_at?: string | null;
  last_match_occurred_at?: string | null;
  account_stats: ArchiveAccountStats[];
}

export interface ArchiveSessionEpoch {
  session_id: string;
  created_at: string;
  manifest_id: string;
  season_authority_hash: string;
  participant_count: number;
  local_model_participants: number;
}

export interface ArchiveProcessRecord {
  runtime_id: string;
  account_id: string;
  controller_type: string;
  state: string;
  started_at?: string | null;
  stopped_at?: string | null;
  exit_code?: number | null;
}

export interface ArchiveOperationSummary {
  session_count: number;
  sessions: ArchiveSessionEpoch[];
  processes: ArchiveProcessRecord[];
}

export interface SeasonArchiveSummary {
  schema_version: 'keqing.season.archive_summary.v1';
  season_id: string;
  manifest_id: string;
  season_authority_hash: string;
  match_summary: ArchiveMatchSummary;
  operation_summary: ArchiveOperationSummary;
  completed_at: string;
  archive_summary_hash: string;
  archive_summary_id: string;
}

/** GET /archive-summary 响应：sealed（历史权威）或 preview（running 实时预览） */
export type ArchiveSummaryResponse =
  | {
      season_id: string;
      kind: 'sealed';
      season_status: 'completed' | 'archived';
      completed_at?: string | null;
      archive_summary: SeasonArchiveSummary;
    }
  | {
      season_id: string;
      kind: 'preview';
      season_status: 'running';
      note?: string;
      archive_summary_projection: Omit<SeasonArchiveSummary, 'completed_at' | 'archive_summary_hash' | 'archive_summary_id'>;
    };

export interface LadderSeasonConfig {
  schema: string;
  season_id: string;
  title?: string;
  status: 'draft' | 'running' | 'completed' | 'archived';
  default?: boolean;
  report_dir?: string;
  scoring?: Record<string, unknown>;
  ingest?: Record<string, unknown>;
  models: Array<{
    model_id: string;
    model_identity_id?: string | null;
    checkpoint?: string | null;
    accounts: Array<{ account_id: string; display_name?: string | null }>;
  }>;
  runtime_manifest?: SeasonRuntimeManifest | null;
  /** R14-D: finalize 时封存的完成时间（sealed 赛季为不可变历史事实） */
  completed_at?: string;
  /** R14-D: finalize 时封存的终局摘要（sealed 赛季；read-time 只读展示） */
  archive_summary?: SeasonArchiveSummary | null;
  created_at?: string;
  updated_at?: string;
}

export interface LadderSeasonsResponse {
  schema: string;
  default_season_id: string | null;
  default_source: LadderDefaultSource;
  seasons: LadderSeason[];
}

export interface LadderSeasonScoring {
  pt_profile?: string;
  pt_rank_deltas?: number[];
  pt_initial?: number;
  pt_target?: number;
  rating_initial?: number;
  rating_formula?: string;
  rank_name?: string;
  /** 版本化计分引擎描述（Round 8） */
  system?: string;
  version?: string;
  game_length?: string;
  /** 个人计分档位策略（tenhou_rank_progression = individual_highest） */
  tier_policy?: string;
  positive_pt_tables?: Record<string, number[]>;
  /** 已废弃的房间字段；仅旧 profile 可能带 */
  room_policy?: string;
  membership?: string;
  initial_rank?: string;
  initial_rating?: number;
}

export interface LadderSeason {
  season_id: string;
  title?: string;
  status?: string;
  games_expected?: number;
  notes?: string;
  models?: string[];
  accounts?: number;
  games?: number;
  data_ready?: boolean;
  report_schema?: string;
  /** 当前只读快照目录名（如 20260801-203000） */
  snapshot_id?: string;
  /** account_summary.json 的 mtime（epoch 秒） */
  updated_at?: number;
  scoring?: LadderSeasonScoring;
  /** 是否默认赛季（目录派生的规范化标记） */
  is_default?: boolean;
  /** 未就绪原因（结构化 readiness 契约；就绪时 state="ready"） */
  readiness?: LadderSeasonReadiness;
}

export interface LadderAccountRow {
  account_id: string;
  display_name: string;
  model_id: string;
  checkpoint?: string | null;
  games: number;
  /** v2 报告的段位状态；v1 legacy 报告为 null（固定七段） */
  rank_id?: string | null;
  rank_name?: string | null;
  rank_ordinal: number;
  pt_initial?: number | null;
  pt_current: number;
  /** 升段目标 PT；天凤位为 null */
  pt_target: number | null;
  pt_gap: number | null;
  pt_progress?: number | null;
  promotions?: number;
  demotions?: number;
  highest_rank_id?: string | null;
  highest_rank_name?: string | null;
  /** 当前所在卓的安定段位（各卓内实测） */
  stable_dan?: number | null;
  /** 凤凰卓内对局数与该卓安定段位（该卓样本不足时为 null） */
  games_houou?: number | null;
  stable_dan_houou?: number | null;
  /** 特上卓内对局数与该卓安定段位（该卓样本不足时为 null） */
  games_tokujou?: number | null;
  stable_dan_tokujou?: number | null;
  tenhou_reached?: boolean;
  total_pt_delta?: number | null;
  avg_pt_delta?: number | null;
  rating: number;
  rank_1: number;
  rank_2: number;
  rank_3: number;
  rank_4: number;
  rank_1_rate: number | null;
  rank_4_rate: number | null;
  avg_rank: number | null;
  avg_rank_pt: number | null;
  agari_rate: number | null;
  houjuu_rate: number | null;
  fuuro_rate: number | null;
  riichi_rate: number | null;
  agari_rate_after_fuuro: number | null;
  houjuu_rate_after_fuuro: number | null;
  agari_rate_after_riichi: number | null;
  houjuu_rate_after_riichi: number | null;
  avg_point_per_agari: number | null;
  total_delta_score: number | null;
  /** R12-A：详细牌谱统计覆盖率（完整牌谱场数/总局数/覆盖率） */
  stats_games?: number | null;
  stats_rounds?: number | null;
  stats_total_games?: number | null;
  stats_coverage?: number | null;
  rank_position?: number;
}

export interface LadderModelSummary {
  model_id: string;
  accounts: number;
  games: number;
  /** 跨段位不再平均 PT；同一段位（含 v1 legacy）时有效 */
  avg_pt: number | null;
  avg_rating: number | null;
  avg_rank: number | null;
  avg_rank_pt: number | null;
  rank_distribution?: Record<string, number>;
  highest_rank_id?: string | null;
  highest_rank_name?: string | null;
  median_rank_ordinal?: number | null;
  median_rank_name?: string | null;
}

export interface LadderResponse {
  season: LadderSeason;
  sort: string;
  accounts: LadderAccountRow[];
  models: LadderModelSummary[];
}

export interface LadderCurvePoint {
  games: number;
  rating: number;
  pt: number;
  rank_id?: string;
  rank_name?: string;
  pt_target?: number | null;
  /** 曲线点上的段位变化（数据已就绪；UI 展示为后续增强） */
  rank_before?: string;
  rank_after?: string;
  transition?: string;
}

export interface LadderRecentGame {
  game_index: number;
  rank: number;
  final_score: number;
  score_delta: number;
  game_length?: string;
  /** 个人计分档位（如 tokujou-equivalent）；天凤位/legacy 为 null */
  pt_tier?: string | null;
  /** 该玩家本局一/二/三位正分档位；四位或天凤位为 null */
  positive_pt?: number[] | null;
  rank_before?: string | null;
  pt_before?: number | null;
  pt_delta: number;
  transition?: string | null;
  rank_after?: string | null;
  pt_after: number;
  rating_before?: number | null;
  rating_after: number;
  source_log?: string | null;
}

export interface LadderAccountDetail {
  season: LadderSeason;
  account: LadderAccountRow;
  rank_distribution: number[];
  curve: LadderCurvePoint[];
  recent_games: LadderRecentGame[];
}

export interface LadderModelDetail {
  season: LadderSeason;
  model: {
    model_id: string;
    checkpoint?: string | null;
    accounts: LadderAccountRow[];
    summary: LadderModelSummary | null;
  };
  league_summary: {
    schema?: string;
    games_total?: number;
    lineups?: string[];
    model: Record<string, unknown>;
  } | null;
}
