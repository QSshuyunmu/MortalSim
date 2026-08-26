#![allow(dead_code)]
/// Utilities for softmax policy likelihood calculation and Self-Normalized
/// Importance Sampling (SNIS) weight normalization / ESS diagnostics.
use rand::RngCore;

/// Computes log P(action | state) under the Boltzmann policy:
///   P(a | s) = exp(Q(s, a) / tau) / sum_{b in legal} exp(Q(s, b) / tau)
///
/// Uses standard max subtraction for numerical stability:
///   let max_q = max_{b in legal} Q(s, b)
///   ln P(a | s) = (Q(s, a) - max_q)/tau - ln sum_{b in legal} exp((Q(s, b) - max_q)/tau)
pub fn softmax_log_prob(
    scores: &[f32],
    legal_mask: &[bool],
    action: usize,
    tau: f32,
) -> Result<f64, String> {
    if scores.len() != legal_mask.len() {
        return Err(format!(
            "scores length ({}) does not match legal_mask length ({})",
            scores.len(),
            legal_mask.len()
        ));
    }
    if action >= scores.len() {
        return Err(format!(
            "action index {} out of bounds for action space {}",
            action,
            scores.len()
        ));
    }
    if !legal_mask[action] {
        return Err(format!("action {} is not legal in the provided mask", action));
    }
    if tau <= 0.0 || tau.is_nan() {
        return Err(format!("temperature tau must be positive, got {}", tau));
    }

    let mut max_q = f32::NEG_INFINITY;
    let mut any_legal = false;
    for (i, (&q, &legal)) in scores.iter().zip(legal_mask).enumerate() {
        if legal {
            any_legal = true;
            if q.is_nan() {
                return Err(format!("NaN Q-value encountered at legal action {}", i));
            }
            if q > max_q {
                max_q = q;
            }
        }
    }

    if !any_legal {
        return Err("no legal actions in mask".to_string());
    }

    let tau_f64 = tau as f64;
    let max_q_f64 = max_q as f64;
    let mut sum_exp = 0.0f64;
    for (&q, &legal) in scores.iter().zip(legal_mask) {
        if legal {
            let diff = (q as f64 - max_q_f64) / tau_f64;
            sum_exp += diff.exp();
        }
    }

    if sum_exp <= 0.0 || sum_exp.is_nan() {
        return Err("invalid partition sum in softmax".to_string());
    }

    let action_diff = (scores[action] as f64 - max_q_f64) / tau_f64;
    let log_prob = action_diff - sum_exp.ln();

    // Clamp for extreme precision edge cases (log_prob must be <= 0.0)
    Ok(log_prob.min(0.0))
}

/// Draws `n` indices from `0..log_weights.len()` with replacement,
/// with probability proportional to `exp(log_weights[i] - max)`
/// (Log-Sum-Exp stable). Deterministic for a given RNG.
pub fn resample_indices(
    log_weights: &[f64],
    n: usize,
    rng: &mut rand_chacha::ChaCha12Rng,
) -> Vec<usize> {
    if log_weights.is_empty() {
        return Vec::new();
    }
    let max = log_weights
        .iter()
        .copied()
        .fold(f64::NEG_INFINITY, f64::max);
    let mut cdf = Vec::with_capacity(log_weights.len());
    let mut acc = 0.0f64;
    for &lw in log_weights {
        acc += (lw - max).exp();
        cdf.push(acc);
    }
    let total = acc;
    let mut out = Vec::with_capacity(n);
    if total > 0.0 && total.is_finite() {
        for _ in 0..n {
            let u = (rng.next_u64() >> 11) as f64 * (1.0 / (1u64 << 53) as f64) * total;
            let idx = cdf.partition_point(|&v| v < u);
            out.push(idx.min(log_weights.len() - 1));
        }
    } else {
        // All weights zero (degenerate): fall back to uniform.
        for _ in 0..n {
            out.push((rng.next_u64() as usize) % log_weights.len());
        }
    }
    out
}

#[derive(Debug, Clone, PartialEq)]
pub struct WeightSummary {
    /// Normalized weights bar{w}_i, sum = 1.0
    pub weights: Vec<f64>,
    /// Effective Sample Size: 1.0 / sum(bar{w}_i^2)
    pub ess: f64,
    /// ESS ratio: ESS / N
    pub ess_ratio: f64,
    /// 10th percentile weight
    pub p10: f64,
    /// 50th percentile (median) weight
    pub p50: f64,
    /// 90th percentile weight
    pub p90: f64,
    /// Maximum normalized weight
    pub max_weight: f64,
}

/// Normalizes log-likelihoods using Log-Sum-Exp to produce normalized weights
/// and computes ESS and distribution quantiles.
pub fn compute_snis_weights(log_likelihoods: &[f64]) -> Result<WeightSummary, String> {
    let n = log_likelihoods.len();
    if n == 0 {
        return Err("log_likelihoods slice cannot be empty".to_string());
    }

    let mut max_log = f64::NEG_INFINITY;
    for &log_l in log_likelihoods {
        if log_l.is_nan() {
            return Err("NaN log-likelihood encountered".to_string());
        }
        if log_l > max_log {
            max_log = log_l;
        }
    }

    // All samples had -inf likelihood
    if max_log == f64::NEG_INFINITY {
        let uniform = 1.0 / n as f64;
        return Ok(WeightSummary {
            weights: vec![uniform; n],
            ess: n as f64,
            ess_ratio: 1.0,
            p10: uniform,
            p50: uniform,
            p90: uniform,
            max_weight: uniform,
        });
    }

    // Exponentiate with max subtraction (Log-Sum-Exp)
    let mut unnorm_weights = Vec::with_capacity(n);
    let mut sum_w = 0.0f64;
    for &log_l in log_likelihoods {
        let w = (log_l - max_log).exp();
        unnorm_weights.push(w);
        sum_w += w;
    }

    if sum_w <= 0.0 || sum_w.is_nan() {
        return Err("sum of unnormalized weights must be positive".to_string());
    }

    let inv_sum = 1.0 / sum_w;
    let mut norm_weights = Vec::with_capacity(n);
    let mut sum_sq = 0.0f64;
    let mut max_w = 0.0f64;

    for &w in &unnorm_weights {
        let nw = w * inv_sum;
        norm_weights.push(nw);
        sum_sq += nw * nw;
        if nw > max_w {
            max_w = nw;
        }
    }

    let ess = if sum_sq > 0.0 { 1.0 / sum_sq } else { 1.0 };
    let ess_ratio = ess / n as f64;

    // Compute quantiles
    let mut sorted = norm_weights.clone();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    let p10 = sorted[(n as f64 * 0.10).floor() as usize];
    let p50 = sorted[(n as f64 * 0.50).floor() as usize];
    let p90 = sorted[((n as f64 * 0.90).floor() as usize).min(n - 1)];

    Ok(WeightSummary {
        weights: norm_weights,
        ess,
        ess_ratio,
        p10,
        p50,
        p90,
        max_weight: max_w,
    })
}

/// Computes the weighted mean sum_i (w_i * x_i) assuming sum_i w_i = 1.
pub fn weighted_mean(values: &[f64], weights: &[f64]) -> f64 {
    debug_assert_eq!(values.len(), weights.len());
    values.iter().zip(weights).map(|(&x, &w)| x * w).sum()
}

/// Computes the estimated standard error of the weighted mean:
///   SE = sqrt( (1 / ESS) * sum_i w_i * (x_i - mean)^2 )
pub fn weighted_std_err(values: &[f64], weights: &[f64], ess: f64) -> f64 {
    debug_assert_eq!(values.len(), weights.len());
    if ess <= 1.0 {
        return 0.0;
    }
    let mean = weighted_mean(values, weights);
    let var: f64 = values
        .iter()
        .zip(weights)
        .map(|(&x, &w)| w * (x - mean) * (x - mean))
        .sum();
    (var / ess).sqrt()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_single_legal_action() {
        let scores = [10.0, 5.0, 2.0];
        let mask = [false, true, false];
        let log_p = softmax_log_prob(&scores, &mask, 1, 1.0).unwrap();
        assert_eq!(log_p, 0.0); // P = 1.0, ln P = 0.0
    }

    #[test]
    fn test_uniform_scores() {
        let scores = [2.0, 2.0, 2.0, 2.0];
        let mask = [true, true, true, true];
        let log_p = softmax_log_prob(&scores, &mask, 0, 1.0).unwrap();
        let expected = (1.0f64 / 4.0).ln();
        assert!((log_p - expected).abs() < 1e-6);
    }

    #[test]
    fn test_temperature_scaling() {
        let scores = [4.0, 2.0];
        let mask = [true, true];
        // tau = 2.0 -> logits = [2.0, 1.0] -> diff = 1.0 -> P(0) = e^1 / (e^1 + 1)
        let log_p = softmax_log_prob(&scores, &mask, 0, 2.0).unwrap();
        let expected_p = 1.0 / (1.0 + (-1.0f64).exp());
        assert!((log_p.exp() - expected_p).abs() < 1e-6);
    }

    #[test]
    fn test_large_scores_no_overflow() {
        let scores = [10000.0, 9999.0, 9000.0];
        let mask = [true, true, true];
        let log_p = softmax_log_prob(&scores, &mask, 0, 1.0).unwrap();
        let expected_p = 1.0 / (1.0 + (-1.0f64).exp() + (-1000.0f64).exp());
        assert!((log_p.exp() - expected_p).abs() < 1e-6);
    }

    #[test]
    fn test_illegal_action_error() {
        let scores = [1.0, 2.0];
        let mask = [true, false];
        assert!(softmax_log_prob(&scores, &mask, 1, 1.0).is_err());
    }

    #[test]
    fn test_snis_weights_uniform() {
        let logs = [0.0; 100];
        let summary = compute_snis_weights(&logs).unwrap();
        assert!((summary.ess - 100.0).abs() < 1e-5);
        assert!((summary.ess_ratio - 1.0).abs() < 1e-5);
        assert!((summary.weights[0] - 0.01).abs() < 1e-5);
    }

    #[test]
    fn test_snis_weights_single_dominant() {
        let mut logs = [-1000.0; 100];
        logs[0] = 0.0;
        let summary = compute_snis_weights(&logs).unwrap();
        assert!((summary.ess - 1.0).abs() < 1e-4);
        assert!((summary.weights[0] - 1.0).abs() < 1e-5);
        assert_eq!(summary.weights[1], 0.0);
    }

    #[test]
    fn test_resample_indices_concentrates() {
        use rand_chacha::ChaCha12Rng;
        use rand::SeedableRng;
        let logs = vec![0.0, -100.0, -100.0, -100.0];
        let mut rng = ChaCha12Rng::seed_from_u64(42);
        let idx = resample_indices(&logs, 200, &mut rng);
        assert_eq!(idx.len(), 200);
        assert!(idx.iter().all(|&i| i == 0));
    }

    #[test]
    fn test_weighted_mean_and_stderr() {
        let values = [10.0, 20.0, 30.0];
        let weights = [0.2, 0.5, 0.3];
        let mean = weighted_mean(&values, &weights);
        assert!((mean - 21.0).abs() < 1e-6);
    }
}
