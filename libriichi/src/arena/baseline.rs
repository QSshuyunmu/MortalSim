use super::prefix::{tile_bucket, bucket_limit, TILE_BUCKETS, DiscardSpec};
use crate::arena::board::UNSHUFFLED;
use crate::arena::board::Board;

use crate::tile::Tile;
use anyhow::{bail, ensure, Context, Result};
use rand::seq::SliceRandom;
use rand::Rng;
use rand_chacha::ChaCha12Rng;
use rand::SeedableRng;
use sha3::{Digest, Sha3_256};
use std::collections::HashMap;

/// Baseline 纯自然演进对局配置
#[derive(Debug, Clone)]
pub struct BaselineGameSpec {
    pub board: Board,
    pub oya: u8,
    pub target_seat: u8,
    pub x: u8,
    pub target_14: [Tile; 14],
}

/// 评估某张牌相对于目标 14 张手牌的"安全/无害等级"与"废牌优先级"
/// 等级越低越优先作为摸切废牌（字牌 < 19幺九 < 28 < 3~7中张）
/// 严格避开目标手牌的有效进张与邻接靠张牌
pub fn evaluate_waste_tier(tile: Tile, target_14: &[Tile; 14]) -> i32 {
    let t_id = tile.deaka().as_usize();
    
    // 1. 绝对不能是目标 14 张本身拥有的牌
    for &t in target_14 {
        if t.deaka().as_usize() == t_id {
            return 999; // 核心牌，严禁作为前置摸切废牌
        }
    }

    // 2. 检查是否为目标数牌的近邻靠张 (±1, ±2)
    let is_honor = t_id >= 27;
    if !is_honor {
        let suit = t_id / 9;
        let num = t_id % 9;
        for &t in target_14 {
            let other_id = t.deaka().as_usize();
            if other_id < 27 && other_id / 9 == suit {
                let other_num = other_id % 9;
                let diff = (num as i32 - other_num as i32).abs();
                if diff <= 1 {
                    return 500; // 紧邻靠张 (如 3m 旁边的 2m/4m)，尽量不摸切
                } else if diff == 2 {
                    return 300; // 嵌张靠张
                }
            }
        }
    }

    // 3. 基础无害等级 (字牌 0~20, 19幺九 100, 28 200, 3~7中张 250)
    if is_honor {
        // 客风/三元牌优先切
        match t_id {
            27..=30 => 10, // 东南西北
            31..=33 => 20, // 白发中
            _ => 15,
        }
    } else {
        let num = t_id % 9;
        match num {
            0 | 8 => 100, // 1m, 9m, 1p, 9p, 1s, 9s
            1 | 7 => 200, // 2, 8
            _ => 250,     // 3, 4, 5, 6, 7
        }
    }
}

/// 构造 Baseline 纯净正向对局：
/// - 自家起手即为目标 14 张中的前 13 张；
/// - 牌山为自家在第 1..x-1 巡安插最平稳素净的无害摸切废牌；
/// - 三家对手完全从 0 巡开始纯自然发牌，强制门清推进；
/// - 到达第 x 巡时自家摸入目标 14th 牌，完美无损接轨决策点。
pub fn build_baseline_game(
    target_seat: u8,
    oya: u8,
    x: u8,
    target_14: &[Tile; 14],
    dora_marker: Tile,
    kyoku: u8,
    honba: u8,
    kyotaku: u8,
    scores: [i32; 4],
    seed: (u64, u64),
) -> Result<BaselineGameSpec> {
    ensure!(target_seat < 4, "target_seat 0..3");
    ensure!(oya < 4, "oya 0..3");
    ensure!(x >= 1 && x <= 18, "x must be 1..18");

    // 1. 初始化剩余可用牌池 (136 - target_14 - dora)
    let mut pool: Vec<Tile> = UNSHUFFLED.to_vec();
    for &t in target_14 {
        let idx = pool.iter().position(|&p| p == t).context("target tile missing in pool")?;
        pool.swap_remove(idx);
    }
    let d_idx = pool.iter().position(|&p| p == dora_marker).context("dora missing in pool")?;
    pool.swap_remove(d_idx);

    let sb = {
        let mut hasher = Sha3_256::new();
        hasher.update(kyoku.to_le_bytes());
        hasher.update(honba.to_le_bytes());
        hasher.update([target_seat, oya, x]);
        hasher.update(seed.0.to_le_bytes());
        hasher.update(seed.1.to_le_bytes());
        let res = hasher.finalize();
        let mut b = [0u8; 32];
        b.copy_from_slice(&res);
        b
    };
    let mut rng = ChaCha12Rng::from_seed(sb);
    pool.shuffle(&mut rng);

    // 2. 为自家挑选第 1..x-1 巡的无害前置摸切舍牌 (有序选出等级最低的废牌)
    let mut target_waste_draws = Vec::new();
    let num_wastes_needed = (x - 1) as usize;

    if num_wastes_needed > 0 {
        // 按无害等级对池中可用牌打分排序
        let mut scored_pool: Vec<(usize, i32)> = pool
            .iter()
            .enumerate()
            .map(|(idx, &t)| (idx, evaluate_waste_tier(t, target_14)))
            .collect();
        scored_pool.sort_by_key(|&(_, tier)| tier);

        let mut chosen_pool_indices = Vec::new();
        let mut last_cut_id: Option<usize> = None;

        for &(p_idx, tier) in &scored_pool {
            if chosen_pool_indices.len() >= num_wastes_needed {
                break;
            }
            if tier >= 900 {
                break; // 严禁选用目标牌本身
            }
            let t = pool[p_idx];
            let t_id = t.deaka().as_usize();
            
            // 避免连续手切相同字牌（如连续两张 1z）
            if let Some(last_id) = last_cut_id {
                if t_id >= 27 && t_id == last_id {
                    continue;
                }
            }
            chosen_pool_indices.push(p_idx);
            last_cut_id = Some(t_id);
        }

        chosen_pool_indices.sort_unstable_by(|a, b| b.cmp(a));
        for idx in chosen_pool_indices {
            target_waste_draws.push(pool.swap_remove(idx));
        }
    }

    // 3. 构建 4 家 0 巡初始配牌
    let mut haipai: [[Tile; 13]; 4] = [[Tile::new_unchecked(0); 13]; 4];

    // 自家初始配牌：严格为目标 14 张中的前 13 张
    haipai[target_seat as usize] = target_14[..13].try_into().unwrap();

    // 其余 3 家对手：纯自然均匀随机发 13 张
    for p in 0..4usize {
        if p != target_seat as usize {
            ensure!(pool.len() >= 13, "pool underflow for opponent haipai");
            let opp_hand: [Tile; 13] = pool.drain(pool.len() - 13..).collect::<Vec<_>>().try_into().unwrap();
            haipai[p] = opp_hand;
        }
    }

    // 4. 构建牌山与王牌
    ensure!(pool.len() >= 14, "insufficient tiles for dead wall");
    pool.shuffle(&mut rng);

    let mut di: Vec<Tile> = pool.drain(pool.len() - 4..).collect();
    di.push(dora_marker);
    let rinshan: Vec<Tile> = pool.drain(pool.len() - 4..).collect();
    let ura_indicators: Vec<Tile> = pool.drain(pool.len() - 5..).collect();

    let mut yama = pool;

    // 将自家第 x 巡的目标摸牌 (14th tile) 及第 1..x-1 巡的无害摸切牌插在牌山顶部
    // (牌山以 pop 方式摸牌，后 push 的先摸到)
    let target_14th = target_14[13];
    yama.push(target_14th); // 第 x 巡摸进 14th tile

    for &waste_t in target_waste_draws.iter().rev() {
        yama.push(waste_t); // 第 1..x-1 巡摸切废牌
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

    Ok(BaselineGameSpec {
        board,
        oya,
        target_seat,
        x,
        target_14: *target_14,
    })
}
