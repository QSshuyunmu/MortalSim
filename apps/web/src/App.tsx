import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from "react";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { Activity, Archive, BarChart3, ChevronDown, ChevronRight, CircleStop, Download, FileUp, Gauge, History as HistoryIcon, Layers3, Play, Plus, RotateCcw, Settings, X } from "lucide-react";
import "./styles.css";

echarts.use([BarChart, HeatmapChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

type Rate = { count: number; total: number; rate: number | null; ci95: number[] | null };
type Mean = { value: number | null; stddev: number | null; ci95: number[] | null; n: number };
type Sample = { seed: number | number[]; trace_hash?: string; point: number; rank: number; outcome: string; win_method?: string; candidate: string };
type Candidate = {
  discard: string; candidate?: string; first_riichi?: boolean; games: number; completed_games: number; errors: number; avg_point: number | null; avg_rank: number | null; point_ci95: number[] | null; rank_counts: number[];
  sample: Record<string, any>; value: { point: Mean; rank: Mean; point_definition?: string }; rank: { average: Mean; positions: Rate[] };
  outcome: Record<string, Rate>; win: Record<string, any>; defense: Record<string, any>; riichi: Record<string, any>; tenpai: Record<string, any>; call: Record<string, any>; draw: Record<string, any>; special: Record<string, any>;
  yaku: Array<{ id: string; count: number | null; rate: number | null; total_tiles: number | null; available: boolean }>;
  samples: Record<string, Sample[]>;
};
type RunResult = { schema_version?: number; metrics_version?: number; merge_state_version?: number; decision_contract?: string; runtime?: Record<string,any>; run_id?: string; elapsed?: number; runs?: number; total_runs?: number; seed?: number; candidates?: Candidate[]; summaries?: Candidate[]; comparisons?: any[]; warnings?: string[]; config?: Record<string, any>; engine?: Record<string, any>; resolved_context?: Record<string, any>; resolved_input?: { main_haipai?: string[]; first_tsumo?: string; dora?: string }; extension_history?: any[]; gpu_telemetry?: Record<string, any>; model?: ModelInfo };
type RunRecord = { run_id: string; status: string; created_at: string; request: Record<string, any>; result?: RunResult };
type ModelInfo = { id:string; label:string; filename:string; sha256?:string; version?:number; conv_channels?:number; num_blocks?:number; ready:boolean; error?:string; source:string; lite_compatible?:boolean; incompatibility_reason?:string; supported_decision_contracts?:string[] };
type ActiveTask = { run_id:string; status:string; extension_of?:string|null; request:Record<string,any>; progress?:Record<string,any>; gpu_status?:any; created_at:string };

const OUTCOME_META = [
  ["self_win", "自家和牌", "#087f68"], ["self_deal_in", "自家放铳", "#a64b42"], ["draw", "流局", "#8a9499"], ["sideways", "横移动", "#c29a52"], ["other_tsumo", "他家自摸", "#58778a"],
] as const;
const YAKU_NAMES: Record<string, string> = { riichi:"立直", double_riichi:"两立直", ippatsu:"一发", menzen_tsumo:"门前清自摸和", tanyao:"断幺九", pinfu:"平和", iipeikou:"一杯口", haku:"白", hatsu:"发", chun:"中", rinshan:"岭上开花", chankan:"抢杠", haitei:"海底摸月", houtei:"河底捞鱼", sanshoku_doujun:"三色同顺", ikkitsuukan:"一气通贯", chanta:"混全带幺九", chiitoitsu:"七对子", toitoi:"对对和", sanankou:"三暗刻", honroutou:"混老头", sanshoku_doukou:"三色同刻", sankantsu:"三杠子", shousangen:"小三元", honitsu:"混一色", junchan:"纯全带幺九", ryanpeikou:"二杯口", chinitsu:"清一色", kokushi:"国士无双", suuankou:"四暗刻", daisangen:"大三元", shousuushii:"小四喜", daisuushii:"大四喜", tsuuiisou:"字一色", chinroutou:"清老头", ryuuiisou:"绿一色", chuuren:"九莲宝灯", suukantsu:"四杠子", tenhou:"天和", chiihou:"地和", nagashi_mangan:"流局满贯", dora:"宝牌", ura_dora:"里宝牌", aka_dora:"赤宝牌" };

const initial = {
  hand:"", dora:"", discards:"",
  riichi_discards:[] as string[],
  round:"E1", honba:"0", kyotaku:"0",
  scores:{self:"25000",shimocha:"25000",toimen:"25000"},
  runs:"1000", seed:"42", batch_size:"1000", rayon_threads:"20", model_id:"mortal-v4-20240308", engine:"lite", decision_contract:"stable_advantage_v2", strict_comparison:true,
};
type RequestCandidate = string | { tile: string; riichi?: boolean };
const candidateKey = (candidate: Pick<Candidate,"discard"|"candidate"|"first_riichi">) => candidate.candidate || (candidate.first_riichi ? `riichi:${candidate.discard}` : candidate.discard);
const candidateLabel = (candidate: Pick<Candidate,"discard"|"first_riichi">) => candidate.first_riichi ? `立直打 ${candidate.discard}` : `打 ${candidate.discard}`;
const candidateIdLabel = (value: string | undefined) => value?.startsWith("riichi:") ? `立直打 ${value.slice("riichi:".length)}` : `打 ${value||""}`;
const requestCandidateLabel = (candidate: RequestCandidate) => typeof candidate === "string" ? `打 ${candidate}` : candidate.riichi ? `立直打 ${candidate.tile}` : `打 ${candidate.tile}`;
const ROUND_OPTIONS = [
  ["E1","东一局"],["E2","东二局"],["E3","东三局"],["E4","东四局"],
  ["S1","南一局"],["S2","南二局"],["S3","南三局"],["S4","南四局"],
  ["W1","西一局"],["W2","西二局"],["W3","西三局"],["W4","西四局"],
] as const;
const roundLabel = (round:string) => ROUND_OPTIONS.find(([id])=>id===round)?.[1] || round;
const pct = (value: number | null | undefined) => value == null ? "不可用" : `${(value * 100).toFixed(2)}%`;
const num = (value: number | null | undefined, digits=1) => value == null ? "不可用" : value.toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const signed = (value: number | null | undefined, digits=1) => value == null ? "不可用" : `${value >= 0 ? "+" : ""}${num(value, digits)}`;
const ci = (value: number[] | null | undefined, percent=false) => !value ? "样本不足" : `${percent ? pct(value[0]) : signed(value[0])} 至 ${percent ? pct(value[1]) : signed(value[1])}`;
function apiErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map(item => typeof item?.msg === "string" ? item.msg : null)
      .filter((message): message is string => Boolean(message));
    if (messages.length) return messages.join("；");
  }
  return fallback;
}
const apiGet = (url:string) => fetch(url, {cache:"no-store"});
const emptyRate = (): Rate => ({count:0,total:0,rate:null,ci95:null});
function normalizeCandidate(candidate:any): Candidate {
  if (candidate?.value?.point && candidate?.outcome) return candidate as Candidate;
  const positions=(candidate?.rank_counts||[0,0,0,0]).map((count:number)=>({count,total:candidate?.games||0,rate:candidate?.games?count/candidate.games:null,ci95:null}));
  const outcome:any={}; for(const [id] of OUTCOME_META) outcome[id]=emptyRate(); outcome.self_ron=emptyRate();outcome.self_tsumo=emptyRate();
  return {...candidate,completed_games:Math.max(0,(candidate?.games||0)-(candidate?.errors||0)),point_ci95:null,value:{point:{value:candidate?.avg_point??null,stddev:null,ci95:null,n:candidate?.games||0},rank:{value:candidate?.avg_rank??null,stddev:null,ci95:null,n:candidate?.games||0}},rank:{average:{value:candidate?.avg_rank??null,stddev:null,ci95:null,n:candidate?.games||0},positions},outcome,win:{riichi_share:emptyRate(),open_share:emptyRate(),dama_share:emptyRate(),ron_share:emptyRate(),tsumo_share:emptyRate(),average_point:null,average_raw_point:null,average_han:null},defense:{deal_in_rate:emptyRate(),other_tsumo_rate:emptyRate(),sideways_rate:emptyRate(),average_deal_in_loss:null,average_deal_in_turn:null},riichi:{rate:emptyRate(),first_rate:emptyRate(),chase_rate:emptyRate(),win_after_rate:emptyRate(),average_turn:null},tenpai:{rate:emptyRate(),average_first_turn:{value:null},draw_tenpai_rate:emptyRate()},call:{rate:emptyRate(),average_count:{value:null},win_after_rate:emptyRate(),average_balance:null},draw:{rate:emptyRate(),average_balance:null,tenpai_count:null},special:{yakuman:0,nagashi_mangan:0,error_types:{}},yaku:[],samples:{}} as Candidate;
}

function EChart({ option, className="chart-canvas", style }: { option: echarts.EChartsCoreOption; className?: string; style?: CSSProperties }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (!ref.current) return; const chart = echarts.init(ref.current); chart.setOption(option); const resize=()=>chart.resize(); window.addEventListener("resize", resize); return ()=>{window.removeEventListener("resize", resize); chart.dispose();}; }, [option]);
  return <div ref={ref} className={className} style={style} />;
}

function useDialogFocus(onEscape:()=>void, escapeDisabled=false) {
  const ref=useRef<HTMLElement>(null);
  const escapeRef=useRef(onEscape);
  escapeRef.current=onEscape;
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    const root=ref.current;
    const focusable=()=>Array.from(root?.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])")||[]);
    requestAnimationFrame(()=>focusable()[0]?.focus());
    const onKey=(event:KeyboardEvent)=>{
      if(event.key==="Escape"&&!escapeDisabled){event.preventDefault();escapeRef.current();return;}
      if(event.key!=="Tab")return;
      const items=focusable();if(!items.length)return;
      const first=items[0],last=items[items.length-1];
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    };
    document.addEventListener("keydown",onKey);
    return()=>{document.removeEventListener("keydown",onKey);previous?.focus();};
  },[escapeDisabled]);
  return ref;
}

function parseTiles(source: string): string[] {
  const tiles: string[] = []; let digits = "";
  for (const char of source.trim()) { if (/\d/.test(char)) digits += char; else if (/[mpsz]/.test(char)) { for (const n of digits) tiles.push(`${n}${char}`); digits=""; } }
  return tiles;
}
const TILE_ASSET_ROOT = "/tiles/";
function normalizeTileText(value: string): string {
  return value.normalize("NFKC").toLowerCase()
    .replace(/[萬万]/g, "m").replace(/[筒饼餅]/g, "p").replace(/[索條条]/g, "s")
    .replace(/東/g, "1z").replace(/南/g, "2z").replace(/西/g, "3z").replace(/北/g, "4z")
    .replace(/白/g, "5z").replace(/發/g, "6z").replace(/中/g, "7z")
    .replace(/[\s,，、;；|/]+/g, "");
}
function normalizeDiscardText(value: string): string {
  return value.normalize("NFKC").split(/[\s,，、;；|/]+/)
    .map(part => normalizeTileText(part)).filter(Boolean).join(", ");
}
function Tile({ value, small=false }: { value:string; small?:boolean }) {
  const [failed, setFailed] = useState(false);
  const n=value[0], suit=value[1];
  const honorFiles=["Ton","Nan","Shaa","Pei","Haku","Hatsu","Chun"];
  const honorNames=["东","南","西","北","白","发","中"];
  const suitFiles:Record<string,string>={m:"Man",p:"Pin",s:"Sou"};
  const suitNames:Record<string,string>={m:"万",p:"筒",s:"索"};
  const file=suit==="z"?honorFiles[Number(n)-1]:`${suitFiles[suit]}${n==="0"?"5-Dora":n}`;
  // The original Haku WebP was corrupt in an earlier generated tile set.
  // Keep the public-domain SVG as a deterministic fallback for this one face.
  const asset=`${TILE_ASSET_ROOT}${file}${file==="Haku"?".svg":".webp"}`;
  const alt=suit==="z"?`${honorNames[Number(n)-1]}风牌`:`${n==="0"?"赤五":n}${suitNames[suit]}`;
  useEffect(()=>setFailed(false),[file]);
  return <span className={`tile ${small?"small":""} ${failed?"tile-failed":""}`}>{!failed&&<img src={asset} alt={alt} width="150" height="200" decoding="async" onError={()=>setFailed(true)}/>}<span className="tile-fallback">{value}</span></span>;
}
function Hand({ source, small=false }: { source:string|string[]; small?:boolean }) { const tiles=Array.isArray(source)?source:parseTiles(source); return <div className="hand">{tiles.map((tile,index)=><Tile key={`${tile}-${index}`} value={tile} small={small}/>)}</div>; }

function Brand() { return <div className="brand"><img className="brand-mascot" src="/mascot.webp" alt="MortalSim 原创红蟹吉祥物"/><div><strong>MortalSim</strong><span>Rust core · GPU</span></div></div>; }

export default function App() {
  const [page,setPage]=useState("run"), [config,setConfig]=useState(initial), [cap,setCap]=useState<any>(null), [runs,setRuns]=useState<RunRecord[]>([]);
  const [status,setStatus]=useState("idle"), [progress,setProgress]=useState<any>({completed:0,total:0}), [runId,setRunId]=useState<string|null>(null), [result,setResult]=useState<RunResult|null>(null), [error,setError]=useState("");
  const [gpu,setGpu]=useState<any>(null);
  const [models,setModels]=useState<ModelInfo[]>([]), [tasks,setTasks]=useState<ActiveTask[]>([]), [taskDrawer,setTaskDrawer]=useState(false), [notice,setNotice]=useState("");
  const taskSources=useRef<Record<string,EventSource>>({});
  const [pendingExtend,setPendingExtend]=useState(false);
  const candidates=useMemo(()=>normalizeDiscardText(config.discards).split(",").map(v=>v.trim()).filter(Boolean),[config.discards]);
  const refresh=()=>apiGet("/api/runs").then(r=>r.json()).then(setRuns).catch(()=>{});
  const refreshModels=()=>apiGet("/api/models").then(r=>r.json()).then(setModels).catch(()=>{});
  const refreshTasks=()=>apiGet("/api/tasks/active").then(r=>r.json()).then(setTasks).catch(()=>{});
  useEffect(()=>{apiGet("/api/capabilities").then(r=>r.json()).then(setCap).catch(()=>setCap({cuda_available:false}));refresh();refreshModels();refreshTasks();},[]);
  useEffect(()=>{
    const selected=models.find(model=>model.id===config.model_id);
    const firstReady=models.find(model=>model.ready&&model.lite_compatible);
    if((!selected||!selected.ready||!selected.lite_compatible)&&firstReady) setConfig(old=>({...old,model_id:firstReady.id}));
  },[models,config.model_id]);
  useEffect(()=>{
    for(const task of tasks){
      if(taskSources.current[task.run_id]) continue;
      const source=new EventSource(`/api/runs/${task.run_id}/events`); taskSources.current[task.run_id]=source;
      const handle=(event:MessageEvent)=>{const data=JSON.parse(event.data); if(data.type==="batch_completed")setTasks(old=>old.map(t=>t.run_id===task.run_id?{...t,progress:data}:t)); if(data.type==="gpu_status")setTasks(old=>old.map(t=>t.run_id===task.run_id?{...t,gpu_status:data}:t)); if(["completed","failed","cancelled"].includes(data.type)){source.close();delete taskSources.current[task.run_id];setTasks(old=>old.filter(t=>t.run_id!==task.run_id));refresh(); if(data.type==="completed"){setNotice(task.extension_of?"扩容已合并到原分析。":"模拟已完成。"); if(task.extension_of===runId)apiGet(`/api/runs/${runId}`).then(r=>r.json()).then(record=>setResult(record.result));} else setNotice(data.error||"任务未完成，原分析保持不变。");}};
      ["batch_completed","gpu_status","completed","failed","cancelled"].forEach(kind=>source.addEventListener(kind,handle as EventListener));
    }
    return undefined;
  },[tasks,runId]);
  useEffect(()=>()=>Object.values(taskSources.current).forEach(source=>source.close()),[]);
  useEffect(()=>{if(!runId||status!=="running")return; const source=new EventSource(`/api/runs/${runId}/events`); const event=(e:MessageEvent)=>{const data=JSON.parse(e.data);if(data.type==="batch_completed")setProgress(data);if(data.type==="gpu_status")setGpu(data);if(data.type==="completed"){setResult(data.result);setStatus("completed");source.close();refresh();}if(data.type==="failed"){setError(data.error||"运行失败");setStatus("failed");source.close();}}; ["batch_completed","gpu_status","completed","failed","cancelled"].forEach(name=>source.addEventListener(name,event as EventListener)); return()=>source.close();},[runId,status]);
  const update=(key:string,value:any)=>setConfig(old=>({...old,[key]:value}));
  const updateScore=(key:string,value:string)=>setConfig(old=>({...old,scores:{...old.scores,[key]:value}}));
  const start=async()=>{
    setError("");setResult(null);setStatus("starting");
    const { riichi_discards, ...requestConfig } = config;
    const payload={...requestConfig,hand:normalizeTileText(config.hand),dora:normalizeTileText(config.dora),discards:candidates.map(tile=>({tile,riichi:riichi_discards.includes(tile)})),runs:Number(config.runs),seed:Number(config.seed),honba:Number(config.honba),kyotaku:Number(config.kyotaku),scores:{self:Number(config.scores.self),shimocha:Number(config.scores.shimocha),toimen:Number(config.scores.toimen)},batch_size:1000,rayon_threads:Number(config.rayon_threads),engine:"lite",decision_contract:"stable_advantage_v2"};
    const response=await fetch("/api/runs",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if(!response.ok){const failure=await response.json().catch(()=>({}));setError(apiErrorMessage(failure.detail,"无法启动"));setStatus("failed");return;}
    const data=await response.json();setRunId(data.run_id);setProgress({completed:0,total:Number(config.runs)});setStatus("running");refreshTasks();
  };
  const cancel=async()=>{if(runId)await fetch(`/api/runs/${runId}/cancel`,{method:"POST"});setStatus("cancelled");refresh();};
  const rerunFormal=async(id:string)=>{setError("");const response=await fetch(`/api/runs/${id}/rerun-formal`,{method:"POST"});if(!response.ok){const body=await response.json().catch(()=>({}));setError(apiErrorMessage(body.detail,"无法创建正式 Lite 重跑"));return;}const data=await response.json();setResult(null);setRunId(data.run_id);setStatus("running");setPage("run");refreshTasks();};
  const openRun=(run:RunRecord)=>{setRunId(run.run_id);setResult(run.result||null);setStatus(run.status);setPage("run");};
  const busy=status==="running"||status==="starting";
  return <div className="shell">
    <aside><Brand/><nav aria-label="主导航">{[["run",BarChart3,"分析台"],["history",HistoryIcon,"历史运行"],["settings",Settings,"设置与诊断"]].map(([id,Icon,label]:any)=><button key={id} aria-label={label} title={label} className={page===id?"active":""} onClick={()=>setPage(id)}><Icon size={17}/><span>{label}</span></button>)}</nav><div className="aside-status"><span className={`status-dot ${cap?.formal_lite_ready?"ok":""}`}/><div><b>{cap?.formal_lite_ready?"正式 Lite 就绪":"正式 Lite 不可用"}</b><small>{cap?.gpu_name||"正在检测运行环境"}</small></div></div></aside>
    <main><header><div><span className="kicker">LOCAL RIICHI SIMULATION</span><h1>{page==="run"?"自亲第一打分析":page==="history"?"历史运行":"设置与诊断"}</h1></div><div className="header-status"><button className={`task-toggle ${tasks.length?"active":""}`} onClick={()=>setTaskDrawer(true)} aria-label="运行任务"><Layers3 size={15}/>任务 {tasks.length||""}</button><Activity size={15}/><span>数据仅保留在本机</span><code>v0.3.0-rc.1</code></div></header>
      {error&&<div className="alert">{error}</div>}{notice&&<div className="notice">{notice}<button onClick={()=>setNotice("")} aria-label="关闭提示"><X size={14}/></button></div>}
      {page==="run"&&<>{!result&&<Workbench config={config} update={update} updateScore={updateScore} candidates={candidates} start={start} cancel={cancel} busy={busy} status={status} progress={progress} cap={cap} gpu={gpu} models={models} refreshModels={refreshModels}/>} {result&&<Results result={result} initialExtend={pendingExtend} onExtendOpened={()=>setPendingExtend(false)} onCreated={()=>{setPendingExtend(false);refreshTasks();setNotice("扩容已在后台开始，可继续浏览其他记录。");}} onRerun={()=>rerunFormal(result.run_id!)} onNew={()=>{setResult(null);setStatus("idle");}}/>}</>}
      {page==="history"&&<History runs={runs} activeTasks={tasks} open={openRun} extend={run=>{openRun(run);setPendingExtend(true);}} rerun={rerunFormal} refresh={refresh}/>}
      {page==="settings"&&<Diagnostics cap={cap} models={models} refreshModels={refreshModels}/>}
    </main>
    {taskDrawer&&<TaskDrawer tasks={tasks} close={()=>setTaskDrawer(false)} refresh={refreshTasks}/>}
  </div>;
}

function Workbench({config,update,updateScore,candidates,start,cancel,busy,status,progress,cap,gpu,models,refreshModels}:any){
  const sample=gpu?.sample||{};
  const enteredScores=["self","shimocha","toimen"].map(key=>Number(config.scores[key]));
  const kamicha=100000-Number(config.kyotaku)*1000-enteredScores.reduce((sum,value)=>sum+value,0);
  const scoreValid=enteredScores.every(value=>Number.isInteger(value)&&value>=0&&value%100===0)&&Number.isInteger(kamicha)&&kamicha>=0&&kamicha%100===0;
  const heldTiles=useMemo(()=>parseTiles(normalizeTileText(config.hand)),[config.hand]);
  const mainHaipai=heldTiles.slice(0,13);
  const firstTsumo=heldTiles[13];
  const candidateOptions=useMemo(()=>Array.from(new Set(heldTiles)),[heldTiles]);
  const riichiCandidates:string[]=config.riichi_discards||[];
  const illegalCandidates=candidates.filter((tile:string)=>!candidateOptions.includes(tile));
  const modelReady=models.some((model:ModelInfo)=>model.id===config.model_id&&model.ready&&model.lite_compatible);
  const readyToRun=heldTiles.length===14&&candidates.length>0&&illegalCandidates.length===0&&modelReady;
  const toggleCandidate=(tile:string)=>{
    const next=candidates.includes(tile)?candidates.filter((item:string)=>item!==tile):[...candidates,tile];
    update("discards",next.join(", "));
    if(!next.includes(tile)) update("riichi_discards",riichiCandidates.filter((item:string)=>item!==tile));
  };
  const toggleRiichi=(tile:string)=>update("riichi_discards",riichiCandidates.includes(tile)?riichiCandidates.filter((item:string)=>item!==tile):[...riichiCandidates,tile]);
  const semanticLocked=busy;
  return <>
    <section className="context-band"><div className="context-title"><span>局面</span><b>{roundLabel(config.round)} · 自亲</b></div><div className="context-hand"><Hand source={mainHaipai}/><span className="draw-sep"/>{firstTsumo&&<Tile value={firstTsumo}/>}</div><div className="context-dora"><span>宝牌指示</span><Tile value={config.dora} small/></div></section>
    <div className="work-grid"><form className="surface input-surface" onSubmit={event=>{event.preventDefault();start();}}><div className="surface-head"><div><span className="kicker">SIMULATION INPUT</span><h2>局面与候选</h2></div><span className="quiet">相同 seed 配对比较</span></div>
      <fieldset disabled={semanticLocked}><legend>局面</legend><div className="fields scene-fields"><label><span>局目</span><select value={config.round} onChange={e=>update("round",e.target.value)}>{ROUND_OPTIONS.map(([id,label])=><option value={id} key={id}>{label}</option>)}</select></label><Field label="本场" value={config.honba} change={(v:string)=>update("honba",v)} type="number" min={0} max={99}/><Field label="供托" value={config.kyotaku} change={(v:string)=>update("kyotaku",v)} type="number" min={0} max={99}/></div></fieldset>
      <fieldset disabled={semanticLocked}><legend>点数</legend><div className="score-grid"><ScoreField label="自家" value={config.scores.self} change={(v:string)=>updateScore("self",v)}/><ScoreField label="下家" value={config.scores.shimocha} change={(v:string)=>updateScore("shimocha",v)}/><ScoreField label="对面" value={config.scores.toimen} change={(v:string)=>updateScore("toimen",v)}/><label><span>上家（自动）</span><input readOnly aria-readonly="true" value={Number.isFinite(kamicha)?String(kamicha):""}/></label></div><div className={`score-check ${scoreValid?"valid":"invalid"}`}>{scoreValid?`校验通过：四家点数与 ${config.kyotaku} 根供托合计 100,000 点`:"点数必须为非负百点整数，且自动计算的上家点数不能为负"}</div></fieldset>
      <fieldset disabled={semanticLocked}><legend>模拟</legend><ModelPicker models={models} modelId={config.model_id} change={(value:string)=>update("model_id",value)} refresh={refreshModels}/><label className="wide"><span>手牌（含第一摸，最后一张）</span><input value={config.hand} onChange={e=>update("hand",e.target.value)} onBlur={e=>update("hand",normalizeTileText(e.target.value))} placeholder="4567m3477p134066s"/></label><div className={`input-check ${heldTiles.length===14?"valid":heldTiles.length===0?"":"invalid"}`}>{heldTiles.length===14?`已识别 14 张，最后一张 ${firstTsumo||""} 作为第一摸。`:heldTiles.length===0?"请输入 14 张手牌，最后一张将作为第一摸。":`当前识别 ${heldTiles.length} 张，需要恰好 14 张。`}</div><div className="fields simulation-fields"><Field label="宝牌指示" value={config.dora} change={(v:string)=>update("dora",v)} normalize={normalizeTileText}/><Field label="模拟局数" value={config.runs} change={(v:string)=>update("runs",v)} type="number" min={1}/></div><label className="wide"><span>候选第一打，逗号分隔</span><input value={config.discards} onChange={e=>update("discards",e.target.value)} onBlur={e=>update("discards",normalizeDiscardText(e.target.value))} placeholder="1s, 6s"/></label><div className="discard-picker" role="group" aria-label="从当前手牌选择候选第一打">{candidateOptions.map(tile=><button key={tile} type="button" aria-pressed={candidates.includes(tile)} className={candidates.includes(tile)?"selected":""} onClick={()=>toggleCandidate(tile)}><Tile value={tile} small/><span>打 {tile}</span></button>)}</div>{illegalCandidates.length>0&&<div className="input-check invalid">候选 {illegalCandidates.join("、")} 不在当前可打牌中。</div>}<div className="candidate-tiles">{candidates.map((value:string)=><div key={value}><Tile value={value}/><span>{riichiCandidates.includes(value)?`立直打 ${value}`:`打 ${value}`}</span><button type="button" className={`riichi-toggle ${riichiCandidates.includes(value)?"enabled":""}`} aria-pressed={riichiCandidates.includes(value)} title="首打时宣告立直" onClick={()=>toggleRiichi(value)}>立</button></div>)}</div></fieldset>
      <details className="advanced"><summary>高级设置</summary><div className="fields"><Field label="Seed" value={config.seed} change={(v:string)=>update("seed",v)} type="number"/><label><span>Batch（正式契约）</span><input type="number" value="1000" readOnly aria-readonly="true"/></label><Field label="Rayon 线程" value={config.rayon_threads} change={(v:string)=>update("rayon_threads",v)} type="number" min={1}/></div><p className="model-note">正式 Lite 固定 Batch 1000，原生图容量 1024；改变 Batch 会改变决策契约。</p></details>
      <div className="actions"><label className="toggle"><input disabled={semanticLocked} type="checkbox" checked={config.strict_comparison} onChange={e=>update("strict_comparison",e.target.checked)}/><span/>固定 seed 严格比较</label><button className="secondary reset-input" type="button" disabled={semanticLocked} onClick={()=>update("discards","")}>清空候选</button><button className="primary" type="submit" disabled={busy||!cap?.formal_lite_ready||!scoreValid||!readyToRun}><Play size={16} fill="currentColor"/>开始模拟</button></div>
      {!cap?.formal_lite_ready&&<div className="input-check invalid">{cap?.cuda_error||"正式 Lite 运行时尚未通过兼容性检查，请前往设置与诊断查看。"}</div>}
    </form><section className="surface runtime"><div className="surface-head"><div><span className="kicker">LIVE RUNTIME</span><h2>GPU 运行状态</h2></div><span className={`run-badge ${busy?"live":""}`}>{status}</span></div><div className="runtime-focus"><Gauge size={26}/><div><span>{busy?`正在模拟 ${progress.discard||"候选"}`:"等待任务"}</span><b>{progress.total?`${progress.completed}/${progress.total}`:"0/0"}</b></div></div><div className="progress"><i style={{width:`${progress.total?progress.completed/progress.total*100:0}%`}}/></div><div className="runtime-metrics"><Mini label="温度" value={sample["temperature.gpu"]!=null?`${sample["temperature.gpu"]}°C`:"—"}/><Mini label="利用率" value={sample["utilization.gpu"]!=null?`${sample["utilization.gpu"]}%`:"—"}/><Mini label="显存" value={sample["memory.used"]!=null?`${sample["memory.used"]}/${sample["memory.total"]} MiB`:"—"}/><Mini label="功耗" value={sample["power.draw"]!=null?`${sample["power.draw"]} W`:"—"}/><Mini label="后端" value="Formal Lite v2"/><Mini label="Rayon" value={`${config.rayon_threads} threads`}/></div>{gpu?.message&&<div className={`gpu-warning ${gpu.level}`}>{gpu.message}</div>}{busy&&<button className="stop" onClick={cancel}><CircleStop size={16}/>取消任务</button>}</section></div>
  </>;
}
function Field({label,value,change,type="text",min,max,normalize}:any){return <label><span>{label}</span><input type={type} min={min} max={max} value={value} onChange={e=>change(e.target.value)} onBlur={normalize ? (e=>change(normalize(e.target.value))) : undefined}/></label>}
function ScoreField({label,value,change}:any){return <label><span>{label}</span><input type="number" min="0" step="100" inputMode="numeric" value={value} onChange={e=>change(e.target.value)}/></label>}
function Mini({label,value}:any){return <div><span>{label}</span><b>{value}</b></div>}
function ModelPicker({models,modelId,change,refresh}:any){
  const [message,setMessage]=useState(""), inputRef=useRef<HTMLInputElement>(null);
  const upload=async(file:File)=>{setMessage(`正在校验 ${file.name}…`);const response=await fetch(`/api/models/import?filename=${encodeURIComponent(file.name)}`,{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});if(!response.ok){const body=await response.json().catch(()=>({}));setMessage(apiErrorMessage(body.detail,"模型导入失败"));return;}const model=await response.json();refresh();change(model.id);setMessage(model.duplicate?"模型已在本机库中，已选中。":"模型结构、张量与 SHA256 已校验，可用于正式 Lite。");};
  const selected=models.find((model:ModelInfo)=>model.id===modelId);
  return <div className="model-picker"><label className="wide"><span>推理模型</span><select value={selected?modelId:""} onChange={event=>change(event.target.value)}><option value="" disabled>请先导入兼容权重</option>{models.map((model:ModelInfo)=><option value={model.id} key={model.id} disabled={!model.ready||!model.lite_compatible}>{model.label} · v{model.version||"?"} · {model.ready&&model.lite_compatible?"正式 Lite 可用":"不兼容"}</option>)}</select></label><button type="button" className="secondary import-model" onClick={()=>inputRef.current?.click()}><FileUp size={15}/>导入 .pth</button><input ref={inputRef} className="visually-hidden" type="file" accept=".pth" onChange={event=>{const file=event.target.files?.[0];if(file)upload(file);event.currentTarget.value="";}}/>{selected?.ready&&selected.lite_compatible?<p className="model-note">{selected.filename} · SHA {selected.sha256?.slice(0,12)||"待校验"} · {selected.conv_channels||"?"}ch / {selected.num_blocks||"?"} blocks · stable_advantage_v2</p>:<p className="model-note">尚无正式 Lite 兼容模型，请导入 v4 / 256ch / 54 blocks 的 Mortal .pth 权重。</p>}{message&&<p className="model-note">{message}</p>}</div>;
}

function Results({result,onNew,onCreated,onRerun,initialExtend,onExtendOpened}:{result:RunResult;onNew:()=>void;onCreated:()=>void;onRerun:()=>void;initialExtend:boolean;onExtendOpened:()=>void}){
  const candidates=(result.candidates||result.summaries||[]).map(normalizeCandidate); const base=candidates[0]; const winner=candidates.reduce((best,c)=>((c.avg_point??-Infinity)>(best?.avg_point??-Infinity)?c:best),base); const [open,setOpen]=useState<Record<string,boolean>>({value:true,outcome:true,win:true,defense:true,riichi:true,tenpai:false,call:false,yaku:false}); const [drawer,setDrawer]=useState<{candidate:Candidate;metric:string}|null>(null);
  const [extend,setExtend]=useState(false);
  useEffect(()=>{if(initialExtend){setExtend(true);onExtendOpened();}},[initialExtend,onExtendOpened]);
  const alternative=candidates.filter(candidate=>candidateKey(candidate)!==candidateKey(winner)).reduce((best,candidate)=>((candidate.avg_point??-Infinity)>(best?.avg_point??-Infinity)?candidate:best),undefined as Candidate|undefined);
  const winnerIsBase=winner&&base&&candidateKey(winner)===candidateKey(base);
  const comparedCandidate=winnerIsBase?alternative:winner;
  const comparison=result.comparisons?.find(item=>item.candidate===candidateKey(comparedCandidate||winner)||item.candidate===comparedCandidate?.discard);
  const sourceDelta=comparison?.point_delta;
  const delta=winnerIsBase&&sourceDelta?{...sourceDelta,value:-sourceDelta.value,ci95:sourceDelta.ci95?[-sourceDelta.ci95[1],-sourceDelta.ci95[0]]:null}:sourceDelta;
  const verdictReference=winnerIsBase?alternative:base;
  const clear=delta?.ci95&&(delta.ci95[0]>0||delta.ci95[1]<0);
  const pointMetricsAvailable=result.metrics_version===2;
  const canExtend=result.schema_version===3&&result.metrics_version===2&&result.merge_state_version===2&&result.decision_contract==="stable_advantage_v2"&&Boolean(result.run_id);
  const legacySchema=(result.schema_version||1)<3;
  const needsFormalRerun=legacySchema||(result.schema_version===3&&result.merge_state_version!==2);
  const resolvedInput=result.resolved_input||{};
  const resultHand=resolvedInput.main_haipai||result.config?.hand||"4567m3477p13406s";
  const resultFirstTsumo=resolvedInput.first_tsumo||result.config?.first_tsumo||"6s";
  const resultDora=resolvedInput.dora||result.config?.dora||"9s";
  return <div className="result-page"><section className="result-context"><button className="icon-button" aria-label="返回新分析" title="返回新分析" onClick={onNew}><RotateCcw size={17}/></button><div><span>{roundLabel(result.config?.round||result.resolved_context?.round||"E1")}</span><Hand source={resultHand} small/></div><div><span>第一摸</span><Tile value={resultFirstTsumo} small/></div><div><span>宝牌指示</span><Tile value={resultDora} small/></div>{needsFormalRerun?<button className="extend-button" onClick={onRerun} title="复制局面与 seed，按当前正式 Lite 创建新记录"><RotateCcw size={15}/>重跑正式 Lite</button>:<button className="extend-button" disabled={!canExtend} onClick={()=>setExtend(true)} title={canExtend?"向本分析追加相同配置的模拟":"决策契约、运行时身份或精确合并状态不允许扩容"}><Plus size={15}/>增加局数</button>}<div className="context-facts"><b>{result.total_runs||result.runs} 局 / 候选</b><span>seed {result.seed} · {result.model?.label||result.model?.id||"Mortal"} · {result.decision_contract==="stable_advantage_v2"?"正式 Lite v2":"旧 AMP 语义"}</span></div><span className={`contract-badge ${needsFormalRerun?"legacy-contract":""}`}>{result.decision_contract||"legacy_amp_v1"}</span></section>
    {result.schema_version===1&&<div className="legacy">旧版统计不完整，无法可靠推导五类终局与役种。</div>}
    {result.schema_version===2&&result.metrics_version===1&&<div className="legacy">该历史记录使用已废止的统计口径，平均局收支不可用；请按相同设置重新模拟。</div>}
    {result.schema_version===2&&result.metrics_version===2&&<div className="legacy">该记录使用旧决策语义，只读且不能扩容。可复制原局面、seed、模型和候选，按正式 Lite 创建新记录。</div>}
    {result.schema_version===3&&result.merge_state_version!==2&&<div className="legacy">该早期 RC 记录缺少双响等终局所需的精确扩容状态，只读且不能追加；请按当前正式 Lite 重跑。</div>}
    {pointMetricsAvailable?<section className="verdict"><div className="verdict-tile"><Tile value={winner?.discard||"1s"}/></div><div><span className="kicker">RECOMMENDED DISCARD</span><h2>推荐第一打：{winner&&candidateLabel(winner)}</h2><p>{comparison&&verdictReference?<>相对 {candidateLabel(verdictReference)} 配对局收支 <strong>{signed(delta?.value)}</strong>，95% CI {ci(delta?.ci95)}。</>:"当前只有一个候选，可查看完整分布。"}</p></div><span className={`confidence ${clear?"clear":""}`}>{clear?"差异明确":"尚不明确"}</span></section>:<section className="verdict legacy-verdict"><div><span className="kicker">RETIRED METRICS</span><h2>旧记录需要重新模拟</h2><p>该记录不再生成推荐结论或局收支比较。</p></div></section>}
    {result.warnings?.map(w=><div className="notice" key={w}>{w}</div>)}
    <section className="metric-workbench"><div className="metric-toolbar"><div><span className="kicker">FULL METRICS</span><h2>候选指标总表</h2></div><details className="export-menu"><summary><Download size={15}/>导出结果</summary><div role="menu"><a role="menuitem" href={`/api/runs/${result.run_id}/export?format=xlsx`}><b>Excel</b><span>当前总表中的全部统计指标</span></a><a role="menuitem" href={`/api/runs/${result.run_id}/export?format=json`}><b>JSON</b><span>完整结果协议，适合复现和二次分析</span></a><a role="menuitem" href={`/api/runs/${result.run_id}/export?format=html`}><b>HTML</b><span>无需应用即可打开的离线报告</span></a></div></details></div>
      <div className="metric-table" style={{"--candidate-count": candidates.length} as CSSProperties}><div className="metric-row table-header"><span>指标</span>{candidates.map(c=><b key={candidateKey(c)}><Tile value={c.discard} small/>{candidateLabel(c)}</b>)}</div>
      <Group id="value" label="价值与顺位" open={open.value} toggle={()=>setOpen(o=>({...o,value:!o.value}))}><Row label="平均局收支（NAGA 口径）" values={candidates.map(c=>result.metrics_version===2?signed(c.value.point.value):"不可用")}/><Row label="局收支 95% CI" values={candidates.map(c=>result.metrics_version===2?ci(c.value.point.ci95):"不可用")}/><Row label="平均终局顺位" values={candidates.map(c=>num(c.rank.average.value,3))}/>{[0,1,2,3].map(i=><Row key={i} label={`${i+1} 位率`} values={candidates.map(c=>rateText(c.rank.positions[i]))}/>)}</Group>
      <Group id="outcome" label="五类终局" open={open.outcome} toggle={()=>setOpen(o=>({...o,outcome:!o.outcome}))}>{OUTCOME_META.map(([id,label])=><ClickableRow key={id} label={label} candidates={candidates} metric={`outcome.${id}`} values={candidates.map(c=>rateText(c.outcome[id]))} open={setDrawer}/>)}<ClickableRow label="其中：自家荣和" candidates={candidates} metric="outcome.self_ron" values={candidates.map(c=>rateText(c.outcome.self_ron))} open={setDrawer}/><ClickableRow label="其中：自家自摸" candidates={candidates} metric="outcome.self_tsumo" values={candidates.map(c=>rateText(c.outcome.self_tsumo))} open={setDrawer}/></Group>
      <Group id="win" label="和牌构成" open={open.win} toggle={()=>setOpen(o=>({...o,win:!o.win}))}><Row label="立直和牌占比" values={candidates.map(c=>rateText(c.win.riichi_share))}/><Row label="副露和牌占比" values={candidates.map(c=>rateText(c.win.open_share))}/><Row label="默听和牌占比" values={candidates.map(c=>rateText(c.win.dama_share))}/><Row label="自摸 / 荣和" values={candidates.map(c=>`${pct(c.win.tsumo_share?.rate)} / ${pct(c.win.ron_share?.rate)}`)}/><Row label="平均和牌点" values={candidates.map(c=>num(c.win.average_point))}/><Row label="平均和牌素点" values={candidates.map(c=>num(c.win.average_raw_point?.value))}/><Row label="平均翻数 / 符" values={candidates.map(c=>`${num(c.win.average_han?.value,2)} / ${num(c.win.average_fu?.value,1)}`)}/></Group>
      <Group id="defense" label="防守" open={open.defense} toggle={()=>setOpen(o=>({...o,defense:!o.defense}))}><Row label="放铳率" negative values={candidates.map(c=>rateText(c.defense.deal_in_rate))}/><Row label="被自摸率" negative values={candidates.map(c=>rateText(c.defense.other_tsumo_rate))}/><Row label="横移动率" values={candidates.map(c=>rateText(c.defense.sideways_rate))}/><Row label="平均放铳损失" negative values={candidates.map(c=>num(c.defense.average_deal_in_loss))}/><Row label="平均放铳巡目" values={candidates.map(c=>num(c.defense.average_deal_in_turn,2))}/></Group>
      <Group id="riichi" label="立直、听牌与副露" open={open.riichi} toggle={()=>setOpen(o=>({...o,riichi:!o.riichi}))}><Row label="立直率" values={candidates.map(c=>rateText(c.riichi.rate))}/><Row label="先制 / 追立占比" values={candidates.map(c=>`${pct(c.riichi.first_rate?.rate)} / ${pct(c.riichi.chase_rate?.rate)}`)}/><Row label="立直后和牌率" values={candidates.map(c=>rateText(c.riichi.win_after_rate))}/><Row label="平均立直巡目" values={candidates.map(c=>num(c.riichi.average_turn,2))}/><Row label="听牌率 / 首次听牌巡目" values={candidates.map(c=>`${pct(c.tenpai.rate?.rate)} / ${num(c.tenpai.average_first_turn?.value,2)}`)}/><Row label="副露率" values={candidates.map(c=>rateText(c.call.rate))}/><Row label="平均副露数 / 副露后和牌率" values={candidates.map(c=>`${num(c.call.average_count?.value,2)} / ${pct(c.call.win_after_rate?.rate)}`)}/></Group>
      <Group id="yaku" label="役种频率（稳定 55 槽位）" open={open.yaku} toggle={()=>setOpen(o=>({...o,yaku:!o.yaku}))}>{base?.yaku?.map((y,i)=><Row key={y.id} label={YAKU_NAMES[y.id]||y.id} values={candidates.map(c=>{const item=c.yaku[i];return item?.available?`${item.count} · ${pct(item.rate)}`:"不可用";})}/>)}</Group></div>
    </section>
    {pointMetricsAvailable&&<Charts candidates={candidates} comparisons={result.comparisons||[]}/>}
    {drawer&&<SampleDrawer runId={result.run_id!} candidate={drawer.candidate} metric={drawer.metric} close={()=>setDrawer(null)} showPoint={pointMetricsAvailable}/>}
    {extend&&<ExtensionDialog result={result} close={()=>setExtend(false)} created={onCreated}/>}
  </div>;
}
function rateText(rate:Rate|undefined){return !rate||rate.rate==null?"不可用":`${pct(rate.rate)} (${rate.count}/${rate.total})`}
function Group({label,open,toggle,children}:any){return <div className="metric-group"><button className="group-head" onClick={toggle}>{open?<ChevronDown size={16}/>:<ChevronRight size={16}/>}<span>{label}</span></button>{open&&children}</div>}
function Row({label,values,negative=false}:{label:string;values:string[];negative?:boolean}){return <div className="metric-row"><span>{label}</span>{values.map((v,i)=><b className={negative?"negative":""} key={i}>{v}</b>)}</div>}
function ClickableRow({label,values,candidates,metric,open}:any){return <div className="metric-row"><span>{label}</span>{values.map((v:string,i:number)=><button className="metric-link" key={i} onClick={()=>open({candidate:candidates[i],metric})}>{v}</button>)}</div>}

function Charts({candidates,comparisons}:{candidates:Candidate[];comparisons:any[]}){
 const outcomeOption=useMemo(()=>({tooltip:{trigger:"axis"},legend:{bottom:0,textStyle:{fontSize:11}},grid:{left:60,right:20,top:12,bottom:45},xAxis:{type:"value",max:100,axisLabel:{formatter:"{value}%"}},yAxis:{type:"category",data:candidates.map(c=>candidateLabel(c))},series:OUTCOME_META.map(([id,label,color])=>({name:label,type:"bar",stack:"all",itemStyle:{color},data:candidates.map(c=>(c.outcome[id]?.rate||0)*100)}))}),[candidates]);
 const rankOption=useMemo(()=>({tooltip:{trigger:"axis"},legend:{bottom:0},grid:{left:60,right:20,top:12,bottom:45},xAxis:{type:"value",max:100,axisLabel:{formatter:"{value}%"}},yAxis:{type:"category",data:candidates.map(c=>candidateLabel(c))},series:[0,1,2,3].map(i=>({name:`${i+1}位`,type:"bar",stack:"rank",itemStyle:{color:["#087f68","#68a99c","#c29a52","#9ba5aa"][i]},data:candidates.map(c=>(c.rank.positions[i]?.rate||0)*100)}))}),[candidates]);
 const forest=useMemo(()=>({tooltip:{trigger:"axis"},grid:{left:70,right:30,top:18,bottom:32},xAxis:{type:"value",axisLine:{onZero:true}},yAxis:{type:"category",data:comparisons.map(c=>candidateIdLabel(c.candidate))},series:[{type:"bar",data:comparisons.map(c=>({value:c.point_delta?.value||0,itemStyle:{color:(c.point_delta?.value||0)>=0?"#087f68":"#a64b42"}})),barWidth:14}]}),[comparisons]);
 const stability=useMemo(()=>({tooltip:{trigger:"axis"},legend:{bottom:0},grid:{left:60,right:20,top:15,bottom:45},xAxis:{type:"value",name:"局"},yAxis:{type:"value"},series:candidates.map((c,i)=>({name:candidateLabel(c),type:"line",showSymbol:false,lineStyle:{width:2,color:["#087f68","#a64b42","#a97f3d","#58778a"][i%4]},data:(c as any).stability?.map((p:any)=>[p.games,p.average_point])||[]}))}),[candidates]);
 const activeYaku=useMemo(()=>{
   const byId=new Map<string,{id:string; rate:number; count:number}>();
   for(const candidate of candidates) for(const item of candidate.yaku||[]){
     const current=byId.get(item.id)||{id:item.id,rate:0,count:0};
     current.rate+=item.rate||0; current.count+=item.count||0; byId.set(item.id,current);
   }
   return [...byId.values()].filter(item=>item.count>0).sort((a,b)=>b.rate-a.rate||a.id.localeCompare(b.id));
 },[candidates]);
 const yakuChartHeight=Math.max(320,activeYaku.length*34+76);
 const yakuHeat=useMemo(()=>({
   tooltip:{formatter:(p:any)=>{const [x,y,rate,count]=p.value;const yaku=activeYaku[y];return `${candidateLabel(candidates[x])}<br/>${YAKU_NAMES[yaku?.id]||yaku?.id||""}<br/>${pct(rate)} (${count} 局)`;}},
   grid:{left:156,right:24,top:16,bottom:54},
   xAxis:{type:"category",data:candidates.map(c=>candidateLabel(c)),axisLabel:{interval:0,rotate:candidates.length>8?35:0,fontSize:11,fontWeight:600},axisTick:{alignWithLabel:true}},
   yAxis:{type:"category",inverse:true,data:activeYaku.map(item=>YAKU_NAMES[item.id]||item.id),axisLabel:{interval:0,width:132,overflow:"truncate",fontSize:11},axisTick:{show:false}},
   series:[{type:"heatmap",label:{show:true,fontSize:11,fontWeight:700,formatter:(p:any)=>pct(p.value[2])},emphasis:{itemStyle:{borderColor:"#123e36",borderWidth:2}},data:activeYaku.flatMap((yaku,y)=>candidates.map((c,x)=>{const item=c.yaku.find(v=>v.id===yaku.id);const rate=item?.rate||0;return {value:[x,y,rate,item?.count||0],itemStyle:{color:`rgba(8,127,104,${.10+Math.min(rate,.9)*.90})`},label:{color:rate>=.34?"#fff":"#285b52"}};}))}]
 }),[candidates,activeYaku]);
 return <section className="charts"><div className="chart-panel"><h3>五类终局分布</h3><p>每个完成局只进入一个类别</p><EChart option={outcomeOption}/></div><div className="chart-panel"><h3>终局顺位分布</h3><p>1 位至 4 位占比</p><EChart option={rankOption}/></div><div className="chart-panel wide-chart"><h3>配对平均局收支差</h3><p>同 seed 候选相对参考第一打</p>{comparisons.length?<EChart option={forest}/>:<div className="chart-empty">至少两个候选后显示</div>}</div><div className="chart-panel"><h3>样本稳定性</h3><p>累计平均局收支随样本增加的变化</p><EChart option={stability}/></div><div className="chart-panel wide-chart yaku-panel"><h3>役种频率热力图</h3><p>按本次平均出现率排序；悬浮可查看和牌局数</p>{activeYaku.length?<EChart option={yakuHeat} className="chart-canvas yaku-chart" style={{"--yaku-chart-height":`${yakuChartHeight}px`} as CSSProperties}/>:<div className="chart-empty">本次没有自家和牌役种</div>}</div></section>
}
function ExtensionDialog({result,close,created}:{result:RunResult;close:()=>void;created:()=>void}){
  const [additional,setAdditional]=useState("1000"),[status,setStatus]=useState("idle"),[message,setMessage]=useState("");
  const dialogRef=useDialogFocus(close);
  const total=result.total_runs||result.runs||0, amount=Number(additional), seedStart=(result.seed||0)+total, seedEnd=seedStart+Math.max(0,amount)-1;
  const submit=async(event:FormEvent)=>{
    event.preventDefault();setMessage("");setStatus("starting");
    const response=await fetch(`/api/runs/${result.run_id}/extensions`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({additional_runs:amount,batch_size:Number(result.config?.batch_size||1000)})});
    if(!response.ok){const body=await response.json().catch(()=>({}));setMessage(apiErrorMessage(body.detail,"无法创建扩容任务"));setStatus("failed");return;}
    await response.json();created();close();
  };
  return <div className="modal-layer"><button className="scrim" onClick={close} aria-label="关闭增加局数窗口"/><section ref={dialogRef} className="modal" role="dialog" aria-modal="true" aria-labelledby="extension-title"><header><div><span className="kicker">EXTEND ANALYSIS</span><h2 id="extension-title">增加相同模拟局数</h2></div><button className="icon-button" aria-label="关闭" onClick={close}><X size={18}/></button></header><form onSubmit={submit}><div className="extension-summary"><span>当前局数<b>{total.toLocaleString()}</b></span><span>新增局数<b>{Number.isFinite(amount)?amount.toLocaleString():"—"}</b></span><span>目标总数<b>{Number.isFinite(amount)?(total+amount).toLocaleString():"—"}</b></span></div><label className="wide"><span>Batch（正式契约）</span><input type="number" value="1000" readOnly aria-readonly="true"/></label><p className="seed-preview">扩容严格继承模型 SHA、stable_advantage_v2、运行时 artifact SHA、Batch 1000 和全部规则。任一身份不一致都会拒绝合并。</p><label className="wide"><span>新增局数</span><input type="number" min="1" max="100000" step="1" value={additional} onChange={e=>setAdditional(e.target.value)}/></label><p className="seed-preview">将使用 seed {seedStart.toLocaleString()} 至 {seedEnd.toLocaleString()}。提交后任务转入后台，取消或失败不会修改原结果。</p>{message&&<div className="alert">{message}</div>}<div className="modal-actions"><button type="button" className="secondary" onClick={close}>暂不增加</button><button className="primary" type="submit" disabled={!Number.isInteger(amount)||amount<1||amount>100000}><Plus size={16}/>开始后台追加</button></div></form></section></div>;
}

function SampleDrawer({runId,candidate,metric,close,showPoint}:{runId:string;candidate:Candidate;metric:string;close:()=>void;showPoint:boolean}){
  const samples=candidate.samples?.[metric]||[], dialogRef=useDialogFocus(close);
  const replay=async(s:Sample)=>{await fetch(`/api/runs/${runId}/replay`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({candidate:candidateKey(candidate),seed:s.seed,expected_trace_hash:s.trace_hash})});};
  return <div className="modal-layer"><button className="scrim" onClick={close} aria-label="关闭样本抽屉"/><aside ref={dialogRef} className="drawer" role="dialog" aria-modal="true" aria-labelledby="sample-title"><header><div><span className="kicker">SAMPLE DRILLDOWN</span><h2 id="sample-title">{metric} · {candidateLabel(candidate)}</h2></div><button className="icon-button" aria-label="关闭" onClick={close}><X size={18}/></button></header><p className="drawer-note">最多保存 100 个确定性代表样本。复跑会强制使用相同候选、seed、模型与规则。</p><div className="sample-list">{samples.map((s,i)=><div className="sample" key={`${JSON.stringify(s.seed)}-${i}`}><div><b>seed {Array.isArray(s.seed)?s.seed.join(":"):s.seed}</b><span>{s.outcome}{showPoint?` · ${signed(s.point)}`:""} · {s.rank} 位</span><code>{s.trace_hash?.slice(0,16)||"无 trace"}</code></div><button aria-label={`复跑 seed ${s.seed}`} title="复跑该样本" onClick={()=>replay(s)}><RotateCcw size={15}/></button></div>)}{!samples.length&&<div className="chart-empty">该指标没有保存样本</div>}</div></aside></div>;
}

function TaskDrawer({tasks,close,refresh}:{tasks:ActiveTask[];close:()=>void;refresh:()=>void}){
  const dialogRef=useDialogFocus(close);
  const cancel=async(task:ActiveTask)=>{if(!window.confirm("取消后本次扩容不会合并到原分析。确定取消吗？"))return;await fetch(`/api/runs/${task.run_id}/cancel`,{method:"POST"});refresh();};
  return <div className="modal-layer"><button className="scrim" onClick={close} aria-label="关闭运行任务"/><aside ref={dialogRef} className="drawer task-drawer" role="dialog" aria-modal="true" aria-labelledby="task-title"><header><div><span className="kicker">BACKGROUND TASKS</span><h2 id="task-title">运行任务</h2></div><button className="icon-button" onClick={close} aria-label="关闭"><X size={18}/></button></header>{tasks.map(task=>{const progress=task.progress||{},gpu=task.gpu_status?.sample||{};const extension=Boolean(task.extension_of);return <section className="task-card" key={task.run_id}><div><b>{extension?"追加模拟":"新分析"}</b><span>{task.request.discards?.map(requestCandidateLabel).join(" / ")} · Batch {task.request.batch_size}</span></div><strong>{progress.completed||0}/{progress.total||task.request.runs||0}</strong><div className="progress"><i style={{width:`${progress.total?(progress.completed||0)/progress.total*100:0}%`}}/></div><small>{task.request.model_id||"mortal-v4-20240308"} · {gpu["temperature.gpu"]??"—"}°C · {gpu["memory.used"]??"—"} MiB</small><button className="stop" onClick={()=>cancel(task)}><CircleStop size={16}/>取消任务</button></section>})}{!tasks.length&&<div className="task-empty"><img src="/mascot.webp" alt=""/><b>没有正在运行的任务</b><span>后台模拟会显示在这里。</span></div>}</aside></div>;
}

function History({runs,activeTasks,open,extend,rerun,refresh}:{runs:RunRecord[];activeTasks:ActiveTask[];open:(run:RunRecord)=>void;extend:(run:RunRecord)=>void;rerun:(id:string)=>void;refresh:()=>void}){
  const remove=async(id:string)=>{if(!window.confirm("确定删除这条历史分析？此操作无法撤销。"))return;await fetch(`/api/runs/${id}`,{method:"DELETE"});refresh();};
  return <section className="surface history"><div className="surface-head"><div><span className="kicker">RUN ARCHIVE</span><h2>本机历史结果</h2></div><span className="quiet">{runs.length} 条记录</span></div><div className="history-head"><span>运行时间 / 候选</span><span>状态</span><span>版本</span><span>操作</span></div>{runs.map(run=>{const extending=activeTasks.some(task=>task.extension_of===run.run_id);const formal=run.result?.schema_version===3&&run.result?.decision_contract==="stable_advantage_v2";const exactMerge=formal&&run.result?.merge_state_version===2;const canExtend=run.status==="completed"&&exactMerge&&run.result?.metrics_version===2&&!extending;const canRerun=run.status==="completed"&&!exactMerge;return <div className="history-row" key={run.run_id}><button className="history-open" onClick={()=>open(run)}><span><b>{run.request.discards?.map(requestCandidateLabel).join(" / ")}</b><small>{new Date(run.created_at).toLocaleString()} · {(run.result?.total_runs||run.result?.runs||run.request.runs||0).toLocaleString()} 局 · {run.result?.model?.label||run.request.model_id||"Mortal v4"}</small></span><span className={`run-badge ${extending?"live":""}`}>{extending?"扩容中":run.status}</span><code>{exactMerge?"Formal Lite v2 · merge v2":formal?"Formal Lite v2 · 早期合并":`schema v${run.result?.schema_version||1} · 旧语义`}</code></button><div className="history-actions">{canRerun&&<button className="icon-button" aria-label="按正式 Lite 重跑" title="复制局面与 seed，创建当前正式 Lite 新记录" onClick={()=>rerun(run.run_id)}><RotateCcw size={16}/></button>}<button className="icon-button" aria-label="增加局数" title={extending?"该分析正在扩容":canExtend?"增加局数":"缺少当前正式 Lite 的精确合并状态"} disabled={!canExtend} onClick={()=>extend(run)}><Plus size={16}/></button><button className="icon-button" aria-label="删除" title="删除" onClick={()=>remove(run.run_id)}><X size={16}/></button></div></div>})}{!runs.length&&<div className="empty-state"><Archive size={30}/><b>还没有历史运行</b><span>完成一次分析后，结果会自动保存在本机。</span></div>}</section>;
}
function Diagnostics({cap,models,refreshModels}:{cap:any;models:ModelInfo[];refreshModels:()=>void}){const readyModels=models.filter(model=>model.ready&&model.lite_compatible);return <div className="diagnostics"><section className="surface"><span className="kicker">FORMAL LITE RUNTIME</span><h2>运行能力</h2>{[["状态",cap?.formal_lite_ready?"正式 Lite 就绪":"不兼容"],["GPU",cap?.gpu_name],["Compute Capability",cap?.compute_capability],["决策契约","stable_advantage_v2"],["运行时 Build",cap?.runtime_build_id],["Artifact SHA",cap?.runtime_artifact_sha256?.slice(0,20)],["模型",readyModels.length?`${readyModels.length} 个兼容`:"未导入"],["数据目录",cap?.data_dir]].map(([k,v])=><div className="diagnostic-row" key={k}><span>{k}</span><code>{v||"不可用"}</code></div>)}{cap?.cuda_error&&<div className="input-check invalid">{cap.cuda_error}</div>}</section><section className="surface about"><span className="kicker">ABOUT</span><h2>MortalSim</h2><Brand/><p>本地运行的日麻第一打模拟与候选比较工具。正式推理使用面向 NVIDIA SM89 的无 PyTorch AOTInductor CUDA 图，稳定动作选择由 Rust 完成。</p><p>应用默认仅监听 127.0.0.1，不上传手牌、seed、结果或日志。权重由用户自行导入，不包含在应用或 Release 中。</p></section><section className="surface model-library"><div className="surface-head"><div><span className="kicker">LOCAL MODEL LIBRARY</span><h2>本机模型</h2></div><button className="icon-button" title="刷新模型库" aria-label="刷新模型库" onClick={refreshModels}><RotateCcw size={16}/></button></div>{models.map(model=><div className="model-row" key={model.id}><b>{model.label}</b><span>v{model.version} · {model.conv_channels}ch / {model.num_blocks} blocks · {model.ready&&model.lite_compatible?"正式 Lite 可用":model.incompatibility_reason||"不可用"}</span><code>{model.sha256?.slice(0,16)||"未校验"}</code></div>)}</section></div>}
