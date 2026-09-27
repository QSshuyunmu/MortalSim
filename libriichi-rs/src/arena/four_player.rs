//! FourPlayer — 四家混战竞技场：每桌 4 个不同模型，座位跨 split 轮转。
//! 适配自 one_vs_three.rs，供模型池评测使用（支持逐半庄明细与 MJAI 落盘）。
use super::game::{BatchGame, Index};
use super::result::GameResult;
use crate::agent::{BatchAgent, new_py_agent};
use std::fs::{self, File};
use std::io;
use std::iter;
use std::path::PathBuf;
use std::time::Duration;

use anyhow::Result;
use flate2::Compression;
use flate2::read::GzEncoder;
use indicatif::{ParallelProgressIterator, ProgressBar, ProgressStyle};
use pyo3::prelude::*;
use rayon::prelude::*;

#[pyclass]
#[derive(Clone, Default)]
pub struct FourPlayer {
    pub disable_progress_bar: bool,
    pub log_dir: Option<String>,
}

#[pymethods]
impl FourPlayer {
    #[new]
    #[pyo3(signature = (*, disable_progress_bar=false, log_dir=None))]
    const fn new(disable_progress_bar: bool, log_dir: Option<String>) -> Self {
        Self {
            disable_progress_bar,
            log_dir,
        }
    }

    /// 逐半庄明细：(seed, key, split, seat_of_engine0, rank_of_engine0, scores)
    pub fn py_vs_py_detailed(
        &self,
        e0: PyObject,
        e1: PyObject,
        e2: PyObject,
        e3: PyObject,
        seed_start: (u64, u64),
        seed_count: u64,
        py: Python<'_>,
    ) -> Result<Vec<(u64, u64, u8, [u8; 4], [i32; 4])>> {
        py.allow_threads(move || {
            let (results, _logs) = self.run_batch(e0, e1, e2, e3, seed_start, seed_count, false)?;
            Ok(results
                .into_iter()
                .enumerate()
                .map(|(i, result)| {
                    let split = (i % 4) as u8;
                    // 权威顺位：直接取 Rust 结算的 rank_by_player（1..4），
                    // 避免由 scores 反推名次带来的并列口径误差。
                    let mut ranks = [0u8; 4];
                    for (s, v) in result.rankings().rank_by_player.iter().enumerate() {
                        ranks[s] = *v as u8;
                    }
                    (result.seed.0, result.seed.1, split, ranks, result.scores)
                })
                .collect())
        })
    }

    /// 带回牌谱 JSON 的版本：(seed, key, split, ranks, scores, log_json)
    /// Rust 只构造字符串，压缩/写盘由 Python 侧独立进程池并行完成（见 L5 方案）。
    pub fn py_vs_py_detailed_with_logs(
        &self,
        e0: PyObject,
        e1: PyObject,
        e2: PyObject,
        e3: PyObject,
        seed_start: (u64, u64),
        seed_count: u64,
        py: Python<'_>,
    ) -> Result<Vec<(u64, u64, u8, [u8; 4], [i32; 4], String)>> {
        py.allow_threads(move || {
            let (results, logs) = self.run_batch(e0, e1, e2, e3, seed_start, seed_count, true)?;
            let mut out = Vec::with_capacity(results.len());
            for (i, result) in results.into_iter().enumerate() {
                let split = (i % 4) as u8;
                let mut ranks = [0u8; 4];
                for (s, v) in result.rankings().rank_by_player.iter().enumerate() {
                    ranks[s] = *v as u8;
                }
                out.push((
                    result.seed.0,
                    result.seed.1,
                    split,
                    ranks,
                    result.scores,
                    logs[i].clone(),
                ));
            }
            Ok(out)
        })
    }

    /// 仅返回引擎 0 的顺位分布（对齐 OneVsThree.py_vs_py 的返回形态）
    pub fn py_vs_py(
        &self,
        e0: PyObject,
        e1: PyObject,
        e2: PyObject,
        e3: PyObject,
        seed_start: (u64, u64),
        seed_count: u64,
        py: Python<'_>,
    ) -> Result<[i32; 4]> {
        py.allow_threads(move || {
            let (results, _logs) = self.run_batch(e0, e1, e2, e3, seed_start, seed_count, false)?;
            let mut rankings = [0; 4];
            for (i, result) in results.iter().enumerate() {
                let rank = result.rankings().rank_by_player[(i % 4) as usize];
                rankings[rank as usize] += 1;
            }
            Ok(rankings)
        })
    }
}

impl FourPlayer {
    fn run_batch(
        &self,
        e0: PyObject,
        e1: PyObject,
        e2: PyObject,
        e3: PyObject,
        seed_start: (u64, u64),
        seed_count: u64,
        want_logs: bool,
    ) -> Result<(Vec<GameResult>, Vec<String>)> {
        if let Some(dir) = &self.log_dir {
            fs::create_dir_all(dir)?;
        }

        log::info!(
            "4p seed: [{}, {}) w/ {:#x}, start {} sets, {} hanchans",
            seed_start.0,
            seed_start.0 + seed_count,
            seed_start.1,
            seed_count,
            seed_count * 4,
        );

        let seeds: Vec<_> = (seed_start.0..seed_start.0 + seed_count)
            .flat_map(|seed| iter::repeat_n((seed, seed_start.1), 4))
            .collect();

        // 引擎 i 在第 split 局坐 seat = (i + split) % 4
        let games = (seed_count * 4) as usize;
        let mut player_ids: [Vec<u8>; 4] = [
            Vec::with_capacity(games),
            Vec::with_capacity(games),
            Vec::with_capacity(games),
            Vec::with_capacity(games),
        ];
        for j in 0..games {
            let split = j % 4;
            for (i, ids) in player_ids.iter_mut().enumerate() {
                ids.push(((i + split) % 4) as u8);
            }
        }

        let mut agents: [Box<dyn BatchAgent>; 4] = [
            new_py_agent(e0, &player_ids[0])?,
            new_py_agent(e1, &player_ids[1])?,
            new_py_agent(e2, &player_ids[2])?,
            new_py_agent(e3, &player_ids[3])?,
        ];

        let mut counters = [0usize; 4];
        let mut indexes: Vec<[Index; 4]> = Vec::with_capacity(games);
        for j in 0..games {
            let split = j % 4;
            let mut row: [Index; 4] = [
                Index {
                    agent_idx: 0,
                    player_id_idx: 0,
                },
                Index {
                    agent_idx: 0,
                    player_id_idx: 0,
                },
                Index {
                    agent_idx: 0,
                    player_id_idx: 0,
                },
                Index {
                    agent_idx: 0,
                    player_id_idx: 0,
                },
            ];
            for seat in 0..4 {
                let agent_idx = (seat + 4 - split) % 4;
                row[seat] = Index {
                    agent_idx,
                    player_id_idx: counters[agent_idx],
                };
                counters[agent_idx] += 1;
            }
            indexes.push(row);
        }

        let batch_game = BatchGame::tenhou_hanchan(self.disable_progress_bar);
        let results = batch_game.run(&mut agents, &indexes, &seeds)?;

        if want_logs {
            // L5：Rust 只并行构造 JSON 字符串，压缩/写盘由 Python 独立进程池完成，
            // 与下一批对局计算重叠，避免阻塞关键路径（实测该段落盘占 27% 墙钟）。
            let logs: Vec<String> = results
                .par_iter()
                .map(|game_result| game_result.dump_json_log())
                .collect::<Result<Vec<_>>>()?;
            return Ok((results, logs));
        }

        if let Some(dir) = &self.log_dir {
            log::info!("dumping game logs");

            let bar = if self.disable_progress_bar {
                ProgressBar::hidden()
            } else {
                ProgressBar::new(seed_count * 4)
            };
            const TEMPLATE: &str = "[{elapsed_precise}] [{wide_bar}] {pos}/{len} {percent:>3}%";
            bar.set_style(ProgressStyle::with_template(TEMPLATE)?.progress_chars("#-"));

            results
                .par_iter()
                .progress_with(bar)
                .enumerate()
                .try_for_each(|(i, game_result)| {
                    let split_name = ["a", "b", "c", "d"][i % 4];
                    let (seed, key) = game_result.seed;
                    let filename: PathBuf = [dir, &format!("{seed}_{key}_{split_name}.json.gz")]
                        .iter()
                        .collect();

                    let log = game_result.dump_json_log()?;
                    let mut comp = GzEncoder::new(log.as_bytes(), Compression::fast());
                    let mut f = File::create(filename)?;
                    io::copy(&mut comp, &mut f)?;

                    anyhow::Ok(())
                })?;
        }

        Ok((results, Vec::new()))
    }
}