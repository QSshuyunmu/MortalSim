/// CustomKyokuRunner — batched multi-kyoku with direct Python engine calls.
use super::board::{Board, Poll, UNSHUFFLED};
use super::mortal_onnx::MortalOnnxEngine;
use crate::algo::agari::Agari;
use crate::algo::sp::SPWorkspace;
use crate::mjai::{Event, EventExt};
use crate::stat::Stat;
use crate::tile::Tile;
use crate::vec_ops::vec_add_assign;
use crate::{must_tile, tu8};
use ndarray::{Array2, Array3};
use numpy::{PyArray2, PyArray3};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use rand::prelude::*;
use rand_chacha::ChaCha12Rng;
use rayon::prelude::*;
use sha3::{Digest, Sha3_256};
use std::array;
use std::cell::RefCell;
use std::str::FromStr;
use std::time::{Duration, Instant};

thread_local! {
    static SP_WORKSPACE: RefCell<SPWorkspace> = RefCell::new(SPWorkspace::default());
}

#[derive(Default)]
struct RunProfile {
    build_game: Duration,
    scan: Duration,
    encode: Duration,
    numpy_wrap: Duration,
    react_batch: Duration,
    extract: Duration,
    decode: Duration,
    poll: Duration,
    take_log: Duration,
    stat: Duration,
    result_pack: Duration,
    loops: usize,
    encoded: usize,
    max_batch: usize,
    errors: usize,
    round_batches: Vec<usize>,
    round_encode: Vec<Duration>,
    round_infer: Vec<Duration>,
}

impl RunProfile {
    fn print(&self, total: Duration) {
        let ms = |d: Duration| d.as_secs_f64() * 1000.;
        eprintln!("\n=== MORTAL_RUST_PROFILE ===");
        eprintln!("  total             : {:10.1} ms", ms(total));
        eprintln!("  build_game        : {:10.1} ms", ms(self.build_game));
        eprintln!("  active scan       : {:10.1} ms", ms(self.scan));
        eprintln!("  encode_obs        : {:10.1} ms", ms(self.encode));
        eprintln!("  numpy wrap        : {:10.1} ms", ms(self.numpy_wrap));
        eprintln!("  react_batch       : {:10.1} ms", ms(self.react_batch));
        eprintln!("  return extract    : {:10.1} ms", ms(self.extract));
        eprintln!("  action decode     : {:10.1} ms", ms(self.decode));
        eprintln!("  board poll        : {:10.1} ms", ms(self.poll));
        eprintln!("  take_log/scan     : {:10.1} ms", ms(self.take_log));
        eprintln!("  target Stat       : {:10.1} ms", ms(self.stat));
        eprintln!("  result packing    : {:10.1} ms", ms(self.result_pack));
        eprintln!("  loops / obs       : {} / {}", self.loops, self.encoded);
        eprintln!(
            "  avg / max batch   : {:.1} / {}",
            self.encoded as f64 / self.loops.max(1) as f64,
            self.max_batch
        );
        eprintln!("  errors            : {}", self.errors);

        if !self.round_encode.is_empty() {
            let serial: Duration = self
                .round_encode
                .iter()
                .zip(&self.round_infer)
                .map(|(&encode, &infer)| encode + infer)
                .sum();
            let overlapped: Duration = self
                .round_encode
                .iter()
                .zip(&self.round_infer)
                .map(|(&encode, &infer)| encode.max(infer))
                .sum();
            let other = total.saturating_sub(serial);
            let perfect_total = other + overlapped;
            let mut batches = self.round_batches.clone();
            batches.sort_unstable();
            let percentile = |p: usize| batches[(batches.len() - 1) * p / 100];
            eprintln!(
                "  batch p10/p50/p90 : {} / {} / {}",
                percentile(10),
                percentile(50),
                percentile(90)
            );
            eprintln!("  serial enc+infer  : {:10.1} ms", ms(serial));
            eprintln!("  ideal overlap sum : {:10.1} ms", ms(overlapped));
            eprintln!("  ideal total floor : {:10.1} ms", ms(perfect_total));
            eprintln!(
                "  ideal max speedup  : {:10.2}x",
                total.as_secs_f64() / perfect_total.as_secs_f64()
            );
        }
    }
}

struct GameState {
    bs: super::board::BoardState,
    reactions: [EventExt; 4],
    is_first: bool,
    first_riichi: bool,
    pending_first_riichi_discard: bool,
    oya: u8,
    discard_tile: Tile,
    ended: bool,
    collected: bool,
    scores: [i32; 4],
    kyotaku_start: u8,
    enable_agari_guard: bool,
    error_msg: Option<String>,
    seed: (u64, u64),
    target_discards: u8,
    first_tenpai_turn: Option<u8>,
    target_agari_metrics: Option<TargetAgariMetrics>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ForcedFirstAction {
    Discard,
    Riichi,
    InvalidRiichi,
}

const STABLE_ADVANTAGE_V2: &str = "stable_advantage_v2";

/// Select the lowest action id among exact ties without ever considering an
/// illegal action.  This is the authoritative policy selector for the Lite
/// decision contract; keep it independent from Python/NumPy argmax behavior.
fn select_stable_action(
    scores: &[f32],
    legal: &[bool],
    excluded_action: Option<usize>,
) -> Result<usize, &'static str> {
    if scores.len() != crate::consts::ACTION_SPACE || legal.len() != crate::consts::ACTION_SPACE {
        return Err("stable selector expects 46 scores and mask entries");
    }

    let mut best: Option<(usize, f32)> = None;
    for action in 0..crate::consts::ACTION_SPACE {
        if !legal[action] || excluded_action == Some(action) {
            continue;
        }
        let score = scores[action];
        if score.is_nan() {
            return Err("stable selector rejected a NaN policy score");
        }
        match best {
            None => best = Some((action, score)),
            Some((_, best_score)) if score > best_score => best = Some((action, score)),
            _ => {}
        }
    }
    best.map(|(action, _)| action)
        .ok_or("stable selector found no legal action")
}

fn forced_first_action(
    is_first: bool,
    pending_riichi_discard: bool,
    wants_riichi: bool,
    can_riichi_discard: bool,
) -> Option<ForcedFirstAction> {
    if pending_riichi_discard {
        return Some(ForcedFirstAction::Discard);
    }
    if !is_first {
        return None;
    }
    if wants_riichi {
        return Some(if can_riichi_discard {
            ForcedFirstAction::Riichi
        } else {
            ForcedFirstAction::InvalidRiichi
        });
    }
    Some(ForcedFirstAction::Discard)
}

struct TargetAgariMetrics {
    agari: Agari,
    pattern_yakus: Vec<&'static str>,
    situational_yakus: Vec<&'static str>,
    dora: u8,
    aka_dora: u8,
    ura_tile_counts: [u8; 34],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RoundOutcome {
    SelfWin,
    SelfDealIn,
    Draw,
    Sideways,
    OtherTsumo,
    Error,
}

impl RoundOutcome {
    fn as_str(self) -> &'static str {
        match self {
            Self::SelfWin => "self_win",
            Self::SelfDealIn => "self_deal_in",
            Self::Draw => "draw",
            Self::Sideways => "sideways",
            Self::OtherTsumo => "other_tsumo",
            Self::Error => "error",
        }
    }
}

fn classify_round_outcome(
    target_player: u8,
    agaris: &[(u8, u8)],
    is_error: bool,
) -> (RoundOutcome, Option<&'static str>) {
    if is_error {
        return (RoundOutcome::Error, None);
    }
    if agaris.is_empty() {
        return (RoundOutcome::Draw, None);
    }
    if let Some(&(actor, target)) = agaris.iter().find(|&&(actor, _)| actor == target_player) {
        return (
            RoundOutcome::SelfWin,
            Some(if actor == target { "tsumo" } else { "ron" }),
        );
    }
    if agaris
        .iter()
        .any(|&(actor, target)| target == target_player && actor != target_player)
    {
        return (RoundOutcome::SelfDealIn, None);
    }
    if agaris.iter().any(|&(actor, target)| actor == target) {
        return (RoundOutcome::OtherTsumo, None);
    }
    (RoundOutcome::Sideways, None)
}

#[pyclass]
pub struct CustomKyokuRunner;

#[pymethods]
impl CustomKyokuRunner {
    #[new]
    fn new() -> Self {
        Self
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (engine, kyoku, honba, kyotaku, bakaze, oya, scores,
                        dora_marker, main_haipai, first_discard, seed,
                        first_tsumo = None, first_riichi = false))]
    fn run(
        &self,
        engine: PyObject,
        kyoku: u8,
        honba: u8,
        kyotaku: u8,
        bakaze: &str,
        oya: u8,
        scores: [i32; 4],
        dora_marker: &str,
        main_haipai: Vec<String>,
        first_discard: &str,
        seed: (u64, u64),
        first_tsumo: Option<String>,
        first_riichi: bool,
        py: Python<'_>,
    ) -> PyResult<PyObject> {
        let mut r = self.run_many(
            engine,
            kyoku,
            honba,
            kyotaku,
            bakaze,
            oya,
            scores,
            dora_marker,
            main_haipai,
            first_discard,
            seed,
            1,
            first_tsumo,
            first_riichi,
            py,
        )?;
        Ok(r.swap_remove(0))
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (engine, kyoku, honba, kyotaku, bakaze, oya, scores,
                        dora_marker, main_haipai, first_discard, seed_start, count,
                        first_tsumo = None, first_riichi = false))]
    fn run_many(
        &self,
        engine: PyObject,
        kyoku: u8,
        honba: u8,
        kyotaku: u8,
        bakaze: &str,
        oya: u8,
        scores: [i32; 4],
        dora_marker: &str,
        main_haipai: Vec<String>,
        first_discard: &str,
        seed_start: (u64, u64),
        count: u32,
        first_tsumo: Option<String>,
        first_riichi: bool,
        py: Python<'_>,
    ) -> PyResult<Vec<PyObject>> {
        let total_started = Instant::now();
        let profiling = std::env::var("MORTAL_PROFILE").is_ok_and(|v| v == "1");
        let tracing = std::env::var("MORTAL_TRACE").is_ok_and(|v| v == "1");
        let trace_events_enabled = std::env::var("MORTAL_TRACE_EVENTS").is_ok_and(|v| v == "1");
        let mut profile = RunProfile::default();
        let eng = engine.bind_borrowed(py);
        let ver: u32 = eng.getattr("version")?.extract()?;
        let decision_contract = eng
            .getattr("decision_contract")
            .and_then(|value| value.extract::<String>())
            .unwrap_or_else(|_| "legacy_amp_v1".to_owned());
        let stable_advantage = decision_contract == STABLE_ADVANTAGE_V2;

        // P1-5: Read enable_rule_based_agari_guard from engine
        let enable_agari_guard: bool = eng
            .getattr("enable_rule_based_agari_guard")
            .and_then(|v| v.extract())
            .unwrap_or(false);

        let parse = |s: &str| {
            Tile::from_str(s).map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("invalid tile: {e}"))
            })
        };
        let dora_tile = parse(dora_marker)?;
        let discard_tile = parse(first_discard)?;
        let first_tsumo_tile = first_tsumo.as_ref().map(|s| parse(s)).transpose()?;
        let hand: Vec<Tile> = main_haipai
            .iter()
            .map(|s| parse(s))
            .collect::<PyResult<Vec<_>>>()?;

        let build_started = profiling.then(Instant::now);
        let mut games: Vec<GameState> = Vec::with_capacity(count as usize);
        for i in 0..count {
            let seed = (seed_start.0.wrapping_add(i as u64), seed_start.1);
            games.push(build_game(
                &hand,
                dora_tile,
                discard_tile,
                first_tsumo_tile,
                kyoku,
                honba,
                kyotaku,
                bakaze,
                oya,
                scores,
                seed,
                enable_agari_guard,
                first_riichi,
            )?);
        }
        if let Some(started) = build_started {
            profile.build_game = started.elapsed();
        }

        let mut results: Vec<PyObject> = Vec::new();
        let mut safety = 0;

        while results.len() < count as usize && safety < 100000 {
            safety += 1;
            profile.loops += 1;

            // Phase 1: collect obs for all acting players
            let mut batch_map: Vec<(usize, usize)> = Vec::new();

            let scan_started = profiling.then(Instant::now);
            for (gi, g) in games.iter_mut().enumerate() {
                if g.ended {
                    continue;
                }
                let ctx = g.bs.agent_context();
                for (pid, st) in ctx.player_states.iter().enumerate() {
                    if !st.last_cans().can_act() {
                        continue;
                    }
                    if pid == g.oya as usize {
                        match forced_first_action(
                            g.is_first,
                            g.pending_first_riichi_discard,
                            g.first_riichi,
                            st.can_riichi_discard(g.discard_tile),
                        ) {
                            Some(ForcedFirstAction::Riichi) => {
                                g.is_first = false;
                                g.pending_first_riichi_discard = true;
                                g.reactions[pid] =
                                    EventExt::no_meta(Event::Reach { actor: pid as u8 });
                                continue;
                            }
                            Some(ForcedFirstAction::Discard) => {
                                g.is_first = false;
                                g.pending_first_riichi_discard = false;
                                let ts = st.last_self_tsumo().is_some_and(|t| t == g.discard_tile);
                                g.reactions[pid] = EventExt::no_meta(Event::Dahai {
                                    actor: pid as u8,
                                    pai: g.discard_tile,
                                    tsumogiri: ts,
                                });
                                continue;
                            }
                            Some(ForcedFirstAction::InvalidRiichi) => {
                                g.is_first = false;
                                g.ended = true;
                                g.error_msg = Some("first_discard_riichi_unavailable".to_owned());
                                continue;
                            }
                            None => {}
                        }
                    }
                    batch_map.push((gi, pid));
                }
            }
            if let Some(started) = scan_started {
                profile.scan += started.elapsed();
            }

            let batch_len = batch_map.len();
            profile.encoded += batch_len;
            profile.max_batch = profile.max_batch.max(batch_len);

            let shape = crate::consts::obs_shape(ver);
            let obs_len = shape.0 * shape.1;
            let encode_started = profiling.then(Instant::now);
            let mut obs_storage = vec![0.; batch_len * obs_len];
            let mut mask_storage = vec![[false; crate::consts::ACTION_SPACE]; batch_len];
            batch_map
                .par_iter()
                .zip(obs_storage.par_chunks_mut(obs_len))
                .zip(mask_storage.par_iter_mut())
                .for_each(|((&(gi, pid), obs), mask)| {
                    let st = &games[gi].bs.agent_context().player_states[pid];
                    SP_WORKSPACE.with_borrow_mut(|workspace| {
                        st.encode_obs_into_with_workspace(ver, false, obs, mask, workspace);
                    });
                });
            if let Some(started) = encode_started {
                let elapsed = started.elapsed();
                profile.encode += elapsed;
                profile.round_batches.push(batch_len);
                profile.round_encode.push(elapsed);
                profile.round_infer.push(Duration::ZERO);
            }

            // Phase 2: batched inference
            if batch_len != 0 {
                let call_started = profiling.then(Instant::now);
                let (actions, q_values, masks_recv, _is_greedy): (
                    Vec<usize>,
                    Vec<Vec<f32>>,
                    Vec<Vec<bool>>,
                    Vec<bool>,
                ) = if eng.is_instance_of::<MortalOnnxEngine>() {
                    let native: PyRef<'_, MortalOnnxEngine> = eng.extract()?;
                    let native_batch =
                        native.infer(&obs_storage, &mask_storage, shape.0, shape.1)?;
                    (
                        native_batch.actions,
                        native_batch.q_values,
                        mask_storage.iter().map(|mask| mask.to_vec()).collect(),
                        vec![true; batch_len],
                    )
                } else {
                    let wrap_started = profiling.then(Instant::now);
                    let obs_array =
                        Array3::from_shape_vec((batch_len, shape.0, shape.1), obs_storage)
                            .expect("observation batch shape");
                    let flat_masks: Vec<bool> = mask_storage.into_iter().flatten().collect();
                    let mask_array = Array2::from_shape_vec(
                        (batch_len, crate::consts::ACTION_SPACE),
                        flat_masks,
                    )
                    .expect("mask batch shape");
                    let batch_obs: Py<PyArray3<f32>> =
                        PyArray3::from_owned_array(py, obs_array).into();
                    let batch_mask: Py<PyArray2<bool>> =
                        PyArray2::from_owned_array(py, mask_array).into();
                    if let Some(started) = wrap_started {
                        profile.numpy_wrap += started.elapsed();
                    }
                    let args = (batch_obs, batch_mask, py.None());
                    let raw = eng.call_method1("react_batch", args).map_err(|e| {
                        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                            "react_batch: {e}"
                        ))
                    })?;
                    let extract_started = profiling.then(Instant::now);
                    let extracted = raw.extract().map_err(|e| {
                        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("extract: {e}"))
                    })?;
                    if let Some(started) = extract_started {
                        profile.extract += started.elapsed();
                    }
                    extracted
                };
                if let Some(started) = call_started {
                    let elapsed = started.elapsed();
                    profile.react_batch += elapsed;
                    *profile.round_infer.last_mut().expect("profile round") = elapsed;
                }

                let decode_started = profiling.then(Instant::now);
                for (i, &(gi, pid)) in batch_map.iter().enumerate() {
                    let g = &mut games[gi];
                    let orig_act = if stable_advantage {
                        select_stable_action(&q_values[i], &masks_recv[i], None).map_err(
                            |message| {
                                PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                                    "{message} at batch row {i}"
                                ))
                            },
                        )?
                    } else {
                        actions[i]
                    };
                    let actor = pid as u8;
                    let guard = g.enable_agari_guard;

                    let st = &g.bs.agent_context().player_states[pid];
                    let cans = st.last_cans();
                    let akas = st.akas_in_hand();

                    // P1-5: rule-based agari guard — if the engine wants agari
                    // but rule_based_agari() disagrees, fall back to the best
                    // alternative action by q_value (excluding action 43).
                    let act = if guard && orig_act == 43 && !st.rule_based_agari() {
                        select_stable_action(&q_values[i], &masks_recv[i], Some(43)).map_err(
                            |message| {
                                PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                                    "{message} after agari guard at batch row {i}"
                                ))
                            },
                        )?
                    } else {
                        orig_act
                    };

                    let ev = match act {
                        0..=36 if cans.can_discard => {
                            let pai = must_tile!(act);
                            let ts = st.last_self_tsumo().is_some_and(|t| t == pai);
                            Event::Dahai {
                                actor,
                                pai,
                                tsumogiri: ts,
                            }
                        }
                        37 if cans.can_riichi => Event::Reach { actor },

                        // P0-1: chi_low (action 38) — ported from mortal.rs
                        38 if cans.can_chi_low => st
                            .last_kawa_tile()
                            .map(|pai| {
                                let first = pai.next();
                                let can_aka = match pai.as_u8() {
                                    tu8!(3m) | tu8!(4m) => akas[0],
                                    tu8!(3p) | tu8!(4p) => akas[1],
                                    tu8!(3s) | tu8!(4s) => akas[2],
                                    _ => false,
                                };
                                let consumed = if can_aka {
                                    [first.akaize(), first.next().akaize()]
                                } else {
                                    [first, first.next()]
                                };
                                Event::Chi {
                                    actor,
                                    target: cans.target_actor,
                                    pai,
                                    consumed,
                                }
                            })
                            .unwrap_or(Event::None),
                        // P0-1: chi_mid (action 39)
                        39 if cans.can_chi_mid => st
                            .last_kawa_tile()
                            .map(|pai| {
                                let can_aka = match pai.as_u8() {
                                    tu8!(4m) | tu8!(6m) => akas[0],
                                    tu8!(4p) | tu8!(6p) => akas[1],
                                    tu8!(4s) | tu8!(6s) => akas[2],
                                    _ => false,
                                };
                                let consumed = if can_aka {
                                    [pai.prev().akaize(), pai.next().akaize()]
                                } else {
                                    [pai.prev(), pai.next()]
                                };
                                Event::Chi {
                                    actor,
                                    target: cans.target_actor,
                                    pai,
                                    consumed,
                                }
                            })
                            .unwrap_or(Event::None),
                        // P0-1: chi_high (action 40)
                        40 if cans.can_chi_high => st
                            .last_kawa_tile()
                            .map(|pai| {
                                let last = pai.prev();
                                let can_aka = match pai.as_u8() {
                                    tu8!(6m) | tu8!(7m) => akas[0],
                                    tu8!(6p) | tu8!(7p) => akas[1],
                                    tu8!(6s) | tu8!(7s) => akas[2],
                                    _ => false,
                                };
                                let consumed = if can_aka {
                                    [last.prev().akaize(), last.akaize()]
                                } else {
                                    [last.prev(), last]
                                };
                                Event::Chi {
                                    actor,
                                    target: cans.target_actor,
                                    pai,
                                    consumed,
                                }
                            })
                            .unwrap_or(Event::None),
                        // P0-1: pon (action 41)
                        41 if cans.can_pon => st
                            .last_kawa_tile()
                            .map(|pai| {
                                let can_aka = match pai.as_u8() {
                                    tu8!(5m) => akas[0],
                                    tu8!(5p) => akas[1],
                                    tu8!(5s) => akas[2],
                                    _ => false,
                                };
                                let consumed = if can_aka {
                                    [pai.akaize(), pai.deaka()]
                                } else {
                                    [pai.deaka(); 2]
                                };
                                Event::Pon {
                                    actor,
                                    target: cans.target_actor,
                                    pai,
                                    consumed,
                                }
                            })
                            .unwrap_or(Event::None),
                        // P0-1: kan (action 42) — daiminkan / ankan / kakan
                        42 if cans.can_daiminkan || cans.can_ankan || cans.can_kakan => {
                            if cans.can_daiminkan {
                                st.last_kawa_tile()
                                    .map(|pai| {
                                        let consumed = if pai.is_aka() {
                                            [pai.deaka(); 3]
                                        } else {
                                            [pai.akaize(), pai, pai]
                                        };
                                        Event::Daiminkan {
                                            actor,
                                            target: cans.target_actor,
                                            pai,
                                            consumed,
                                        }
                                    })
                                    .unwrap_or(Event::None)
                            } else if cans.can_ankan {
                                let cands = st.ankan_candidates();
                                if !cands.is_empty() {
                                    let tile = cands[0];
                                    Event::Ankan {
                                        actor,
                                        consumed: [tile.akaize(), tile, tile, tile],
                                    }
                                } else {
                                    Event::None
                                }
                            } else {
                                // kakan
                                let cands = st.kakan_candidates();
                                if !cands.is_empty() {
                                    let tile = cands[0];
                                    let can_aka_target = match tile.as_u8() {
                                        tu8!(5m) => akas[0],
                                        tu8!(5p) => akas[1],
                                        tu8!(5s) => akas[2],
                                        _ => false,
                                    };
                                    let (pai, consumed) = if can_aka_target {
                                        (tile.akaize(), [tile.deaka(); 3])
                                    } else {
                                        (tile.deaka(), [tile.akaize(), tile.deaka(), tile.deaka()])
                                    };
                                    Event::Kakan {
                                        actor,
                                        pai,
                                        consumed,
                                    }
                                } else {
                                    Event::None
                                }
                            }
                        }

                        43 if cans.can_agari() => Event::Hora {
                            actor,
                            target: cans.target_actor,
                            deltas: None,
                            ura_markers: None,
                        },
                        44 if cans.can_ryukyoku => Event::Ryukyoku { deltas: None },
                        _ => Event::None,
                    };
                    if actor == g.oya && matches!(&ev, Event::Hora { .. }) {
                        let is_ron = cans.can_ron_agari;
                        if let Ok((
                            agari,
                            pattern_yakus,
                            situational_yakus,
                            dora,
                            aka_dora,
                            ura_tile_counts,
                        )) = st.pending_agari_metrics(is_ron)
                        {
                            g.target_agari_metrics = Some(TargetAgariMetrics {
                                agari,
                                pattern_yakus,
                                situational_yakus,
                                dora,
                                aka_dora,
                                ura_tile_counts,
                            });
                        }
                    }
                    g.reactions[pid] = EventExt::no_meta(ev);
                }
                if let Some(started) = decode_started {
                    profile.decode += started.elapsed();
                }
            }

            // Phase 3: submit & advance (with error recovery)
            let poll_started = profiling.then(Instant::now);
            games
                .par_iter_mut()
                .enumerate()
                .for_each(|(gi, g)| advance_game(gi, g));
            if let Some(started) = poll_started {
                profile.poll += started.elapsed();
            }

            // Phase 4: collect finished games
            for g in games.iter_mut() {
                if !g.ended || g.collected {
                    continue;
                }
                g.collected = true;
                let kr = g.bs.end();
                let fs = kr.scores;
                let dl: [i32; 4] = score_deltas(fs, g.scores);
                let mut ord: Vec<usize> = (0..4).collect();
                ord.sort_by(|&a, &b| fs[b].cmp(&fs[a]));
                let mut rk = [0i32; 4];
                for (i, &p) in ord.iter().enumerate() {
                    rk[p] = i as i32 + 1;
                }

                let log_started = profiling.then(Instant::now);
                let log_events = g.bs.take_log();
                let mut agaris: Vec<(u8, u8)> = Vec::new();
                let mut ura_dora = 0u8;
                let round_balances = round_balances_from_events(&log_events);
                if g.error_msg.is_some() {
                    profile.errors += 1;
                }

                let trace_hash = tracing.then(|| {
                    let encoded = serde_json::to_vec(&log_events).expect("serialize game trace");
                    let digest = Sha3_256::digest(encoded);
                    digest
                        .iter()
                        .map(|byte| format!("{byte:02x}"))
                        .collect::<String>()
                });
                let trace_events = trace_events_enabled.then(|| {
                    log_events
                        .iter()
                        .filter_map(|event| serde_json::to_string(event).ok())
                        .collect::<Vec<_>>()
                });

                let target_stat: Option<PyObject> = if g.error_msg.is_none() {
                    for ev in &log_events {
                        if let Event::Hora {
                            actor,
                            target,
                            ura_markers,
                            ..
                        } = &ev.event
                        {
                            agaris.push((*actor, *target));
                            if *actor == g.oya {
                                if let (Some(markers), Some(metrics)) =
                                    (ura_markers, &g.target_agari_metrics)
                                {
                                    ura_dora = markers
                                        .iter()
                                        .map(|marker| {
                                            metrics.ura_tile_counts[marker.next().as_usize()]
                                        })
                                        .sum();
                                }
                            }
                        }
                    }
                    if let Some(started) = log_started {
                        profile.take_log += started.elapsed();
                    }

                    let events: Vec<Event> = log_events.into_iter().map(|e| e.event).collect();
                    let stat_started = profiling.then(Instant::now);
                    let mut stat = Stat::from_game(&events, g.oya);
                    stat.point = dl[g.oya as usize] as i64;
                    let stat = Py::new(py, stat).unwrap().into();
                    if let Some(started) = stat_started {
                        profile.stat += started.elapsed();
                    }
                    Some(stat)
                } else {
                    if let Some(started) = log_started {
                        profile.take_log += started.elapsed();
                    }
                    None
                };

                let (outcome, win_method) =
                    classify_round_outcome(g.oya, &agaris, g.error_msg.is_some());

                let pack_started = profiling.then(Instant::now);
                let ctx = g.bs.agent_context();
                let d = PyDict::new(py);
                let r = PyDict::new(py);
                r.set_item("type", outcome.as_str()).ok();
                r.set_item("outcome", outcome.as_str()).ok();
                r.set_item("final_scores", fs).ok();
                r.set_item("initial_scores", g.scores).ok();
                r.set_item("score_deltas", dl).ok();
                r.set_item("round_balances", round_balances).ok();
                r.set_item("kyotaku_start", g.kyotaku_start).ok();
                r.set_item("kyotaku_remaining", kr.kyotaku_left).ok();
                if let Some(error) = &g.error_msg {
                    r.set_item("error", error).ok();
                }
                r.set_item(
                    "agari_actors",
                    agaris.iter().map(|&(actor, _)| actor).collect::<Vec<_>>(),
                )
                .ok();
                r.set_item(
                    "agari_targets",
                    agaris.iter().map(|&(_, target)| target).collect::<Vec<_>>(),
                )
                .ok();
                if let Some(method) = win_method {
                    r.set_item("win_method", method).ok();
                }
                d.set_item("result", r).ok();
                let metrics = PyDict::new(py);
                metrics.set_item("version", 1).ok();
                let target_state = &ctx.player_states[g.oya as usize];
                metrics
                    .set_item("first_tenpai_turn", g.first_tenpai_turn)
                    .ok();
                metrics
                    .set_item("final_tenpai", target_state.shanten() == 0)
                    .ok();
                metrics
                    .set_item("riichi_declared", target_state.self_riichi_declared())
                    .ok();
                metrics
                    .set_item("riichi_accepted", target_state.self_riichi_accepted())
                    .ok();
                metrics
                    .set_item(
                        "fuuro_count",
                        target_state.chis().len()
                            + target_state.pons().len()
                            + target_state.minkans().len(),
                    )
                    .ok();
                metrics.set_item("target_discards", g.target_discards).ok();
                if let Some(agari) = &g.target_agari_metrics {
                    let (fu, han, yakuman, raw_point) = match agari.agari {
                        Agari::Normal { fu, han } => {
                            let final_han = han.saturating_add(ura_dora);
                            let point = Agari::Normal { fu, han: final_han }.point(true);
                            let raw_point = if win_method == Some("tsumo") {
                                point.tsumo_total(true)
                            } else {
                                point.ron
                            };
                            (Some(fu), Some(final_han), None, raw_point)
                        }
                        Agari::Yakuman(count) => {
                            let point = Agari::Yakuman(count).point(true);
                            let raw_point = if win_method == Some("tsumo") {
                                point.tsumo_total(true)
                            } else {
                                point.ron
                            };
                            (None, None, Some(count), raw_point)
                        }
                    };
                    let mut yakus = agari.pattern_yakus.clone();
                    yakus.extend(agari.situational_yakus.iter().copied());
                    metrics.set_item("yaku_ids", yakus).ok();
                    metrics.set_item("fu", fu).ok();
                    metrics.set_item("han", han).ok();
                    metrics.set_item("yakuman_count", yakuman).ok();
                    metrics.set_item("raw_win_point", raw_point).ok();
                    metrics.set_item("dora", agari.dora).ok();
                    metrics.set_item("aka_dora", agari.aka_dora).ok();
                    metrics.set_item("ura_dora", ura_dora).ok();
                }
                d.set_item("metrics", metrics).ok();
                d.set_item("seed", g.seed).ok();
                if let Some(hash) = trace_hash {
                    d.set_item("trace_hash", hash).ok();
                }
                if let Some(events) = trace_events {
                    d.set_item("trace_events", events).ok();
                }
                d.set_item(
                    "stat",
                    target_stat
                        .as_ref()
                        .map_or_else(|| py.None(), |s| s.clone_ref(py)),
                )
                .ok();
                let pl: Vec<PyObject> = (0..4)
                    .map(|pid| {
                        let p = PyDict::new(py);
                        let ps = &ctx.player_states[pid];
                        p.set_item("player_id", pid).unwrap();
                        p.set_item("is_oya", pid == g.oya as usize).unwrap();
                        p.set_item("final_score", fs[pid]).unwrap();
                        p.set_item("score_delta", dl[pid]).unwrap();
                        p.set_item("round_balance", round_balances[pid]).unwrap();
                        p.set_item("final_rank", rk[pid]).unwrap();
                        p.set_item("riichi_declared", ps.self_riichi_declared())
                            .unwrap();
                        p.set_item("riichi_accepted", ps.self_riichi_accepted())
                            .unwrap();
                        p.set_item("shanten", ps.shanten() as i32).unwrap();
                        p.set_item("agari", agaris.iter().any(|&(actor, _)| actor == pid as u8))
                            .unwrap();
                        p.set_item(
                            "deal_in",
                            agaris
                                .iter()
                                .any(|&(actor, target)| target == pid as u8 && actor != target),
                        )
                        .unwrap();
                        let stat = if pid == g.oya as usize {
                            target_stat
                                .as_ref()
                                .map_or_else(|| py.None(), |s| s.clone_ref(py))
                        } else {
                            py.None()
                        };
                        p.set_item("stat", stat).unwrap();
                        p.into()
                    })
                    .collect();
                d.set_item("players", pl).ok();
                results.push(d.into());
                if let Some(started) = pack_started {
                    profile.result_pack += started.elapsed();
                }
            }
        }
        if profiling {
            profile.print(total_started.elapsed());
        }
        Ok(results)
    }
}

fn advance_game(gi: usize, g: &mut GameState) {
    if g.ended {
        return;
    }
    let target_discarded = matches!(
        &g.reactions[g.oya as usize].event,
        Event::Dahai { actor, .. } if *actor == g.oya
    );
    let mut last_err: Option<String> = None;
    for _retry in 0..3 {
        let rx = std::mem::take(&mut g.reactions);
        match g.bs.poll(rx) {
            Ok(Poll::End) => {
                if target_discarded {
                    g.target_discards = g.target_discards.saturating_add(1);
                }
                capture_target_metrics(g);
                g.ended = true;
                break;
            }
            Ok(Poll::InGame) => {
                if target_discarded {
                    g.target_discards = g.target_discards.saturating_add(1);
                }
                capture_target_metrics(g);
                break;
            }
            Err(e) => {
                last_err = Some(format!("{e}"));
                for (pid, state) in g.bs.agent_context().player_states.iter().enumerate() {
                    if state.last_cans().can_discard {
                        if let Some(tile) = state.last_self_tsumo() {
                            g.reactions[pid] = EventExt::no_meta(Event::Dahai {
                                actor: pid as u8,
                                pai: tile,
                                tsumogiri: true,
                            });
                        }
                    }
                }
            }
        }
    }
    if !g.ended {
        if let Some(err) = last_err {
            eprintln!("[CustomKyokuRunner] Game {gi} failed after 3 retries: {err}");
            g.ended = true;
            g.error_msg = Some(err);
        }
    }
}

fn capture_target_metrics(g: &mut GameState) {
    if g.first_tenpai_turn.is_some() {
        return;
    }
    let target_state = &g.bs.agent_context().player_states[g.oya as usize];
    if target_state.shanten() == 0 {
        g.first_tenpai_turn = Some(g.target_discards);
    }
}

fn score_deltas(final_scores: [i32; 4], initial_scores: [i32; 4]) -> [i32; 4] {
    array::from_fn(|index| final_scores[index] - initial_scores[index])
}

fn round_balances_from_events(events: &[EventExt]) -> [i32; 4] {
    let mut balances = [0; 4];
    for event in events {
        let deltas = match &event.event {
            Event::Hora {
                deltas: Some(deltas),
                ..
            }
            | Event::Ryukyoku {
                deltas: Some(deltas),
            } => Some(deltas),
            _ => None,
        };
        if let Some(deltas) = deltas {
            vec_add_assign(&mut balances, deltas);
        }
    }
    balances
}

fn build_game(
    hand: &[Tile],
    dora_tile: Tile,
    discard_tile: Tile,
    first_tsumo_tile: Option<Tile>,
    kyoku: u8,
    honba: u8,
    kyotaku: u8,
    _bakaze: &str,
    oya: u8,
    scores: [i32; 4],
    seed: (u64, u64),
    enable_agari_guard: bool,
    first_riichi: bool,
) -> PyResult<GameState> {
    let k0 = kyoku.wrapping_sub(1);
    let mut wall: Vec<Tile> = UNSHUFFLED.to_vec();

    // Remove main hand tiles
    for &t in hand {
        let i = wall.iter().position(|&x| x == t).unwrap();
        wall.remove(i);
    }
    // Remove dora marker
    {
        let i = wall.iter().position(|&x| x == dora_tile).unwrap();
        wall.remove(i);
    }
    // Remove first_tsumo tile if specified
    if let Some(ft) = first_tsumo_tile {
        let i = wall.iter().position(|&x| x == ft).unwrap();
        wall.remove(i);
    }

    // Shuffle
    let sb: [u8; 32] = Sha3_256::new()
        .chain_update(seed.0.to_le_bytes())
        .chain_update(seed.1.to_le_bytes())
        .chain_update([k0, honba])
        .finalize()
        .into();
    let mut rng = ChaCha12Rng::from_seed(sb);
    wall.shuffle(&mut rng);

    let n_wall = wall.len(); // 121
    let oh: [Tile; 39] = wall[0..39].try_into().unwrap();
    let mut di: Vec<Tile> = wall[39..43].to_vec();
    di.push(dora_tile);
    let mut yama: Vec<Tile> = wall[43..47].to_vec(); // temporarily use for other tiles
    yama.clear();
    yama.extend_from_slice(&wall[52..n_wall]); // 69 tiles (121-52)
    // Push first_tsumo as the last yama tile (popped first by haipai())
    if let Some(ft) = first_tsumo_tile {
        yama.push(ft); // now yama has 70 tiles
    }

    // Place main hand at the oya seat; distribute other hands to remaining seats.
    // This ensures the dealer (oya) always gets the fixed hand, first tsumo,
    // and first discard — matching the "自亲第一打模拟器" semantics.
    let haipai: [[Tile; 13]; 4] = array::from_fn(|i| {
        if i == oya as usize {
            hand.try_into().unwrap()
        } else {
            let non_oya_before = (0..i).filter(|&j| j as u8 != oya).count();
            let start = non_oya_before * 13;
            oh[start..start + 13].try_into().unwrap()
        }
    });

    let bs = Board {
        kyoku: k0,
        honba,
        kyotaku,
        scores,
        haipai,
        yama,
        rinshan: wall[43..47].to_vec(),
        dora_indicators: di,
        ura_indicators: wall[47..52].to_vec(),
    }
    .into_state_with_oya(oya);

    Ok(GameState {
        bs,
        reactions: Default::default(),
        is_first: true,
        first_riichi,
        pending_first_riichi_discard: false,
        oya,
        discard_tile,
        ended: false,
        collected: false,
        scores,
        kyotaku_start: kyotaku,
        enable_agari_guard,
        error_msg: None,
        seed,
        target_discards: 0,
        first_tenpai_turn: None,
        target_agari_metrics: None,
    })
}

#[cfg(test)]
mod tests {
    use super::{
        Event, EventExt, ForcedFirstAction, RoundOutcome, classify_round_outcome,
        forced_first_action, round_balances_from_events, score_deltas, select_stable_action,
    };

    #[test]
    fn stable_selector_is_legal_deterministic_and_tie_stable() {
        let mut scores = [-10.0; 46];
        let mut legal = [false; 46];
        legal[3] = true;
        legal[9] = true;
        scores[3] = 7.5;
        scores[9] = 7.5;
        assert_eq!(select_stable_action(&scores, &legal, None), Ok(3));

        scores[9] = 8.0;
        assert_eq!(select_stable_action(&scores, &legal, None), Ok(9));
        assert_eq!(select_stable_action(&scores, &legal, Some(9)), Ok(3));
    }

    #[test]
    fn stable_selector_rejects_nan_and_empty_masks() {
        let mut scores = [-1.0; 46];
        let mut legal = [false; 46];
        legal[4] = true;
        scores[4] = f32::NAN;
        assert_eq!(
            select_stable_action(&scores, &legal, None),
            Err("stable selector rejected a NaN policy score")
        );
        assert_eq!(
            select_stable_action(&[0.0; 46], &[false; 46], None),
            Err("stable selector found no legal action")
        );
    }

    #[test]
    fn first_riichi_is_an_explicit_reach_then_forced_discard_sequence() {
        assert_eq!(
            forced_first_action(true, false, true, true),
            Some(ForcedFirstAction::Riichi)
        );
        assert_eq!(
            forced_first_action(false, true, true, true),
            Some(ForcedFirstAction::Discard)
        );
        assert_eq!(
            forced_first_action(true, false, true, false),
            Some(ForcedFirstAction::InvalidRiichi)
        );
        assert_eq!(forced_first_action(false, false, true, true), None);
    }

    #[test]
    fn outcome_partition_uses_target_player_perspective() {
        assert_eq!(
            classify_round_outcome(0, &[], false),
            (RoundOutcome::Draw, None)
        );
        assert_eq!(
            classify_round_outcome(0, &[(0, 1)], false),
            (RoundOutcome::SelfWin, Some("ron"))
        );
        assert_eq!(
            classify_round_outcome(0, &[(0, 0)], false),
            (RoundOutcome::SelfWin, Some("tsumo"))
        );
        assert_eq!(
            classify_round_outcome(0, &[(2, 0)], false),
            (RoundOutcome::SelfDealIn, None)
        );
        assert_eq!(
            classify_round_outcome(0, &[(2, 1)], false),
            (RoundOutcome::Sideways, None)
        );
        assert_eq!(
            classify_round_outcome(0, &[(2, 2)], false),
            (RoundOutcome::OtherTsumo, None)
        );
    }

    #[test]
    fn multi_ron_precedence_is_target_aware() {
        assert_eq!(
            classify_round_outcome(0, &[(1, 3), (0, 3)], false),
            (RoundOutcome::SelfWin, Some("ron"))
        );
        assert_eq!(
            classify_round_outcome(0, &[(1, 0), (2, 0)], false),
            (RoundOutcome::SelfDealIn, None)
        );
        assert_eq!(
            classify_round_outcome(0, &[(1, 2), (3, 2)], false),
            (RoundOutcome::Sideways, None)
        );
        assert_eq!(
            classify_round_outcome(0, &[(0, 1)], true),
            (RoundOutcome::Error, None)
        );
    }

    #[test]
    fn score_deltas_are_exact_end_minus_start_and_track_kyotaku() {
        let initial = [24_000, 25_000, 25_000, 25_000];
        let final_scores = [36_000, 22_000, 22_000, 20_000];
        let deltas = score_deltas(final_scores, initial);
        assert_eq!(deltas, [12_000, -3_000, -3_000, -5_000]);
        // A 1,000-point pre-existing kyotaku was claimed during the round.
        assert_eq!(deltas.iter().sum::<i32>(), 1_000 * (1 - 0));
    }

    #[test]
    fn round_balance_uses_terminal_settlement_and_excludes_riichi_payment() {
        let events = vec![
            EventExt::no_meta(Event::ReachAccepted { actor: 0 }),
            EventExt::no_meta(Event::Hora {
                actor: 0,
                target: 1,
                deltas: Some([8_700, -7_700, 0, 0]),
                ura_markers: Some(vec![]),
            }),
        ];
        assert_eq!(round_balances_from_events(&events), [8_700, -7_700, 0, 0]);
    }
}
