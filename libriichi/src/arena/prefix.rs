#![allow(dead_code)]
/// Forward Native Rollout and scripted prefix game construction for
/// "Ko's x-th Discard" conditional simulation.
///
/// Forward Native Rollout Scheme:
///  - Deduct target 14, dora indicator, and all river discards from the 136-tile pool.
///  - Opponent initial haipai: k tedashi discards from their river + (13 - k) uniform draws from pool.
///  - Timeline: tsumogiri discards are placed at their draw slots; tedashi draws are natural draws from pool.
///  - Replay in prefix executes strictly forward in O(1) without rejection or artificial priors.

use super::board::{Board, UNSHUFFLED};
use crate::tile::Tile;
use crate::tu8;
use anyhow::{Context, Result, anyhow, ensure};
use rand::prelude::*;
use rand_chacha::ChaCha12Rng;
use sha3::{Digest, Sha3_256};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DiscardSpec {
    pub tile: Tile,
    pub tsumogiri: bool,
    pub is_riichi: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PrefixStep {
    pub actor: u8,
    pub tile: Tile,
    pub tsumogiri: bool,
    pub is_riichi: bool,
    pub accumulate_likelihood: bool,
}

/// A player's initial 13-tile deal for the prefix game.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HandAssignment {
    pub initial_13: [Tile; 13],
}

#[derive(Debug, Clone)]
pub struct PrefixGameSpec {
    pub board: Board,
    pub oya: u8,
    pub forced_steps: Vec<PrefixStep>,
    pub target_seat: u8,
    /// Per-seat hand assignments (opponents + target). Indexed by absolute seat.
    pub hands: [HandAssignment; 4],
}

/// Tile-count buckets: [0..34) normal tiles (deaka), 34/35/36 = aka 5m/5p/5s.
pub const TILE_BUCKETS: usize = 37;

pub fn tile_bucket(tile: Tile) -> usize {
    match tile.as_u8() {
        tu8!(5mr) => 34,
        tu8!(5pr) => 35,
        tu8!(5sr) => 36,
        _ => tile.deaka().as_usize(),
    }
}

/// Bucket limits: normal tiles have 4 copies, aka tiles have 1 copy.
pub fn bucket_limit(bucket: usize) -> u8 {
    match bucket {
        4 | 13 | 22 => 3, // normal 5m, 5p, 5s (3 copies each in 136-tile set)
        34 | 35 | 36 => 1, // aka 5mr, 5pr, 5sr (1 copy each)
        _ => 4, // all other tiles (4 copies each)
    }
}

/// Expected number of discards in the prefix for player p before target's
/// turn-x decision point (seat-order asymmetric).
pub fn expected_discards(p: u8, target_seat: u8, oya: u8, x: u8) -> usize {
    assert!(x >= 1 && x <= 18);
    let pos_p = (p as i32 + 4 - oya as i32) % 4;
    let pos_target = (target_seat as i32 + 4 - oya as i32) % 4;
    if pos_p < pos_target {
        x as usize
    } else {
        (x - 1) as usize
    }
}

fn remove_tile(pool: &mut Vec<Tile>, tile: Tile) -> Result<()> {
    if let Some(pos) = pool.iter().position(|&t| t == tile) {
        pool.swap_remove(pos);
        Ok(())
    } else {
        Err(anyhow!("tile {:?} not found in available pool", tile))
    }
}

/// Fixed (non-sampled) tile counts: target 14 + dora indicator + all rivers.
pub fn fixed_tile_counts(
    target_14: &[Tile; 14],
    target_past: &[DiscardSpec],
    opponent_rivers: &[Vec<DiscardSpec>; 4],
    dora_marker: Tile,
) -> [u8; TILE_BUCKETS] {
    let mut counts = [0u8; TILE_BUCKETS];
    let mut add = |tile: Tile| {
        let b = tile_bucket(tile);
        counts[b] += 1;
    };
    for &t in target_14 {
        add(t);
    }
    add(dora_marker);
    for d in target_past {
        add(d.tile);
    }
    // opponent_rivers[target_seat] must be empty (caller contract).
    for river in opponent_rivers {
        for d in river {
            add(d.tile);
        }
    }
    counts
}

/// Add counts of a slice of tiles; returns false if any bucket exceeds its limit.
pub fn add_tiles_count(counts: &mut [u8; TILE_BUCKETS], tiles: &[Tile]) -> bool {
    for &t in tiles {
        let b = tile_bucket(t);
        counts[b] += 1;
    }
    for b in 0..TILE_BUCKETS {
        if counts[b] > bucket_limit(b) {
            return false;
        }
    }
    true
}

/// Increment counts with a 13-tile hand; returns false if any bucket exceeds
/// its physical limit.
pub fn add_hand_counts(counts: &mut [u8; TILE_BUCKETS], hand: &[Tile; 13]) -> bool {
    add_tiles_count(counts, hand)
}

pub fn hand_counts(hand: &[Tile; 13]) -> [u8; TILE_BUCKETS] {
    let mut counts = [0u8; TILE_BUCKETS];
    add_hand_counts(&mut counts, hand);
    counts
}

/// Validates river lengths and global fixed tile counts.
pub fn validate_inputs(
    target_seat: u8,
    oya: u8,
    x: u8,
    target_14: &[Tile; 14],
    target_past: &[DiscardSpec],
    opponent_rivers: &[Vec<DiscardSpec>; 4],
    dora_marker: Tile,
) -> Result<()> {
    ensure!(target_seat < 4, "target_seat must be 0..3");
    ensure!(oya < 4, "oya must be 0..3");
    ensure!(x >= 1 && x <= 18, "x must be in 1..=18");
    let tp_len = target_past.len();
    ensure!(
        tp_len == (x - 1) as usize || tp_len == x as usize,
        "target_past length ({}) must be x - 1 ({}) or x ({})",
        tp_len,
        x - 1,
        x
    );
    for p in 0..4u8 {
        if p != target_seat {
            let r_len = opponent_rivers[p as usize].len();
            ensure!(
                r_len >= ((x - 1) as usize).saturating_sub(1) && r_len <= (x + 1) as usize,
                "opponent {} river length ({}) out of valid range for turn {}",
                p,
                r_len,
                x
            );
        }
    }
    let counts = fixed_tile_counts(target_14, target_past, opponent_rivers, dora_marker);
    for b in 0..TILE_BUCKETS {
        ensure!(
            counts[b] <= bucket_limit(b),
            "fixed tiles exceed physical limit for bucket {} ({})",
            b,
            counts[b]
        );
    }
    Ok(())
}

fn seed_from_tuple(k0: u8, k1: u8, a: u8, b: u8, c: u64, d: u64) -> [u8; 32] {
    Sha3_256::new()
        .chain_update(k0.to_le_bytes())
        .chain_update(k1.to_le_bytes())
        .chain_update([a, b])
        .chain_update(c.to_le_bytes())
        .chain_update(d.to_le_bytes())
        .finalize()
        .into()
}

/// Forward Native Rollout: Sample initial haipai and construct the prefix game
/// directly in O(1) without rejection sampling or synthetic shanten priors.
pub fn sample_prefix_game(
    target_seat: u8,
    oya: u8,
    x: u8,
    target_14: &[Tile; 14],
    target_past: &[DiscardSpec],
    opponent_rivers: &[Vec<DiscardSpec>; 4],
    dora_marker: Tile,
    kyoku: u8,
    honba: u8,
    kyotaku: u8,
    scores: [i32; 4],
    seed: (u64, u64),
) -> Result<PrefixGameSpec> {
    validate_inputs(target_seat, oya, x, target_14, target_past, opponent_rivers, dora_marker)?;

    // 1. Available Pool = 136 - target_14 - dora - all rivers.
    let mut pool: Vec<Tile> = UNSHUFFLED.to_vec();
    for &t in target_14 {
        remove_tile(&mut pool, t)?;
    }
    remove_tile(&mut pool, dora_marker)?;
    for d in target_past {
        remove_tile(&mut pool, d.tile)?;
    }
    for p in 0..4usize {
        if p as u8 != target_seat {
            for d in &opponent_rivers[p] {
                remove_tile(&mut pool, d.tile)?;
            }
        }
    }
    ensure!(pool.len() >= 39, "insufficient tiles in pool to deal opponents");

    let sb: [u8; 32] = seed_from_tuple(kyoku, honba, target_seat, x, seed.0, seed.1);
    let mut rng = ChaCha12Rng::from_seed(sb);
    pool.shuffle(&mut rng);

    // 2. Build initial 13 haipai for all 4 players (Forward Haipai)
    let mut hands: [HandAssignment; 4] = [
        HandAssignment { initial_13: [Tile::new_unchecked(0); 13] },
        HandAssignment { initial_13: [Tile::new_unchecked(0); 13] },
        HandAssignment { initial_13: [Tile::new_unchecked(0); 13] },
        HandAssignment { initial_13: [Tile::new_unchecked(0); 13] },
    ];

    // Target player: k_target tedashi discards + (13 - k_target) tiles from target_14[..13]
    let target_tedashis: Vec<Tile> = target_past
        .iter()
        .filter(|d| !d.tsumogiri)
        .map(|d| d.tile)
        .collect();
    let k_target = target_tedashis.len();
    ensure!(k_target <= 13, "target tedashis ({}) exceed 13", k_target);

    let mut target_initial_vec = target_tedashis;
    target_initial_vec.extend_from_slice(&target_14[..13 - k_target]);
    let target_initial: [Tile; 13] = target_initial_vec.try_into().unwrap();
    hands[target_seat as usize] = HandAssignment { initial_13: target_initial };

    // Opponents: k tedashi discards + (13 - k) uniform random draws from pool
    for p in 0..4u8 {
        if p == target_seat {
            continue;
        }
        let river = &opponent_rivers[p as usize];
        let tedashis: Vec<Tile> = river
            .iter()
            .filter(|d| !d.tsumogiri)
            .map(|d| d.tile)
            .collect();
        let k = tedashis.len();
        ensure!(k <= 13, "opponent {} tedashis ({}) exceed 13", p, k);
        let needed = 13 - k;
        ensure!(pool.len() >= needed, "insufficient pool for opponent {}", p);

        let mut opp_initial = tedashis;
        for _ in 0..needed {
            opp_initial.push(pool.pop().unwrap());
        }
        let initial_13: [Tile; 13] = opp_initial.try_into().unwrap();
        hands[p as usize] = HandAssignment { initial_13 };
    }

    build_prefix_game_from_hands(
        target_seat,
        oya,
        x,
        target_14,
        target_past,
        opponent_rivers,
        dora_marker,
        kyoku,
        honba,
        kyotaku,
        scores,
        &hands,
        seed,
    )
}

/// Rebuild the prefix game from explicit per-seat initial hand assignments.
pub fn build_prefix_game_from_hands(
    target_seat: u8,
    oya: u8,
    x: u8,
    target_14: &[Tile; 14],
    target_past: &[DiscardSpec],
    opponent_rivers: &[Vec<DiscardSpec>; 4],
    dora_marker: Tile,
    kyoku: u8,
    honba: u8,
    kyotaku: u8,
    scores: [i32; 4],
    hands: &[HandAssignment; 4],
    seed: (u64, u64),
) -> Result<PrefixGameSpec> {
    validate_inputs(target_seat, oya, x, target_14, target_past, opponent_rivers, dora_marker)?;

    let haipai: [[Tile; 13]; 4] = [
        hands[0].initial_13,
        hands[1].initial_13,
        hands[2].initial_13,
        hands[3].initial_13,
    ];

    let target_tedashis: Vec<Tile> = target_past
        .iter()
        .filter(|d| !d.tsumogiri)
        .map(|d| d.tile)
        .collect();
    let k_target = target_tedashis.len();

    // Reconstruct available pool from 136
    let mut pool: Vec<Tile> = UNSHUFFLED.to_vec();
    for p in 0..4usize {
        for &t in &haipai[p] {
            remove_tile(&mut pool, t)?;
        }
    }
    remove_tile(&mut pool, dora_marker)?;

    // Remove target's kept draw tiles (which enter hand during prefix) and target 14th tile
    for &t in &target_14[13 - k_target..14] {
        remove_tile(&mut pool, t)?;
    }

    // Remove all tsumogiri discards in all rivers
    for d in target_past {
        if d.tsumogiri {
            remove_tile(&mut pool, d.tile)?;
        }
    }
    for p in 0..4usize {
        if p as u8 != target_seat {
            for d in &opponent_rivers[p] {
                if d.tsumogiri {
                    remove_tile(&mut pool, d.tile)?;
                }
            }
        }
    }

    let sb: [u8; 32] = seed_from_tuple(kyoku, honba, target_seat, x, seed.0 ^ 0x9e3779b97f4a7c15, seed.1 ^ 0xbf58476d1ce4e5b9);
    let mut rng = ChaCha12Rng::from_seed(sb);
    pool.shuffle(&mut rng);

    // Build timeline draws
    let mut timeline_draws: Vec<Tile> = Vec::new();
    let mut forced_steps: Vec<PrefixStep> = Vec::new();
    let mut target_tedashi_draw_idx = 0usize;

    if oya == target_seat {
        if x == 1 && target_past.is_empty() {
            timeline_draws.push(target_14[13]);
        } else {
            let d0 = target_past[0];
            if d0.tsumogiri {
                timeline_draws.push(d0.tile);
            } else {
                timeline_draws.push(target_14[13 - k_target + target_tedashi_draw_idx]);
                target_tedashi_draw_idx += 1;
            }
        }
    } else {
        if opponent_rivers[oya as usize].is_empty() {
            let t = pool.pop().context("insufficient pool for oya initial draw")?;
            timeline_draws.push(t);
        } else {
            let d0 = opponent_rivers[oya as usize][0];
            if d0.tsumogiri {
                timeline_draws.push(d0.tile);
            } else {
                let t = pool.pop().context("insufficient pool for oya initial draw")?;
                timeline_draws.push(t);
            }
        }
    }

    let is_post_discard_reaction = target_past.len() == x as usize;

    'outer: for r in 1..=(x + 1) {
        for offset in 0..4u8 {
            let p = (oya + offset) % 4;
            let river_idx = (r - 1) as usize;

            let has_discard = if p == target_seat {
                river_idx < target_past.len()
            } else {
                river_idx < opponent_rivers[p as usize].len()
            };

            if !has_discard {
                if p == target_seat && !is_post_discard_reaction && r == x {
                    timeline_draws.push(target_14[13]);
                    break 'outer;
                }
                let remaining_any = (0..4u8).any(|check_p| {
                    if check_p == target_seat {
                        river_idx < target_past.len()
                    } else {
                        river_idx < opponent_rivers[check_p as usize].len()
                    }
                });
                if !remaining_any {
                    break 'outer;
                }
                continue;
            }

            if !(r == 1 && p == oya) {
                if p == target_seat {
                    let d = target_past[river_idx];
                    if d.tsumogiri {
                        timeline_draws.push(d.tile);
                    } else {
                        timeline_draws.push(target_14[13 - k_target + target_tedashi_draw_idx]);
                        target_tedashi_draw_idx += 1;
                    }
                } else {
                    let d = opponent_rivers[p as usize][river_idx];
                    if d.tsumogiri {
                        timeline_draws.push(d.tile);
                    } else {
                        let t = pool.pop().context("insufficient pool for opponent draw")?;
                        timeline_draws.push(t);
                    }
                }
            }

            let discard_spec = if p == target_seat {
                target_past[river_idx]
            } else {
                opponent_rivers[p as usize][river_idx]
            };
            forced_steps.push(PrefixStep {
                actor: p,
                tile: discard_spec.tile,
                tsumogiri: discard_spec.tsumogiri,
                is_riichi: discard_spec.is_riichi,
                accumulate_likelihood: p != target_seat,
            });
        }
    }

    ensure!(pool.len() >= 13, "insufficient tiles for dead wall");
    let mut di: Vec<Tile> = pool.drain(pool.len() - 4..).collect();
    di.push(dora_marker);
    let rinshan: Vec<Tile> = pool.drain(pool.len() - 4..).collect();
    let ura_indicators: Vec<Tile> = pool.drain(pool.len() - 5..).collect();

    let mut yama = pool;
    for &t in timeline_draws.iter().rev() {
        yama.push(t);
    }

    let board = Board {
        kyoku: kyoku.wrapping_sub(1),
        honba,
        kyotaku,
        scores,
        haipai,
        yama,
        rinshan,
        dora_indicators: di,
        ura_indicators,
    };

    Ok(PrefixGameSpec {
        board,
        oya,
        forced_steps,
        target_seat,
        hands: hands.clone(),
    })
}

/// Assembles `n_out` full hand-assignment sets from per-player marginal subfamilies.
pub fn assemble_marginal_games(
    sub_hands: &[[HandAssignment; 4]],
    log_likelihoods: &[[f64; 4]],
    target_seat: u8,
    target_14: &[Tile; 14],
    target_past: &[DiscardSpec],
    opponent_rivers: &[Vec<DiscardSpec>; 4],
    dora_marker: Tile,
    n_out: usize,
    seed: (u64, u64),
) -> (Vec<[HandAssignment; 4]>, usize) {
    use super::weighted::resample_indices;

    let fixed = fixed_tile_counts(target_14, target_past, opponent_rivers, dora_marker);
    let opponents: Vec<u8> = (0..4u8).filter(|&p| p != target_seat).collect();
    let n_sub = sub_hands.len().max(1);
    if n_sub == 0 {
        return (Vec::new(), 0);
    }

    let mut rngs: Vec<ChaCha12Rng> = opponents
        .iter()
        .map(|&p| {
            ChaCha12Rng::from_seed(seed_from_tuple(0, 0, target_seat, p, seed.0, seed.1))
        })
        .collect();

    let mut sub_idx: Vec<Vec<usize>> = Vec::with_capacity(opponents.len());
    for (k, &p) in opponents.iter().enumerate() {
        let logw: Vec<f64> = log_likelihoods.iter().map(|ll| ll[p as usize]).collect();
        sub_idx.push(resample_indices(&logw, n_out, &mut rngs[k]));
    }

    let budget = 256usize;
    let mut out = Vec::with_capacity(n_out);
    let mut fallback = 0usize;
    let empty_hand = HandAssignment {
        initial_13: [Tile::new_unchecked(0); 13],
    };

    for i in 0..n_out {
        let mut counts = fixed;
        let mut assembled: [HandAssignment; 4] = core::array::from_fn(|_| empty_hand.clone());
        assembled[target_seat as usize] = sub_hands[i % n_sub][target_seat as usize].clone();

        let mut ok = true;
        for (k, &p) in opponents.iter().enumerate() {
            let mut chosen: Option<usize> = None;
            let k_tedashis = opponent_rivers[p as usize]
                .iter()
                .filter(|d| !d.tsumogiri)
                .count();

            for d in 0..budget {
                let idx = sub_idx[k][(i + d) % n_out];
                let hand = &sub_hands[idx][p as usize];
                let mut trial = counts;
                // Check pool tiles in opponent's initial haipai (elements after the k tedashis)
                let pool_tiles = &hand.initial_13[k_tedashis..13];
                if add_tiles_count(&mut trial, pool_tiles) {
                    chosen = Some(idx);
                    counts = trial;
                    break;
                }
            }
            match chosen {
                Some(idx) => {
                    assembled[p as usize] = sub_hands[idx][p as usize].clone();
                }
                None => {
                    ok = false;
                    break;
                }
            }
        }

        if ok {
            out.push(assembled);
        } else {
            out.push(sub_hands[i % n_sub].clone());
            fallback += 1;
        }
    }

    (out, fallback)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::arena::board::Poll;
    use crate::mjai::{Event, EventExt};
    use crate::tile::Tile;
    use std::array;
    use std::str::FromStr;

    fn parse_tile(s: &str) -> Tile {
        Tile::from_str(s).unwrap()
    }

    fn sample_spec() -> PrefixGameSpec {
        // Target = South (seat 1), x = 2, Oya = East (seat 0).
        let target_14 = [
            parse_tile("1m"), parse_tile("2m"), parse_tile("3m"),
            parse_tile("4m"), parse_tile("5m"), parse_tile("6m"),
            parse_tile("7m"), parse_tile("8m"), parse_tile("9m"),
            parse_tile("1p"), parse_tile("2p"), parse_tile("3p"),
            parse_tile("4p"), parse_tile("5p"),
        ];
        let target_past = vec![DiscardSpec { tile: parse_tile("9s"), tsumogiri: false, is_riichi: false }];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("E"), tsumogiri: false, is_riichi: false },
                DiscardSpec { tile: parse_tile("S"), tsumogiri: true, is_riichi: false },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("W"), tsumogiri: false, is_riichi: false }],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false, is_riichi: false }],
        ];
        sample_prefix_game(
            1, 0, 2, &target_14, &target_past, &opponent_rivers,
            parse_tile("8s"), 1, 0, 0, [25000; 4], (12345, 67890),
        ).unwrap()
    }

    #[test]
    fn test_sample_replay_reaches_decision_point() {
        let spec = sample_spec();
        assert_eq!(spec.forced_steps.len(), 5);

        let mut bs = spec.board.into_state_with_oya(0);
        let poll = bs.poll(Default::default()).unwrap();
        assert!(matches!(poll, Poll::InGame));

        for step in &spec.forced_steps {
            while !bs.agent_context().player_states[step.actor as usize].last_cans().can_discard {
                let p = bs.poll(Default::default()).unwrap();
                assert!(matches!(p, Poll::InGame));
            }
            assert!(bs.agent_context().player_states[step.actor as usize].last_cans().can_discard);
            let reactions = array::from_fn(|i| {
                if i as u8 == step.actor {
                    EventExt::no_meta(Event::Dahai {
                        actor: step.actor,
                        pai: step.tile,
                        tsumogiri: step.tsumogiri,
                    })
                } else {
                    EventExt::default()
                }
            });
            let p = bs.poll(reactions).unwrap();
            assert!(matches!(p, Poll::InGame));
        }
        while !bs.agent_context().player_states[1].last_cans().can_discard {
            let p = bs.poll(Default::default()).unwrap();
            assert!(matches!(p, Poll::InGame));
        }

        // Target hand must equal the given 14 tiles.
        let tehai = bs.agent_context().player_states[1].tehai();
        let mut expected = [0u8; 34];
        for &t in &[
            parse_tile("1m"), parse_tile("2m"), parse_tile("3m"),
            parse_tile("4m"), parse_tile("5m"), parse_tile("6m"),
            parse_tile("7m"), parse_tile("8m"), parse_tile("9m"),
            parse_tile("1p"), parse_tile("2p"), parse_tile("3p"),
            parse_tile("4p"), parse_tile("5p"),
        ] {
            expected[t.deaka().as_usize()] += 1;
        }
        assert_eq!(tehai, expected);
    }

    #[test]
    fn test_rebuild_from_hands_is_identical() {
        let spec1 = sample_spec();
        let target_14 = [
            parse_tile("1m"), parse_tile("2m"), parse_tile("3m"),
            parse_tile("4m"), parse_tile("5m"), parse_tile("6m"),
            parse_tile("7m"), parse_tile("8m"), parse_tile("9m"),
            parse_tile("1p"), parse_tile("2p"), parse_tile("3p"),
            parse_tile("4p"), parse_tile("5p"),
        ];
        let target_past = vec![DiscardSpec { tile: parse_tile("9s"), tsumogiri: false, is_riichi: false }];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("E"), tsumogiri: false, is_riichi: false },
                DiscardSpec { tile: parse_tile("S"), tsumogiri: true, is_riichi: false },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("W"), tsumogiri: false, is_riichi: false }],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false, is_riichi: false }],
        ];
        let spec2 = build_prefix_game_from_hands(
            1, 0, 2, &target_14, &target_past, &opponent_rivers,
            parse_tile("8s"), 1, 0, 0, [25000; 4], &spec1.hands, (12345, 67890),
        ).unwrap();

        assert_eq!(spec1.board.haipai, spec2.board.haipai);
        assert_eq!(spec1.board.yama, spec2.board.yama);
        assert_eq!(spec1.forced_steps, spec2.forced_steps);
    }

    #[test]
    fn test_sample_reproducibility() {
        let a = sample_spec();
        let b = sample_spec();
        assert_eq!(a.board.haipai, b.board.haipai);
        assert_eq!(a.board.yama, b.board.yama);
        assert_eq!(a.forced_steps, b.forced_steps);
    }

    #[test]
    fn test_assemble_marginal_games_compatible() {
        let spec = sample_spec();
        let sub_hands = vec![spec.hands.clone()];
        let log_likes = vec![[0.0f64, 0.0, 0.0, 0.0]];
        let target_14 = [
            parse_tile("1m"), parse_tile("2m"), parse_tile("3m"),
            parse_tile("4m"), parse_tile("5m"), parse_tile("6m"),
            parse_tile("7m"), parse_tile("8m"), parse_tile("9m"),
            parse_tile("1p"), parse_tile("2p"), parse_tile("3p"),
            parse_tile("4p"), parse_tile("5p"),
        ];
        let target_past = vec![DiscardSpec { tile: parse_tile("9s"), tsumogiri: false, is_riichi: false }];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("E"), tsumogiri: false, is_riichi: false },
                DiscardSpec { tile: parse_tile("S"), tsumogiri: true, is_riichi: false },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("W"), tsumogiri: false, is_riichi: false }],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false, is_riichi: false }],
        ];
        let (assembled, fallback) = assemble_marginal_games(
            &sub_hands,
            &log_likes,
            1,
            &target_14,
            &target_past,
            &opponent_rivers,
            parse_tile("8s"),
            5,
            (7, 8),
        );
        assert_eq!(assembled.len(), 5);
        assert_eq!(fallback, 0);
        let fixed = fixed_tile_counts(&target_14, &target_past, &opponent_rivers, parse_tile("8s"));
        for hands in &assembled {
            let mut counts = fixed;
            for p in 0..4u8 {
                if p == 1 {
                    continue;
                }
                let k = opponent_rivers[p as usize].iter().filter(|d| !d.tsumogiri).count();
                assert!(add_tiles_count(&mut counts, &hands[p as usize].initial_13[k..13]));
            }
        }
    }

    #[test]
    fn repro_qq_cmd() {
        let target_14: [Tile; 14] = [
            parse_tile("2m"), parse_tile("3m"), parse_tile("4m"),
            parse_tile("6m"), parse_tile("9m"), parse_tile("9m"),
            parse_tile("2s"), parse_tile("4s"), parse_tile("7s"),
            parse_tile("8s"), parse_tile("9s"), parse_tile("3p"),
            parse_tile("3p"), parse_tile("6p"),
        ];
        let target_past = vec![DiscardSpec { tile: parse_tile("S"), tsumogiri: true, is_riichi: false }];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("N"), tsumogiri: false, is_riichi: false },
                DiscardSpec { tile: parse_tile("1s"), tsumogiri: true, is_riichi: false },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false, is_riichi: false }],
            vec![DiscardSpec { tile: parse_tile("9m"), tsumogiri: false, is_riichi: false }],
        ];
        for i in 0..5000u64 {
            let res = sample_prefix_game(
                1, 0, 2, &target_14, &target_past, &opponent_rivers,
                parse_tile("N"), 1, 0, 0, [25000; 4], (2026u64.wrapping_add(i), 57005),
            );
            match res {
                Ok(_) => {}
                Err(e) => {
                    eprintln!("FAILED at i={}: {:?}", i, e);
                    panic!("found failing seed");
                }
            }
        }
        eprintln!("repro OK: all 5000 seeds passed");
    }
}
