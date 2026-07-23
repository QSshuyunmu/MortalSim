import json
import os
import time
import atexit
import traceback
import torch
import numpy as np
from torch.distributions import Normal, Categorical
from typing import *

# ── Profiler (opt-in via MORTAL_PROFILE=1) ──────────────────────────────
_PROFILE = os.environ.get("MORTAL_PROFILE") == "1"
_PROF = {
    "calls": 0, "sum_batch": 0,
    "t_total": 0.0, "t_stack": 0.0, "t_tensor": 0.0,
    "t_infer": 0.0, "t_tolist": 0.0,
}

def _profile_sync(device):
    if device.type == "cuda":
        torch.cuda.synchronize(device)

def _print_prof():
    if not _PROFILE or _PROF["calls"] == 0:
        return
    c = _PROF["calls"]
    sb = _PROF["sum_batch"] / c
    print("\n═══ MORTAL_PROFILE ─══", flush=True)
    print(f"  react_batch calls : {c}", flush=True)
    print(f"  avg batch size    : {sb:.1f}", flush=True)
    print(f"  total time        : {_PROF['t_total']*1000:.1f} ms", flush=True)
    print(f"    input array             : {_PROF['t_stack']*1000:.1f} ms "
          f"({_PROF['t_stack']/_PROF['t_total']:.1%})", flush=True)
    print(f"    as_tensor              : {_PROF['t_tensor']*1000:.1f} ms "
          f"({_PROF['t_tensor']/_PROF['t_total']:.1%})", flush=True)
    print(f"    model fwd             : {_PROF['t_infer']*1000:.1f} ms "
          f"({_PROF['t_infer']/_PROF['t_total']:.1%})", flush=True)
    print(f"    tolist (Py→Rust)      : {_PROF['t_tolist']*1000:.1f} ms "
          f"({_PROF['t_tolist']/_PROF['t_total']:.1%})", flush=True)

atexit.register(_print_prof)

class MortalEngine:
    def __init__(
        self,
        brain,
        dqn,
        is_oracle,
        version,
        device = None,
        stochastic_latent = False,
        enable_amp = False,
        enable_quick_eval = True,
        enable_rule_based_agari_guard = False,
        name = 'NoName',
        boltzmann_epsilon = 0,
        boltzmann_temp = 1,
        top_p = 1,
    ):
        self.engine_type = 'mortal'
        self.device = device or torch.device('cpu')
        assert isinstance(self.device, torch.device)
        self.brain = brain.to(self.device).eval()
        self.dqn = dqn.to(self.device).eval()
        self.is_oracle = is_oracle
        self.version = version
        self.stochastic_latent = stochastic_latent

        self.enable_amp = enable_amp
        self.enable_quick_eval = enable_quick_eval
        self.enable_rule_based_agari_guard = enable_rule_based_agari_guard
        self.name = name

        self.boltzmann_epsilon = boltzmann_epsilon
        self.boltzmann_temp = boltzmann_temp
        self.top_p = top_p

    def react_batch(self, obs, masks, invisible_obs):
        try:
            with (
                torch.autocast(self.device.type, enabled=self.enable_amp),
                torch.inference_mode(),
            ):
                return self._react_batch(obs, masks, invisible_obs)
        except Exception as ex:
            raise Exception(f'{ex}\n{traceback.format_exc()}')

    def _react_batch(self, obs, masks, invisible_obs):
        if _PROFILE:
            _PROF["calls"] += 1
            _PROF["sum_batch"] += len(obs)
            _profile_sync(self.device)
            t_start = time.perf_counter()
            t = time.perf_counter()
            obs_np = obs if isinstance(obs, np.ndarray) else np.stack(obs, axis=0)
            masks_np = masks if isinstance(masks, np.ndarray) else np.stack(masks, axis=0)
            _PROF["t_stack"] += (t2 := time.perf_counter()) - t
            t = t2
            obs_t = torch.as_tensor(obs_np, device=self.device)
            masks_t = torch.as_tensor(masks_np, device=self.device)
            if invisible_obs is not None:
                invisible_obs = torch.as_tensor(
                    invisible_obs if isinstance(invisible_obs, np.ndarray) else np.stack(invisible_obs, axis=0),
                    device=self.device,
                )
            _profile_sync(self.device)
            _PROF["t_tensor"] += (t2 := time.perf_counter()) - t
            t = t2
            batch_size = obs_t.shape[0]
            match self.version:
                case 1:
                    mu, logsig = self.brain(obs_t, invisible_obs)
                    latent = mu if not self.stochastic_latent else Normal(mu, logsig.exp() + 1e-6).sample()
                    q_out = self.dqn(latent, masks_t)
                case 2 | 3 | 4:
                    phi = self.brain(obs_t)
                    q_out = self.dqn(phi, masks_t)
            _profile_sync(self.device)
            _PROF["t_infer"] += (t2 := time.perf_counter()) - t
            t = t2
            if self.boltzmann_epsilon > 0:
                is_greedy = torch.full((batch_size,), 1-self.boltzmann_epsilon, device=self.device).bernoulli().to(torch.bool)
                logits = (q_out / self.boltzmann_temp).masked_fill(~masks_t, -torch.inf)
                sampled = sample_top_p(logits, self.top_p)
                actions = torch.where(is_greedy, q_out.argmax(-1), sampled)
            else:
                is_greedy = torch.ones(batch_size, dtype=torch.bool, device=self.device)
                actions = q_out.argmax(-1)
            result = (actions.tolist(), q_out.tolist(), masks_t.tolist(), is_greedy.tolist())
            _PROF["t_tolist"] += time.perf_counter() - t
            _PROF["t_total"] += time.perf_counter() - t_start
            return result

        obs = torch.as_tensor(
            obs if isinstance(obs, np.ndarray) else np.stack(obs, axis=0),
            device=self.device,
        )
        masks = torch.as_tensor(
            masks if isinstance(masks, np.ndarray) else np.stack(masks, axis=0),
            device=self.device,
        )
        if invisible_obs is not None:
            invisible_obs = torch.as_tensor(
                invisible_obs if isinstance(invisible_obs, np.ndarray) else np.stack(invisible_obs, axis=0),
                device=self.device,
            )
        batch_size = obs.shape[0]

        match self.version:
            case 1:
                mu, logsig = self.brain(obs, invisible_obs)
                if self.stochastic_latent:
                    latent = Normal(mu, logsig.exp() + 1e-6).sample()
                else:
                    latent = mu
                q_out = self.dqn(latent, masks)
            case 2 | 3 | 4:
                phi = self.brain(obs)
                q_out = self.dqn(phi, masks)

        if self.boltzmann_epsilon > 0:
            is_greedy = torch.full((batch_size,), 1-self.boltzmann_epsilon, device=self.device).bernoulli().to(torch.bool)
            logits = (q_out / self.boltzmann_temp).masked_fill(~masks, -torch.inf)
            sampled = sample_top_p(logits, self.top_p)
            actions = torch.where(is_greedy, q_out.argmax(-1), sampled)
        else:
            is_greedy = torch.ones(batch_size, dtype=torch.bool, device=self.device)
            actions = q_out.argmax(-1)

        return actions.tolist(), q_out.tolist(), masks.tolist(), is_greedy.tolist()

def sample_top_p(logits, p):
    if p >= 1:
        return Categorical(logits=logits).sample()
    if p <= 0:
        return logits.argmax(-1)
    probs = logits.softmax(-1)
    probs_sort, probs_idx = probs.sort(-1, descending=True)
    probs_sum = probs_sort.cumsum(-1)
    mask = probs_sum - probs_sort > p
    probs_sort[mask] = 0.
    sampled = probs_idx.gather(-1, probs_sort.multinomial(1)).squeeze(-1)
    return sampled

class ExampleMjaiLogEngine:
    def __init__(self, name: str):
        self.engine_type = 'mjai-log'
        self.name = name
        self.player_ids = None

    def set_player_ids(self, player_ids: List[int]):
        self.player_ids = player_ids

    def react_batch(self, game_states):
        res = []
        for game_state in game_states:
            game_idx = game_state.game_index
            state = game_state.state
            events_json = game_state.events_json

            events = json.loads(events_json)
            assert events[0]['type'] == 'start_kyoku'

            player_id = self.player_ids[game_idx]
            cans = state.last_cans
            if cans.can_discard:
                tile = state.last_self_tsumo()
                res.append(json.dumps({
                    'type': 'dahai',
                    'actor': player_id,
                    'pai': tile,
                    'tsumogiri': True,
                }))
            else:
                res.append('{"type":"none"}')
        return res

    # They will be executed at specific events. They can be no-op but must be
    # defined.
    def start_game(self, game_idx: int):
        pass
    def end_kyoku(self, game_idx: int):
        pass
    def end_game(self, game_idx: int, scores: List[int]):
        pass
