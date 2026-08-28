#![allow(dead_code)]
/// Proposal sampler and scripted prefix game construction for
/// "Ko's x-th Discard" conditional simulation.
///
/// v0.2 (marginal/mean-field scheme):
///  - `sample_prefix_game` draws joint deals from the shared pool (uniform proposal).
///  - Per-player marginal likelihoods are computed by the runner (softmax Q/tau).
///  - `build_prefix_game_from_hands` rebuilds a game from an assembled
///    (possibly cross-deal) triple of hands + kept-draw assignments.

use super::board::{Board, UNSHUFFLED};
use crate::tile::Tile;
use crate::tu8;
use anyhow::{Context, Result, anyhow, ensure};
use rand::prelude::*;
use rand_chacha::ChaCha12Rng;
use sha3::{Digest, Sha3_256};
use std::collections::HashMap;

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

/// A player's decision-point hand together with which of its tiles were
/// drawn-and-kept (in chronological order). This is the minimal state needed
/// to reconstruct a legal trajectory consistent with the player's river.
#[derive(Debug, Clone)]
pub struct HandAssignment {
    pub current_13: [Tile; 13],
    pub kept_draws: Vec<Tile>,
}

#[derive(Debug)]
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

/// Increment counts with a 13-tile hand; returns false if any bucket exceeds
/// its physical limit.
pub fn add_hand_counts(counts: &mut [u8; TILE_BUCKETS], hand: &[Tile; 13]) -> bool {
    for &t in hand {
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

/// Build the full prefix game (Board + forced steps) from explicit per-seat
/// hand assignments. The hands must be physically compatible with the fixed
/// tiles (caller responsibility; `add_hand_counts` can verify incrementally).
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

    // Reconstruct each player's initial 13-tile hand from
    // current_13 - kept_draws + tedashi discards.
    let mut haipai: [[Tile; 13]; 4] = [[Tile::new_unchecked(0); 13]; 4];
    let mut player_draws: HashMap<(u8, usize), Tile> = HashMap::new();

    for p in 0..4u8 {
        let river: &[DiscardSpec] = if p == target_seat {
            target_past
        } else {
            &opponent_rivers[p as usize]
        };
        let mut tedashis = Vec::new();
        let mut tsumogiris = Vec::new();
        for (i, d) in river.iter().enumerate() {
            if d.tsumogiri {
                tsumogiris.push((i, d.tile));
            } else {
                tedashis.push(d.tile);
            }
        }

        let assignment = &hands[p as usize];
        let mut initial_13 = assignment.current_13.to_vec();
        // Remove kept draws (they were drawn later, not in the initial hand).
        for tile in &assignment.kept_draws {
            let idx = initial_13.iter().position(|&t| t == *tile).ok_or_else(|| {
                anyhow!("kept draw {:?} not found in current hand of player {}", tile, p)
            })?;
            initial_13.swap_remove(idx);
        }
        // Tedashi discards were in the initial hand.
        for t in tedashis {
            initial_13.push(t);
        }
        ensure!(
            initial_13.len() == 13,
            "initial hand length for player {} is {}, expected 13",
            p,
            initial_13.len()
        );
        haipai[p as usize] = initial_13.try_into().unwrap();

        // Assign draw tiles: tsumogiri from the river, tedashi draws = kept tiles.
        let mut kept_iter = assignment.kept_draws.iter();
        for (turn_idx, d) in river.iter().enumerate() {
            if d.tsumogiri {
                player_draws.insert((p, turn_idx), d.tile);
            } else {
                let tile = *kept_iter.next().context("kept draws exhausted")?;
                player_draws.insert((p, turn_idx), tile);
            }
        }
        if p == target_seat && target_past.len() < x as usize {
            // The target's decision-point draw (14th tile) in discard timing.
            player_draws.insert((target_seat, (x - 1) as usize), target_14[13]);
        }
    }

    // Build the chronological timeline (draws + forced discards).
    // Build the chronological timeline (draws + forced discards).
    let mut scripted_draws: Vec<Tile> = Vec::new();
    let mut forced_steps: Vec<PrefixStep> = Vec::new();
    let mut player_draw_counters = [0usize; 4];

    let oya_draw_0 = *player_draws
        .get(&(oya, 0))
        .context("oya initial 14th draw missing")?;
    scripted_draws.push(oya_draw_0);
    player_draw_counters[oya as usize] += 1;

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
                    // Standard turn x discard decision point reached!
                    let draw_tile = *player_draws
                        .get(&(p, (x - 1) as usize))
                        .context("target turn x draw missing")?;
                    scripted_draws.push(draw_tile);
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
                let d_idx = player_draw_counters[p as usize];
                if let Some(&draw_tile) = player_draws.get(&(p, d_idx)) {
                    scripted_draws.push(draw_tile);
                    player_draw_counters[p as usize] += 1;
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

    // Assemble Board.
    // Wall at deal = 136 - initial haipai (52) - dead wall (14, incl. dora marker).
    // The river tiles / kept draws / target 14th are all drawn DURING the
    // prefix, so they must still be in the live wall at deal. scripted_draws
    // are therefore removed from the shuffled remainder and re-inserted at the
    // draw positions (end of yama, popped first).
    let mut pool: Vec<Tile> = UNSHUFFLED.to_vec();
    for p in 0..4usize {
        for &t in &haipai[p] {
            remove_tile(&mut pool, t)?;
        }
    }
    remove_tile(&mut pool, dora_marker)?;

    // Prefix draws must strictly come from the live wall, not the dead wall.
    // Remove scripted_draws first before drawing the dead wall from the pool.
    for &t in &scripted_draws {
        remove_tile(&mut pool, t)?;
    }
    ensure!(pool.len() >= 13, "insufficient tiles for dead wall");

    let sb: [u8; 32] = seed_from_tuple(kyoku, honba, target_seat, x, seed.0, seed.1);
    let mut rng = ChaCha12Rng::from_seed(sb);
    pool.shuffle(&mut rng);

    let mut di: Vec<Tile> = pool.drain(pool.len() - 4..).collect();
    di.push(dora_marker);
    let rinshan: Vec<Tile> = pool.drain(pool.len() - 4..).collect();
    let ura_indicators: Vec<Tile> = pool.drain(pool.len() - 5..).collect();

    let mut yama = pool;
    for &t in scripted_draws.iter().rev() {
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


/// Helper to convert a 13-tile array to counts for shanten calculator
fn hand_to_counts_34(tiles: &[Tile; 13]) -> [u8; 34] {
    let mut c = [0u8; 34];
    for &t in tiles {
        c[t.deaka().as_usize()] += 1;
    }
    c
}

/// Sample 13 tiles from `pool` for player `p`, prioritizing 0-shanten if Riichi
/// or 0..=2 shanten if late turns (x >= 6).
fn sample_structured_hand_for_opponent(
    pool: &mut Vec<Tile>,
    is_riichi: bool,
    turn: u8,
    rng: &mut ChaCha12Rng,
) -> Result<[Tile; 13]> {
    ensure!(pool.len() >= 13, "insufficient tiles in pool");
    let max_shanten_target = if is_riichi {
        0i8 // Riichi player MUST be in tenpai (0-shanten)
    } else if turn >= 10 {
        2i8 // Late turn non-riichi: average 1..2 shanten
    } else if turn >= 6 {
        3i8
    } else {
        6i8 // Early turn: no restriction
    };

    let mut best_hand: Option<([Tile; 13], i8)> = None;
    // Attempt up to 80 candidate combinations from pool
    for _ in 0..80 {
        pool.shuffle(rng);
        let candidate: [Tile; 13] = pool[pool.len() - 13..].try_into().unwrap();
        let counts = hand_to_counts_34(&candidate);
        let sh = crate::algo::shanten::calc_all(&counts, 4);
        if sh <= max_shanten_target {
            // Found a qualified structured hand!
            let current_13: [Tile; 13] = pool.drain(pool.len() - 13..).collect::<Vec<_>>().try_into().unwrap();
            return Ok(current_13);
        }
        match best_hand {
            None => best_hand = Some((candidate, sh)),
            Some((_, best_sh)) if sh < best_sh => best_hand = Some((candidate, sh)),
            _ => {}
        }
    }

    // If exact target not met after 80 tries, take the lowest shanten hand found
    pool.shuffle(rng);
    let current_13: [Tile; 13] = pool.drain(pool.len() - 13..).collect::<Vec<_>>().try_into().unwrap();
    Ok(current_13)
}


/// Synthetic Tenpai/Shanten Builder: Constructs a realistic 13-tile mahjong hand from available pool.
/// Supports all 3 fundamental Japanese Mahjong forms (Tenhou Rules):
/// 1. Standard Normal Form (4面子1雀头: 3 complete melds + 1 pair + 1 taatsu/shanpon wait)
/// 2. Chiitoitsu Form (七对子: 6 distinct pairs + 1 single wait tile)
/// 3. Kokushi Musou Form (国士无双: 12 yaojiu + 1 pair, or 13 distinct yaojiu)
fn synthesize_shanten_hand(
    pool: &mut Vec<Tile>,
    is_riichi: bool,
    turn: u8,
    rng: &mut ChaCha12Rng,
) -> Result<[Tile; 13]> {
    ensure!(pool.len() >= 13, "pool underflow");
    if turn < 4 && !is_riichi {
        // Early turns: uniform sample
        let mut h: [Tile; 13] = pool[pool.len() - 13..].try_into().unwrap();
        pool.truncate(pool.len() - 13);
        return Ok(h);
    }

    let mut pool_counts = [0u8; 34];
    for &t in pool.iter() {
        pool_counts[t.deaka().as_usize()] += 1;
    }

    // Pattern 2 Check: Chiitoitsu (七对子 6 pairs + 1 wait)
    let available_pairs: Vec<usize> = (0..34).filter(|&k| pool_counts[k] >= 2).collect();
    if available_pairs.len() >= 6 {
        // 15% probability if >= 6 pairs available, or 50% if >= 7 pairs available
        let p_roll = rng.gen_range(0..100);
        if (available_pairs.len() >= 7 && p_roll < 40) || (available_pairs.len() == 6 && p_roll < 20) {
            let mut chitoi_pairs = available_pairs.clone();
            chitoi_pairs.shuffle(rng);
            let mut extracted: Vec<Tile> = Vec::with_capacity(13);
            let mut used_counts = [0u8; 34];
            for &p_tile in &chitoi_pairs[..6] {
                used_counts[p_tile] += 2;
            }
            // Add 1 single tile (wait)
            for i in 0..34 {
                if used_counts[i] == 0 && pool_counts[i] >= 1 {
                    used_counts[i] += 1;
                    break;
                }
            }
            // Extract from pool
            for i in 0..34 {
                let needed = used_counts[i];
                let mut got = 0;
                let mut p_idx = 0;
                while p_idx < pool.len() && got < needed {
                    if pool[p_idx].deaka().as_usize() == i {
                        extracted.push(pool.swap_remove(p_idx));
                        got += 1;
                    } else {
                        p_idx += 1;
                    }
                }
            }
            if extracted.len() == 13 {
                let h: [Tile; 13] = extracted.try_into().unwrap();
                let counts = hand_to_counts_34(&h);
                let sh = crate::algo::shanten::calc_all(&counts, 4);
                if is_riichi && sh == 0 {
                    return Ok(h);
                } else if !is_riichi && sh <= 2 {
                    return Ok(h);
                }
                for t in h { pool.push(t); }
            }
        }
    }

    // Pattern 1: Standard 4面子1雀头 Form (3 Melds + 1 Pair + 1 Wait)
    for _ in 0..300 {
        let mut trial_counts = pool_counts;

        // 1. Pick a Pair (雀头)
        let mut possible_pairs: Vec<usize> = (0..34).filter(|&k| trial_counts[k] >= 2).collect();
        if possible_pairs.is_empty() {
            break;
        }
        possible_pairs.shuffle(rng);
        let pair_t = possible_pairs[0];
        trial_counts[pair_t] -= 2;

        // 2. Try picking 3 complete Melds (顺子 or 刻子, including Honors)
        let mut melds_found = 0;
        let mut all_indices: Vec<usize> = (0..34).collect();
        all_indices.shuffle(rng);

        for &base in &all_indices {
            if melds_found >= 3 {
                break;
            }
            if base < 27 {
                let num = base % 9;
                // Shuntsu (顺子)
                if num <= 6 && trial_counts[base] >= 1 && trial_counts[base + 1] >= 1 && trial_counts[base + 2] >= 1 {
                    trial_counts[base] -= 1;
                    trial_counts[base + 1] -= 1;
                    trial_counts[base + 2] -= 1;
                    melds_found += 1;
                    continue;
                }
            }
            // Koutsu (刻子, suits + honors)
            if trial_counts[base] >= 3 {
                trial_counts[base] -= 3;
                melds_found += 1;
            }
        }

        // 3. Try picking 1 Wait / Taatsu (搭子: 2 tiles or 2nd pair for shanpon)
        for &base in &all_indices {
            if base < 27 {
                let num = base % 9;
                if num <= 7 && trial_counts[base] >= 1 && trial_counts[base + 1] >= 1 {
                    trial_counts[base] -= 1;
                    trial_counts[base + 1] -= 1;
                    break;
                }
            }
            if trial_counts[base] >= 2 {
                trial_counts[base] -= 2;
                break;
            }
        }

        // If we constructed at least 2 melds + pair (<= 1-shanten)
        if melds_found >= 2 {
            let mut assembled_indices = [0u8; 34];
            for i in 0..34 {
                assembled_indices[i] = pool_counts[i] - trial_counts[i];
            }
            // Extract exact tiles from pool
            let mut extracted: Vec<Tile> = Vec::with_capacity(13);
            for i in 0..34 {
                let needed = assembled_indices[i];
                let mut got = 0;
                let mut p_idx = 0;
                while p_idx < pool.len() && got < needed {
                    if pool[p_idx].deaka().as_usize() == i {
                        extracted.push(pool.swap_remove(p_idx));
                        got += 1;
                    } else {
                        p_idx += 1;
                    }
                }
            }
            // Fill remaining up to 13 from pool if needed
            while extracted.len() < 13 && !pool.is_empty() {
                extracted.push(pool.pop().unwrap());
            }
            if extracted.len() == 13 {
                let h: [Tile; 13] = extracted.try_into().unwrap();
                let counts = hand_to_counts_34(&h);
                let sh = crate::algo::shanten::calc_all(&counts, 4);
                if is_riichi && sh == 0 {
                    return Ok(h);
                } else if !is_riichi && sh <= 2 {
                    return Ok(h);
                }
                // Put back to pool and continue search
                for t in h {
                    pool.push(t);
                }
            }
        }
    }

    // Fallback to highest quality shanten hand
    sample_structured_hand_for_opponent(pool, is_riichi, turn, rng)
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

/// Uniform joint proposal: sample current hands + kept-draw assignments for all
/// four players from the shared pool, then build the full prefix game.
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

    // Pool = 136 - target14 - dora - all rivers.
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

    let mut hands: [HandAssignment; 4] = [
        HandAssignment { current_13: [Tile::new_unchecked(0); 13], kept_draws: vec![] },
        HandAssignment { current_13: [Tile::new_unchecked(0); 13], kept_draws: vec![] },
        HandAssignment { current_13: [Tile::new_unchecked(0); 13], kept_draws: vec![] },
        HandAssignment { current_13: [Tile::new_unchecked(0); 13], kept_draws: vec![] },
    ];

    // Opponents: draw current 13 from pool with shanten/meld bias; pick kept subset.
    for p in 0..4u8 {
        if p == target_seat {
            continue;
        }
        let river = &opponent_rivers[p as usize];
        let kp = river.len();
        let tsumogiri_count = river.iter().filter(|d| d.tsumogiri).count();
        let num_kept = kp - tsumogiri_count;
        let is_riichi_opponent = river.iter().any(|d| d.is_riichi);

        let current_13 = synthesize_shanten_hand(&mut pool, is_riichi_opponent, x, &mut rng)?;

        let mut kept_indices: Vec<usize> = (0..13).collect();
        kept_indices.shuffle(&mut rng);
        let chosen = &kept_indices[..num_kept];
        let mut kept_tiles = Vec::new();
        let mut sorted = chosen.to_vec();
        sorted.sort_unstable_by(|a, b| b.cmp(a));
        let mut cur = current_13.to_vec();
        for idx in sorted {
            kept_tiles.push(cur.swap_remove(idx));
        }

        hands[p as usize] = HandAssignment { current_13, kept_draws: kept_tiles };
    }

    // Target: kept subset among the first 13 tiles (using actual target_past.len()).
    {
        let kp = target_past.len();
        let tsumogiri_count = target_past.iter().filter(|d| d.tsumogiri).count();
        let num_kept = (kp - tsumogiri_count).min(13);
        let current_13: [Tile; 13] = target_14[..13].try_into().unwrap();

        let mut kept_indices: Vec<usize> = (0..13).collect();
        kept_indices.shuffle(&mut rng);
        let chosen = &kept_indices[..num_kept];
        let mut kept_tiles = Vec::new();
        let mut sorted = chosen.to_vec();
        sorted.sort_unstable_by(|a, b| b.cmp(a));
        let mut cur = current_13.to_vec();
        for idx in sorted {
            kept_tiles.push(cur.swap_remove(idx));
        }
        hands[target_seat as usize] = HandAssignment { current_13, kept_draws: kept_tiles };
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

/// Assembles `n_out` full hand-assignment sets from per-player marginal
/// subfamilies (mean-field / sequential conditional scheme).
///
/// - For each opponent, `n_out` indices are resampled from the joint-deal pool
///   with probability proportional to that player's marginal likelihood.
/// - Hands are then combined sequentially (opponent by opponent) with a
///   tile-count compatibility check against the fixed tiles and previously
///   placed hands.
/// - If no compatible candidate is found within the retry budget for some
///   player, the original joint deal `i` (guaranteed compatible) is used as a
///   fallback. Returns (assembled, fallback_count).
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

    // Per-player deterministic resampling RNGs.
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
        current_13: [Tile::new_unchecked(0); 13],
        kept_draws: vec![],
    };

    for i in 0..n_out {
        let mut counts = fixed;
        let mut assembled: [HandAssignment; 4] = core::array::from_fn(|_| empty_hand.clone());
        // The target's hand is fixed by the query; keep its assignment from the
        // original joint deal (unweighted, only affects the yama script).
        assembled[target_seat as usize] = sub_hands[i % n_sub][target_seat as usize].clone();

        let mut ok = true;
        for (k, &p) in opponents.iter().enumerate() {
            let mut chosen: Option<usize> = None;
            for d in 0..budget {
                let idx = sub_idx[k][(i + d) % n_out];
                let hand = &sub_hands[idx][p as usize];
                let mut trial = counts;
                if add_hand_counts(&mut trial, &hand.current_13) {
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
            // Fallback to the original joint deal (compatible by construction).
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
        let target_past = vec![DiscardSpec { tile: parse_tile("9s"), tsumogiri: false }];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("E"), tsumogiri: false },
                DiscardSpec { tile: parse_tile("S"), tsumogiri: true },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("W"), tsumogiri: false }],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false }],
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
        let target_past = vec![DiscardSpec { tile: parse_tile("9s"), tsumogiri: false }];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("E"), tsumogiri: false },
                DiscardSpec { tile: parse_tile("S"), tsumogiri: true },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("W"), tsumogiri: false }],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false }],
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
        // Reuse the sampled spec hands as the pool of size 1 and verify the
        // assembly returns compatible hands with fallback=0.
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
        let target_past = vec![DiscardSpec { tile: parse_tile("9s"), tsumogiri: false }];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("E"), tsumogiri: false },
                DiscardSpec { tile: parse_tile("S"), tsumogiri: true },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("W"), tsumogiri: false }],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false }],
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
        assert_eq!(fallback, 0); // single-deal pool is self-compatible
        // Every assembled triple must be tile-compatible with fixed tiles.
        let fixed = fixed_tile_counts(&target_14, &target_past, &opponent_rivers, parse_tile("8s"));
        for hands in &assembled {
            let mut counts = fixed;
            for p in 0..4u8 {
                if p == 1 {
                    continue;
                }
                assert!(add_hand_counts(&mut counts, &hands[p as usize].current_13));
            }
        }
    }

    #[test]
    fn repro_qq_cmd() {
        // QQ: 234699m24789s336p seat=南(1) x=2 河=东:4z,1s;南:2zt;西:4z;北:9m
        let target_14: [Tile; 14] = [
            parse_tile("2m"), parse_tile("3m"), parse_tile("4m"),
            parse_tile("6m"), parse_tile("9m"), parse_tile("9m"),
            parse_tile("2s"), parse_tile("4s"), parse_tile("7s"),
            parse_tile("8s"), parse_tile("9s"), parse_tile("3p"),
            parse_tile("3p"), parse_tile("6p"),
        ];
        let target_past = vec![DiscardSpec { tile: parse_tile("S"), tsumogiri: true }];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("N"), tsumogiri: false },
                DiscardSpec { tile: parse_tile("1s"), tsumogiri: true },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false }],
            vec![DiscardSpec { tile: parse_tile("9m"), tsumogiri: false }],
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