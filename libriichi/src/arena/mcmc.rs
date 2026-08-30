#![allow(dead_code)]
/// Adaptive MCMC Local Perturbation Hand Sampler (Mode 1).
///
/// Samples opponent initial haipai conditional on observed river discards and
/// empirical Tenhou multi-dimensional shanten priors using Metropolis-Hastings.

use super::board::UNSHUFFLED;
use super::prefix::{
    validate_inputs, DiscardSpec, HandAssignment, PrefixGameSpec, build_prefix_game_from_hands,
};
use super::shanten_priors::TENHOU_MULTIDIM_SHANTEN_PRIORS;
use crate::algo::shanten::calc_all;
use crate::tile::Tile;
use anyhow::{ensure, Result};
use rand::seq::SliceRandom;
use rand::RngCore;
use rand::SeedableRng;
use rand_chacha::ChaCha12Rng;
use sha3::{Digest, Sha3_256};

/// Configuration parameters for MCMC haipai sampling.
#[derive(Debug, Clone, PartialEq)]
pub struct McmcConfig {
    /// Inverse temperature / score scaling factor alpha (default: 1.0)
    pub alpha: f64,
    /// Burn-in step count (default: 15)
    pub burn_in: usize,
    /// Thinning / sampling interval (default: 3)
    pub thinning: usize,
    /// Optional extra shanten penalty factor (default: 0.0)
    pub shanten_penalty: f64,
}

impl Default for McmcConfig {
    fn default() -> Self {
        Self {
            alpha: 1.0,
            burn_in: 15,
            thinning: 3,
            shanten_penalty: 0.0,
        }
    }
}

fn remove_tile(pool: &mut Vec<Tile>, tile: Tile) -> Result<()> {
    if let Some(pos) = pool.iter().position(|&t| t == tile) {
        pool.swap_remove(pos);
        Ok(())
    } else {
        anyhow::bail!("tile {:?} not found in available pool", tile)
    }
}

/// Computes the number of distinct middle suits (3..7 in m, p, s) discarded in a river.
/// Returns 0, 1, or 2 (clamped to 2) corresponding to `mid_var` index in shanten priors.
pub fn compute_mid_suits_cut(river: &[DiscardSpec]) -> u8 {
    let mut suits = [false; 3];
    for d in river {
        let id = d.tile.deaka().as_usize();
        if id < 27 {
            let suit = id / 9;
            let rank = id % 9;
            if (2..=6).contains(&rank) {
                suits[suit] = true;
            }
        }
    }
    let count = suits.iter().filter(|&&s| s).count();
    count.min(2) as u8
}

/// Nanosecond-fast shanten calculation for a 13-tile hand.
#[inline]
pub fn compute_hand_shanten(hand: &[Tile; 13]) -> i8 {
    let mut tiles = [0u8; 34];
    for &t in hand {
        tiles[t.deaka().as_usize()] += 1;
    }
    calc_all(&tiles, 4)
}

/// Computes empirical log prior log P_Tenhou(Shanten | x, furo, oya, mid_var).
#[inline]
pub fn compute_shanten_log_prior(
    shanten: i8,
    turn: u8,
    furo_type: u8,
    is_oya: bool,
    mid_var: u8,
) -> f64 {
    let turn_idx = (turn as usize).clamp(1, 18);
    let furo_idx = (furo_type as usize).min(3);
    let oya_idx = if is_oya { 1 } else { 0 };
    let mid_var_idx = (mid_var as usize).min(2);

    let priors = TENHOU_MULTIDIM_SHANTEN_PRIORS[turn_idx][furo_idx][oya_idx][mid_var_idx];
    let total: u32 = priors.iter().map(|&c| c as u32).sum();
    let total_f64 = if total == 0 { 10000.0 } else { total as f64 };

    let s_idx = shanten.clamp(0, 6) as usize;
    let count = priors[s_idx] as f64;

    if count > 0.0 {
        (count / total_f64).ln()
    } else {
        (0.1 / total_f64).ln()
    }
}

/// Computes target energy function E(H) for opponent hand H.
/// E(H) = alpha * log P_Tenhou(Shanten(H) | x, furo, oya, mid_var) - shanten_penalty * shanten
#[inline]
pub fn compute_hand_energy(
    hand: &[Tile; 13],
    turn: u8,
    furo_type: u8,
    is_oya: bool,
    mid_var: u8,
    config: &McmcConfig,
) -> f64 {
    let shanten = compute_hand_shanten(hand);
    let log_prior = compute_shanten_log_prior(shanten, turn, furo_type, is_oya, mid_var);
    let penalty = config.shanten_penalty * (shanten as f64);
    config.alpha * log_prior - penalty
}

fn derive_mcmc_seed(k0: u8, k1: u8, a: u8, b: u8, c: u64, d: u64) -> [u8; 32] {
    Sha3_256::new()
        .chain_update(b"mcmc_sampler_v1")
        .chain_update(k0.to_le_bytes())
        .chain_update(k1.to_le_bytes())
        .chain_update([a, b])
        .chain_update(c.to_le_bytes())
        .chain_update(d.to_le_bytes())
        .finalize()
        .into()
}

/// Samples `n_samples` hand assignments [HandAssignment; 4] via adaptive MCMC.
///
/// - Keeps target player's haipai strictly fixed.
/// - For each opponent, keeps river tedashis fixed and perturbs the remaining (13 - k) free tiles
///   by local swaps with the remaining available pool U.
/// - Metropolis-Hastings acceptance ensures convergence to empirical Tenhou shanten prior distribution.
pub fn sample_mcmc_hands(
    target_seat: u8,
    oya: u8,
    x: u8,
    target_14: &[Tile; 14],
    target_past: &[DiscardSpec],
    opponent_rivers: &[Vec<DiscardSpec>; 4],
    dora_marker: Tile,
    n_samples: usize,
    config: &McmcConfig,
    seed: (u64, u64),
) -> Result<Vec<[HandAssignment; 4]>> {
    validate_inputs(target_seat, oya, x, target_14, target_past, opponent_rivers, dora_marker)?;

    if n_samples == 0 {
        return Ok(Vec::new());
    }

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

    let seed_bytes = derive_mcmc_seed(0, 0, target_seat, x, seed.0, seed.1);
    let mut rng = ChaCha12Rng::from_seed(seed_bytes);
    pool.shuffle(&mut rng);

    // 2. Setup target player fixed hand
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

    // 3. Setup opponents initial hands & metadata
    let mut hands_state: [[Tile; 13]; 4] = [[Tile::new_unchecked(0); 13]; 4];
    let mut k_tedashi_arr = [0usize; 4];
    let mut mid_var_arr = [0u8; 4];
    let mut is_oya_arr = [false; 4];
    let mut energies = [0.0f64; 4];

    hands_state[target_seat as usize] = target_initial;

    for p in 0..4u8 {
        if p == target_seat {
            continue;
        }
        let p_idx = p as usize;
        let river = &opponent_rivers[p_idx];
        let tedashis: Vec<Tile> = river
            .iter()
            .filter(|d| !d.tsumogiri)
            .map(|d| d.tile)
            .collect();
        let k = tedashis.len();
        ensure!(k <= 13, "opponent {} tedashis ({}) exceed 13", p, k);
        k_tedashi_arr[p_idx] = k;
        let needed = 13 - k;
        ensure!(pool.len() >= needed, "insufficient pool for opponent {}", p);

        let mut opp_initial = tedashis;
        for _ in 0..needed {
            opp_initial.push(pool.pop().unwrap());
        }
        let initial_13: [Tile; 13] = opp_initial.try_into().unwrap();
        hands_state[p_idx] = initial_13;

        let mid_var = compute_mid_suits_cut(river);
        mid_var_arr[p_idx] = mid_var;
        let is_oya = p == oya;
        is_oya_arr[p_idx] = is_oya;

        energies[p_idx] = compute_hand_energy(&initial_13, x, 0, is_oya, mid_var, config);
    }

    // 4. MCMC Burn-in and Sampling
    let mut samples = Vec::with_capacity(n_samples);

    let step_chain = |hands: &mut [[Tile; 13]; 4],
                      free_pool: &mut Vec<Tile>,
                      energies: &mut [f64; 4],
                      rng: &mut ChaCha12Rng| {
        for p in 0..4u8 {
            if p == target_seat {
                continue;
            }
            let p_idx = p as usize;
            let k = k_tedashi_arr[p_idx];
            let free_count = 13 - k;
            if free_count == 0 || free_pool.is_empty() {
                continue;
            }

            let free_idx = (rng.next_u64() as usize) % free_count;
            let hand_pos = k + free_idx;
            let pool_idx = (rng.next_u64() as usize) % free_pool.len();

            let t_old = hands[p_idx][hand_pos];
            let t_new = free_pool[pool_idx];

            if t_old == t_new {
                continue;
            }

            let mut candidate_hand = hands[p_idx];
            candidate_hand[hand_pos] = t_new;

            let cand_energy = compute_hand_energy(
                &candidate_hand,
                x,
                0,
                is_oya_arr[p_idx],
                mid_var_arr[p_idx],
                config,
            );

            let delta_e = cand_energy - energies[p_idx];
            let accept = if delta_e >= 0.0 {
                true
            } else {
                let accept_prob = delta_e.exp();
                let u = (rng.next_u64() >> 11) as f64 * (1.0 / (1u64 << 53) as f64);
                u < accept_prob
            };

            if accept {
                hands[p_idx][hand_pos] = t_new;
                free_pool[pool_idx] = t_old;
                energies[p_idx] = cand_energy;
            }
        }
    };

    // Burn-in
    for _ in 0..config.burn_in {
        step_chain(&mut hands_state, &mut pool, &mut energies, &mut rng);
    }

    let make_hand_assignment = |hands: &[[Tile; 13]; 4]| -> [HandAssignment; 4] {
        core::array::from_fn(|i| HandAssignment {
            initial_13: hands[i],
        })
    };

    // Collect first sample after burn-in
    samples.push(make_hand_assignment(&hands_state));

    // Collect remaining samples with thinning interval
    let stride = config.thinning.max(1);
    for _ in 1..n_samples {
        for _ in 0..stride {
            step_chain(&mut hands_state, &mut pool, &mut energies, &mut rng);
        }
        samples.push(make_hand_assignment(&hands_state));
    }

    Ok(samples)
}

/// Constructs a single PrefixGameSpec using MCMC sampled opponent hands.
pub fn sample_mcmc_prefix_game(
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
    config: &McmcConfig,
    seed: (u64, u64),
) -> Result<PrefixGameSpec> {
    let hands = sample_mcmc_hands(
        target_seat,
        oya,
        x,
        target_14,
        target_past,
        opponent_rivers,
        dora_marker,
        1,
        config,
        seed,
    )?;
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
        &hands[0],
        seed,
    )
}

/// Constructs multiple PrefixGameSpec instances using MCMC sampled opponent hands.
pub fn sample_mcmc_prefix_games(
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
    n_samples: usize,
    config: &McmcConfig,
    seed: (u64, u64),
) -> Result<Vec<PrefixGameSpec>> {
    let hands_vec = sample_mcmc_hands(
        target_seat,
        oya,
        x,
        target_14,
        target_past,
        opponent_rivers,
        dora_marker,
        n_samples,
        config,
        seed,
    )?;

    let mut specs = Vec::with_capacity(hands_vec.len());
    for (i, hands) in hands_vec.iter().enumerate() {
        let game_seed = (seed.0.wrapping_add(i as u64), seed.1);
        let spec = build_prefix_game_from_hands(
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
            hands,
            game_seed,
        )?;
        specs.push(spec);
    }

    Ok(specs)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::arena::board::Poll;
    use crate::arena::prefix::{bucket_limit, tile_bucket, TILE_BUCKETS};
    use crate::mjai::{Event, EventExt};
    use std::array;
    use std::str::FromStr;

    fn parse_tile(s: &str) -> Tile {
        Tile::from_str(s).unwrap()
    }

    #[test]
    fn test_compute_mid_suits_cut() {
        // Only honors / terminals
        let river1 = vec![
            DiscardSpec { tile: parse_tile("1m"), tsumogiri: false, is_riichi: false },
            DiscardSpec { tile: parse_tile("9p"), tsumogiri: false, is_riichi: false },
            DiscardSpec { tile: parse_tile("E"), tsumogiri: false, is_riichi: false },
        ];
        assert_eq!(compute_mid_suits_cut(&river1), 0);

        // 1 middle suit (manzu 3m)
        let river2 = vec![
            DiscardSpec { tile: parse_tile("3m"), tsumogiri: false, is_riichi: false },
            DiscardSpec { tile: parse_tile("5m"), tsumogiri: false, is_riichi: false },
            DiscardSpec { tile: parse_tile("9s"), tsumogiri: false, is_riichi: false },
        ];
        assert_eq!(compute_mid_suits_cut(&river2), 1);

        // 2 middle suits (3m, 6p)
        let river3 = vec![
            DiscardSpec { tile: parse_tile("3m"), tsumogiri: false, is_riichi: false },
            DiscardSpec { tile: parse_tile("6p"), tsumogiri: false, is_riichi: false },
        ];
        assert_eq!(compute_mid_suits_cut(&river3), 2);

        // 3 middle suits (3m, 6p, 5s) -> clamped to 2
        let river4 = vec![
            DiscardSpec { tile: parse_tile("3m"), tsumogiri: false, is_riichi: false },
            DiscardSpec { tile: parse_tile("6p"), tsumogiri: false, is_riichi: false },
            DiscardSpec { tile: parse_tile("5s"), tsumogiri: false, is_riichi: false },
        ];
        assert_eq!(compute_mid_suits_cut(&river4), 2);
    }

    #[test]
    fn test_compute_shanten_and_energy() {
        let hand_tiles = [
            parse_tile("1m"), parse_tile("2m"), parse_tile("3m"),
            parse_tile("4m"), parse_tile("5m"), parse_tile("6m"),
            parse_tile("7m"), parse_tile("8m"), parse_tile("9m"),
            parse_tile("1p"), parse_tile("2p"), parse_tile("3p"),
            parse_tile("P"),
        ];
        let shanten = compute_hand_shanten(&hand_tiles);
        assert_eq!(shanten, 0); // Tenpai

        let config = McmcConfig::default();
        let energy = compute_hand_energy(&hand_tiles, 1, 0, false, 0, &config);
        assert!(energy.is_finite());
        assert!(energy <= 0.0);
    }

    #[test]
    fn test_sample_mcmc_hands_invariants() {
        let target_14 = [
            parse_tile("1m"), parse_tile("2m"), parse_tile("3m"),
            parse_tile("4m"), parse_tile("5m"), parse_tile("6m"),
            parse_tile("7m"), parse_tile("8m"), parse_tile("9m"),
            parse_tile("1p"), parse_tile("2p"), parse_tile("3p"),
            parse_tile("4p"), parse_tile("5p"),
        ];
        let target_past = vec![
            DiscardSpec { tile: parse_tile("9s"), tsumogiri: false, is_riichi: false },
        ];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("E"), tsumogiri: false, is_riichi: false },
                DiscardSpec { tile: parse_tile("S"), tsumogiri: true, is_riichi: false },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("W"), tsumogiri: false, is_riichi: false }],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false, is_riichi: false }],
        ];
        let dora_marker = parse_tile("8s");
        let config = McmcConfig {
            alpha: 1.0,
            burn_in: 15,
            thinning: 3,
            shanten_penalty: 0.0,
        };

        let samples = sample_mcmc_hands(
            1, 0, 2, &target_14, &target_past, &opponent_rivers,
            dora_marker, 10, &config, (42, 99),
        ).unwrap();

        assert_eq!(samples.len(), 10);

        for sample in &samples {
            // Check target hand fixed
            assert_eq!(sample[1].initial_13[0], parse_tile("9s")); // tedashi
            for i in 0..12 {
                assert_eq!(sample[1].initial_13[1 + i], target_14[i]);
            }

            // Check opponent 0 preserved tedashi 'E' at index 0
            assert_eq!(sample[0].initial_13[0], parse_tile("E"));

            // Check opponent 2 preserved tedashi 'W' at index 0
            assert_eq!(sample[2].initial_13[0], parse_tile("W"));

            // Check opponent 3 preserved tedashi 'N' at index 0
            assert_eq!(sample[3].initial_13[0], parse_tile("N"));

            // Check physical bucket counts per hand <= limit
            for p in 0..4 {
                let mut counts = [0u8; TILE_BUCKETS];
                for &t in &sample[p].initial_13 {
                    let b = tile_bucket(t);
                    counts[b] += 1;
                    assert!(counts[b] <= bucket_limit(b), "bucket {} exceeded in seat {}", b, p);
                }
            }

            // Check total table tile counts
            let mut total_counts = [0u8; TILE_BUCKETS];
            for p in 0..4 {
                for &t in &sample[p].initial_13 {
                    total_counts[tile_bucket(t)] += 1;
                }
            }
            total_counts[tile_bucket(dora_marker)] += 1;
            for d in &target_past {
                if d.tsumogiri {
                    total_counts[tile_bucket(d.tile)] += 1;
                }
            }
            for p in 0..4 {
                if p != 1 {
                    for d in &opponent_rivers[p] {
                        if d.tsumogiri {
                            total_counts[tile_bucket(d.tile)] += 1;
                        }
                    }
                }
            }
            // Add target 14th tile and drawn tiles
            total_counts[tile_bucket(target_14[13])] += 1;
            total_counts[tile_bucket(target_14[12])] += 1;

            for b in 0..TILE_BUCKETS {
                assert!(total_counts[b] <= bucket_limit(b), "total bucket {} exceeded", b);
            }
        }
    }

    #[test]
    fn test_sample_mcmc_reproducibility() {
        let target_14 = [
            parse_tile("1m"), parse_tile("2m"), parse_tile("3m"),
            parse_tile("4m"), parse_tile("5m"), parse_tile("6m"),
            parse_tile("7m"), parse_tile("8m"), parse_tile("9m"),
            parse_tile("1p"), parse_tile("2p"), parse_tile("3p"),
            parse_tile("4p"), parse_tile("5p"),
        ];
        let target_past = vec![
            DiscardSpec { tile: parse_tile("9s"), tsumogiri: false, is_riichi: false },
        ];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("E"), tsumogiri: false, is_riichi: false },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("W"), tsumogiri: false, is_riichi: false }],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false, is_riichi: false }],
        ];
        let dora_marker = parse_tile("8s");
        let config = McmcConfig::default();

        let s1 = sample_mcmc_hands(
            1, 0, 2, &target_14, &target_past, &opponent_rivers,
            dora_marker, 5, &config, (100, 200),
        ).unwrap();

        let s2 = sample_mcmc_hands(
            1, 0, 2, &target_14, &target_past, &opponent_rivers,
            dora_marker, 5, &config, (100, 200),
        ).unwrap();

        assert_eq!(s1, s2);
    }

    #[test]
    fn test_sample_mcmc_prefix_games_batch() {
        let target_14 = [
            parse_tile("1m"), parse_tile("2m"), parse_tile("3m"),
            parse_tile("4m"), parse_tile("5m"), parse_tile("6m"),
            parse_tile("7m"), parse_tile("8m"), parse_tile("9m"),
            parse_tile("1p"), parse_tile("2p"), parse_tile("3p"),
            parse_tile("4p"), parse_tile("5p"),
        ];
        let target_past = vec![
            DiscardSpec { tile: parse_tile("9s"), tsumogiri: false, is_riichi: false },
        ];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("E"), tsumogiri: false, is_riichi: false },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("W"), tsumogiri: false, is_riichi: false }],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false, is_riichi: false }],
        ];
        let dora_marker = parse_tile("8s");
        let config = McmcConfig::default();

        let specs = sample_mcmc_prefix_games(
            1, 0, 2, &target_14, &target_past, &opponent_rivers,
            dora_marker, 1, 0, 0, [25000; 4], 3, &config, (12345, 67890),
        ).unwrap();

        assert_eq!(specs.len(), 3);
        for spec in &specs {
            assert_eq!(spec.target_seat, 1);
            assert_eq!(spec.oya, 0);
        }
    }

    #[test]
    fn test_mcmc_prefix_game_replay_compatibility() {
        let target_14 = [
            parse_tile("1m"), parse_tile("2m"), parse_tile("3m"),
            parse_tile("4m"), parse_tile("5m"), parse_tile("6m"),
            parse_tile("7m"), parse_tile("8m"), parse_tile("9m"),
            parse_tile("1p"), parse_tile("2p"), parse_tile("3p"),
            parse_tile("4p"), parse_tile("5p"),
        ];
        let target_past = vec![
            DiscardSpec { tile: parse_tile("9s"), tsumogiri: false, is_riichi: false },
        ];
        let opponent_rivers = [
            vec![
                DiscardSpec { tile: parse_tile("E"), tsumogiri: false, is_riichi: false },
                DiscardSpec { tile: parse_tile("S"), tsumogiri: true, is_riichi: false },
            ],
            vec![],
            vec![DiscardSpec { tile: parse_tile("W"), tsumogiri: false, is_riichi: false }],
            vec![DiscardSpec { tile: parse_tile("N"), tsumogiri: false, is_riichi: false }],
        ];
        let dora_marker = parse_tile("8s");
        let config = McmcConfig::default();

        let spec = sample_mcmc_prefix_game(
            1, 0, 2, &target_14, &target_past, &opponent_rivers,
            dora_marker, 1, 0, 0, [25000; 4], &config, (12345, 67890),
        ).unwrap();

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

        // Must reach decision point for target player (seat 1)
        assert!(bs.agent_context().player_states[1].last_cans().can_discard);
        let tehai = bs.agent_context().player_states[1].tehai();
        let mut expected = [0u8; 34];
        for &t in &target_14 {
            expected[t.deaka().as_usize()] += 1;
        }
        assert_eq!(tehai, expected);
    }
}
