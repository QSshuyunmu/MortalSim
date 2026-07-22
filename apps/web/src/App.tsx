import { useEffect, useMemo, useState, type CSSProperties } from "react";

type Page = "analysis" | "history" | "settings";
type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

type Config = {
  hand: string;
  first_tsumo: string;
  dora: string;
  discards: string;
  runs: string;
  seed: string;
  oya: string;
  batch_size: string;
  rayon_threads: string;
  strict_comparison: boolean;
};

type Summary = Record<string, any> & {
  discard: string;
  games: number;
  errors: number;
  avg_rank: number;
  avg_point: number;
  rank_counts?: number[];
};

type RunResult = {
  run_id?: string;
  elapsed?: number;
  device?: string;
  runs?: number;
  seed?: number;
  summaries: Summary[];
  comparisons?: Array<{ discard: string; paired_point_delta: number; ci95: number[] }>;
  gpu_telemetry?: Record<string, any>;
};

type HistoryRun = {
  run_id: string;
  status: RunStatus;
  created_at: string;
  request: Record<string, any>;
  result?: RunResult;
  error?: string;
};

const initialConfig: Config = {
  hand: "4567m3477p13406s",
  first_tsumo: "6s",
  dora: "9s",
  discards: "1s,6s",
  runs: "1000",
  seed: "42",
  oya: "0",
  batch_size: "1000",
  rayon_threads: "20",
  strict_comparison: true,
};

const api = async (path: string, init?: RequestInit) => {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...init?.headers }, ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败 (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
};

const pct = (value: any) => typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
const signed = (value: any, digits = 1) => typeof value === "number" ? `${value >= 0 ? "+" : ""}${value.toFixed(digits)}` : "—";
const number = (value: any, digits = 2) => typeof value === "number" ? value.toFixed(digits) : "—";

function App() {
  const [page, setPage] = useState<Page>("analysis");
  const [config, setConfig] = useState<Config>(initialConfig);
  const [capabilities, setCapabilities] = useState<Record<string, any> | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<RunStatus | "idle">("idle");
  const [progress, setProgress] = useState({ completed: 0, total: 0, discard: "" });
  const [result, setResult] = useState<RunResult | null>(null);
  const [history, setHistory] = useState<HistoryRun[]>([]);
  const [message, setMessage] = useState("准备就绪");
  const [error, setError] = useState("");

  useEffect(() => { api("/api/capabilities").then(setCapabilities).catch((e) => setError(e.message)); }, []);
  useEffect(() => { if (page === "history") api("/api/runs").then(setHistory).catch((e) => setError(e.message)); }, [page]);

  const candidates = useMemo(() => config.discards.split(",").map((x) => x.trim()).filter(Boolean), [config.discards]);
  const update = (key: keyof Config, value: string | boolean) => setConfig((old) => ({ ...old, [key]: value }));

  const start = async () => {
    if (capabilities && !capabilities.cuda_available) {
      setError("CUDA unavailable. This GPU-only build requires an NVIDIA GPU and CUDA-enabled PyTorch; CPU fallback is disabled.");
      return;
    }
    if (capabilities && !capabilities.model_exists) {
      setError("未找到 Mortal 模型，请先在设置页检查模型路径。");
      return;
    }
    setError(""); setResult(null); setStatus("queued"); setMessage("正在创建任务…");
    try {
      const created = await api("/api/runs", { method: "POST", body: JSON.stringify({
        ...config,
        discards: candidates,
        runs: Number(config.runs), seed: Number(config.seed), oya: Number(config.oya),
        batch_size: Number(config.batch_size), rayon_threads: Number(config.rayon_threads), engine: "python",
      })});
      setRunId(created.run_id); setStatus(created.status); watch(created.run_id);
    } catch (e: any) { setStatus("idle"); setError(e.message); }
  };

  const watch = (id: string) => {
    const source = new EventSource(`/api/runs/${id}/events`);
    source.onmessage = () => undefined;
    ["status", "candidate_started", "batch_completed", "gpu_status", "candidate_completed", "completed", "failed", "cancelled"].forEach((name) => {
      source.addEventListener(name, (event) => {
        const data = JSON.parse((event as MessageEvent).data);
        if (name === "status") setMessage(data.message || "运行中");
        if (name === "candidate_started") setMessage(`正在分析 ${data.discard}`);
        if (name === "batch_completed") setProgress({ completed: data.completed, total: data.total, discard: data.discard });
        if (name === "gpu_status" && data.available && data.sample) setMessage(`GPU ${data.sample["temperature.gpu"] ?? "—"}°C · ${data.sample["memory.used"] ?? "—"} MiB`);
        if (name === "completed") { setStatus("completed"); setResult(data.result); setMessage("分析完成"); source.close(); }
        if (name === "failed") { setStatus("failed"); setError(data.error || "运行失败"); source.close(); }
        if (name === "cancelled") { setStatus("cancelled"); setMessage("已取消"); source.close(); }
      });
    });
    source.onerror = () => { if (status === "running") setMessage("正在等待 Worker…"); };
  };

  const cancel = async () => { if (!runId) return; await api(`/api/runs/${runId}/cancel`, { method: "POST" }); setStatus("cancelled"); setMessage("已取消"); };
  const loadRun = (run: HistoryRun) => { setConfig({ ...initialConfig, ...run.request, discards: (run.request.discards || []).join(",") }); setResult(run.result || null); setRunId(run.run_id); setStatus(run.status); setPage("analysis"); };
  const deleteRun = async (id: string) => { await api(`/api/runs/${id}`, { method: "DELETE" }); setHistory((items) => items.filter((item) => item.run_id !== id)); };

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">M</div><div><strong>MortalSim</strong><span>local analysis desk</span></div></div>
      <nav>
        <button className={page === "analysis" ? "active" : ""} onClick={() => setPage("analysis")}>新建分析</button>
        <button className={page === "history" ? "active" : ""} onClick={() => setPage("history")}>历史运行</button>
        <button className={page === "settings" ? "active" : ""} onClick={() => setPage("settings")}>设置与诊断</button>
      </nav>
      <div className="sidebar-foot"><span className={`dot ${capabilities?.cuda_available ? "ok" : "warn"}`}></span>{capabilities?.cuda_available ? "CUDA 可用" : "CPU 模式"}</div>
    </aside>
    <main className="main">
      <header className="topbar"><div><span className="eyebrow">MORTAL / LOCAL</span><h1>{page === "analysis" ? "第一打分析" : page === "history" ? "历史运行" : "设置与诊断"}</h1></div><div className="top-meta"><span className="status-dot"></span>{message}<code>v0.1 alpha</code></div></header>
      {error && <div className="alert danger">{error}</div>}
      {page === "analysis" && <Analysis config={config} update={update} candidates={candidates} start={start} cancel={cancel} status={status} progress={progress} result={result} capabilities={capabilities} />}
      {page === "history" && <History runs={history} loadRun={loadRun} deleteRun={deleteRun} />}
      {page === "settings" && <Settings capabilities={capabilities} />}
    </main>
  </div>;
}

function Analysis({ config, update, candidates, start, cancel, status, progress, result, capabilities }: any) {
  const busy = status === "queued" || status === "running";
  return <>
    <section className="context-grid">
      <div className="panel form-panel"><div className="panel-head"><div><span className="eyebrow">NEW RUN</span><h2>局面设置</h2></div><span className="hint">相同 seed 配对比较</span></div>
        <div className="field wide"><label>手牌</label><input value={config.hand} onChange={(e) => update("hand", e.target.value)} /><div className="tile-preview">{config.hand || "输入牌谱"}</div></div>
        <div className="form-grid"><Field label="第一摸" value={config.first_tsumo} onChange={(v: string) => update("first_tsumo", v)} /><Field label="宝牌指示" value={config.dora} onChange={(v: string) => update("dora", v)} /><Field label="oya 座位" value={config.oya} onChange={(v: string) => update("oya", v)} type="number" /><Field label="模拟局数" value={config.runs} onChange={(v: string) => update("runs", v)} type="number" /><Field label="Seed" value={config.seed} onChange={(v: string) => update("seed", v)} type="number" /><Field label="Batch" value={config.batch_size} onChange={(v: string) => update("batch_size", v)} type="number" /></div>
        <div className="field wide"><label>第一打候选</label><input value={config.discards} onChange={(e) => update("discards", e.target.value)} /><div className="chips">{candidates.map((candidate: string) => <span key={candidate} className="chip">{candidate}</span>)}</div></div>
        <div className="form-actions"><label className="check"><input type="checkbox" checked={config.strict_comparison} onChange={(e) => update("strict_comparison", e.target.checked)} />固定 seed 严格比较</label><button className="primary" onClick={start} disabled={busy || candidates.length === 0}>开始模拟</button>{busy && <button className="secondary" onClick={cancel}>取消</button>}</div>
      </div>
      <div className="panel run-panel"><div className="panel-head"><div><span className="eyebrow">RUNTIME</span><h2>运行状态</h2></div><span className={`badge ${busy ? "live" : status === "completed" ? "done" : ""}`}>{status}</span></div><div className="runtime-message">{busy ? "Worker 正在推进局面" : status === "completed" ? "结果已准备好" : "等待下一次分析"}</div><div className="progress-track"><div style={{ width: `${progress.total ? (progress.completed / progress.total) * 100 : 0}%` }}></div></div><div className="progress-meta"><span>{progress.discard || "—"}</span><strong>{progress.total ? `${progress.completed}/${progress.total} 局` : "—"}</strong></div><div className="runtime-grid"><Metric label="设备" value={capabilities?.cuda_available ? "CUDA" : "CPU"} /><Metric label="模型" value="Mortal v4" /><Metric label="线程" value={config.rayon_threads} /><Metric label="候选" value={`${candidates.length} 个`} /></div></div>
    </section>
    {result ? <Results result={result} /> : <section className="empty panel"><div className="empty-mark">◎</div><h2>结果会出现在这里</h2><p>输入局面和候选第一打，运行后查看得点、顺位与置信区间。</p></section>}
  </>;
}

function Results({ result }: { result: RunResult }) {
  const summaries = result.summaries || [];
  const base = summaries[0];
  const exportUrl = result.run_id ? `/api/runs/${result.run_id}/export` : "";
  return <section className="results">
    <div className="section-head">
      <div><span className="eyebrow">COMPARISON</span><h2>候选打法对比</h2></div>
      <div className="section-actions">
        <span className="muted">{result.runs || 0} 局 · seed {result.seed ?? "—"} · {number(result.elapsed, 1)}s</span>
        {exportUrl && <><a className="export-link" href={`${exportUrl}?format=json`}>JSON</a><a className="export-link" href={`${exportUrl}?format=csv`}>CSV</a><a className="export-link" href={`${exportUrl}?format=html`}>HTML</a></>}
      </div>
    </div>
    <div className="compare-table panel"><div className="table-row table-head"><span>指标</span>{summaries.map((s) => <span key={s.discard}>{s.discard}{s === base && <small>参考</small>}</span>)}</div><CompareRow label="平均得点" values={summaries.map((s) => signed(s.avg_point))} /><CompareRow label="平均顺位" values={summaries.map((s) => number(s.avg_rank))} /><CompareRow label="和了率" values={summaries.map((s) => pct(s.agari_rate))} /><CompareRow label="放铳率" values={summaries.map((s) => pct(s.houjuu_rate))} /><CompareRow label="立直率" values={summaries.map((s) => pct(s.riichi_rate))} /><CompareRow label="副露率" values={summaries.map((s) => pct(s.fuuro_rate))} /></div>
    <div className="chart-grid"><RankChart summaries={summaries} /><PointBars summaries={summaries} /></div>
    <div className="detail-grid">{summaries.map((summary) => <div className="panel detail-card" key={summary.discard}><div className="detail-title"><strong>{summary.discard}</strong><span>{summary.games} 局</span></div><div className="detail-line"><span>荣和 / 自摸</span><b>{summary.hora ?? 0} / {summary.tsumo ?? 0}</b></div><div className="detail-line"><span>流局</span><b>{summary.ryukyoku ?? 0}</b></div><div className="detail-line"><span>错误</span><b className={summary.errors ? "bad" : "good"}>{summary.errors}</b></div></div>)}</div>
  </section>;
}

function Field({ label, value, onChange, type = "text" }: any) { return <div className="field"><label>{label}</label><input type={type} value={value} onChange={(e) => onChange(e.target.value)} /></div>; }
function Metric({ label, value }: any) { return <div><span className="metric-label">{label}</span><strong>{value}</strong></div>; }
function CompareRow({ label, values }: { label: string; values: string[] }) { return <div className="table-row"><span>{label}</span>{values.map((value, index) => <span key={`${label}-${index}`} className={index > 0 ? "value-accent" : ""}>{value}</span>)}</div>; }
function RankChart({ summaries }: { summaries: Summary[] }) { return <div className="panel chart"><div className="chart-head"><h3>终局顺位分布</h3><span>1 → 4</span></div>{summaries.map((s) => { const values = s.rank_counts || [0, 0, 0, 0]; const total = values.reduce((a, b) => a + b, 0) || 1; return <div className="bar-row" key={s.discard}><label>{s.discard}</label><div className="stack">{values.map((v, i) => <i key={i} className={`rank r${i + 1}`} style={{ width: `${v / total * 100}%` }} />)}</div></div>; })}</div>; }
function PointBars({ summaries }: { summaries: Summary[] }) { const max = Math.max(...summaries.map((s) => Math.abs(s.avg_point || 0)), 1); return <div className="panel chart"><div className="chart-head"><h3>平均得点</h3><span>相对参考打法</span></div>{summaries.map((s) => <div className="point-row" key={s.discard}><label>{s.discard}</label><div className="point-track"><i style={{ width: `${Math.min(100, Math.abs(s.avg_point || 0) / max * 100)}%`, background: (s.avg_point || 0) >= 0 ? "var(--accent)" : "var(--danger)" }} /></div><b>{signed(s.avg_point)}</b></div>)}</div>; }
function History({ runs, loadRun, deleteRun }: { runs: HistoryRun[]; loadRun: (run: HistoryRun) => void; deleteRun: (id: string) => void }) {
  return <section className="panel history"><div className="section-head"><div><span className="eyebrow">RUN ARCHIVE</span><h2>历史运行</h2></div><span className="muted">{runs.length} 条记录</span></div>{runs.length === 0 ? <div className="empty compact"><h2>还没有保存的运行</h2><p>完成一次分析后，结果会自动出现在这里。</p></div> : <div className="history-list">{runs.map((run) => <div className="history-row" key={run.run_id}><button className="history-main" onClick={() => loadRun(run)}><span><strong>{(run.request.discards || []).join(", ")}</strong><small>{new Date(run.created_at).toLocaleString()}</small></span><span className={`badge ${run.status === "completed" ? "done" : ""}`}>{run.status}</span><code>{run.run_id.slice(0, 8)}</code></button><button className="history-delete" title="删除运行" onClick={() => deleteRun(run.run_id)}>删除</button></div>)}</div>}</section>;
}
function Settings({ capabilities }: { capabilities: Record<string, any> | null }) { return <section className="settings-grid"><div className="panel"><span className="eyebrow">DIAGNOSTICS</span><h2>运行环境</h2><div className="setting-line"><span>平台</span><code>{capabilities?.platform || "检测中…"}</code></div><div className="setting-line"><span>Python</span><code>{capabilities?.python || "—"}</code></div><div className="setting-line"><span>CUDA</span><strong className={capabilities?.cuda_available ? "good" : "muted"}>{capabilities?.cuda_available ? "可用" : "不可用"}</strong></div><div className="setting-line"><span>模型</span><strong className={capabilities?.model_exists ? "good" : "bad"}>{capabilities?.model_exists ? "已找到" : "缺失"}</strong></div><div className="setting-line"><span>数据目录</span><code>{capabilities?.data_dir || "—"}</code></div></div><div className="panel"><span className="eyebrow">ABOUT</span><h2>MortalSim</h2><p className="prose">本地运行的自亲第一打模拟与比较工具。模拟、模型和结果默认留在本机。</p><p className="muted">正式推理：Python AMP · Rust runner · Windows x64</p></div></section>; }

export default App;
