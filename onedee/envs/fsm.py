import numpy as np
import torch
from rebar import arrdict, dotdict
from .. import spaces

__all__ = []

class FSMEnv:

    def __init__(self, states, n_envs, device='cuda'):
        indices = {n: i for i, n in enumerate(states)}
        (d_obs,) = {len(o) for t, o, ars in states.values()}
        (n_actions,) = {len(ars) for t, o, ars in states.values()}

        self.action_space = spaces.MultiDiscrete(1, n_actions)
        self.observation_space = spaces.MultiVector(1, d_obs) if d_obs else spaces.MultiEmpty()

        self.n_envs = n_envs
        self.n_agents = 1
        self.device = torch.device(device)
        self._token = torch.zeros(n_envs, dtype=torch.long)

        term, obs, trans, reward = [], [], [], []
        for t, o, ars in states.values():
            term.append(t)
            obs.append(o)
            trans.append([indices[s] for s, r in ars])
            reward.append([r for s, r in ars])
        self._term = torch.as_tensor(term, dtype=torch.bool, device=self.device)
        self._obs = torch.as_tensor(obs, dtype=torch.float, device=self.device)
        self._trans = torch.as_tensor(trans, dtype=torch.int, device=self.device)
        self._reward = torch.as_tensor(reward, dtype=torch.float, device=self.device)

    def reset(self):
        self._token[:] = 0
        return arrdict(
            obs=self._obs[self._token, None],
            reward=torch.zeros((self.n_envs,), dtype=torch.float, device=self.device),
            reset=torch.ones((self.n_envs), dtype=torch.bool, device=self.device),
            terminal=torch.ones((self.n_envs), dtype=torch.bool, device=self.device))

    def step(self, decision):
        actions = decision.actions[:, 0]
        reward = self._reward[self._token, actions]
        self._token[:] = self._trans[self._token, actions].long()
        
        reset = self._term[self._token]
        self._token[reset] = 0

        return arrdict(
            obs=self._obs[self._token, None],
            reward=reward,
            reset=reset,
            terminal=reset)

    def __repr__(self):
        s, a = self._trans.shape
        return f'{type(self).__name__}({s}s{a}a)' 

    def __str__(self):
        return repr(self)


class State:

    def __init__(self, name, builder):
        self._name = name
        self._builder = builder

    def to(self, state, action, reward=0., prob=1.):
        self._builder._trans.append(dotdict(
            prev=self._name, 
            action=action, 
            next=state, 
            reward=reward, 
            prob=prob))
        return self

class Builder:

    def __init__(self):
        self._obs = []
        self._trans = []

    def state(self, name, obs):
        if isinstance(obs, (int, float, bool)):
            obs = (obs,)
        self._obs.append(dotdict(state=name, obs=obs))
        return State(name, self)
    
    def build(self):
        states = (
            {x.state for x in self._obs} | 
            {x.prev for x in self._trans} | 
            {x.next for x in self._trans})

        actions = {x.action for x in self._trans}
        assert max(actions) == len(actions)-1, 'Action set isn\'t contiguous'
        
        indices = {s: i for i, s in enumerate(states)}

        n_states = len(states)
        n_actions = len(actions)
        (d_obs,) = {len(x.obs) for x in self._obs}

        obs = torch.full((n_states, d_obs), np.nan)
        for x in self._obs:
            obs[indices[x.state]] = torch.as_tensor(x.obs)

        trans = torch.full((n_states, n_actions, n_states), 0.)
        reward = torch.full((n_states, n_actions), 0.)
        for x in self._trans:
            trans[indices[x.prev], x.action, indices[x.next]] = x.prob
            reward[indices[x.prev], x.action] = x.reward
        
        terminal = trans.sum(-1).max(-1).values == 0
        origin = (trans.sum(0).max(1).values == 0)

        return dotdict(obs=obs, trans=trans, terminal=terminal, origin=origin, indices=indices)


def fsm(f):

    def init(self, *args, n_envs=1, **kwargs):
        fsm = f(*args, **kwargs)
        super(self.__class__, self).__init__(fsm=fsm, n_envs=n_envs)

    name = f.__name__
    __all__.append(name)
    return type(name, (FSMEnv,), {'__init__': init})

@fsm
def UnitReward():
    b = Builder()
    b.state('start', ()).to('start', 0, 1.)
    return b.build()

@fsm
def Chain(n):
    assert n >= 2, 'Need the number of states to be at least 1'
    states = {}
    for i in range(n-2):
        states[i] = (False, (i/n,), [(i+1, 0.)])
    if n > 1:
        states[n-2] = (False, (n-2/n,), [(n-1, 1.)])
    states[n-1] = (True, (n-1/n,), [(n-1, 0.)])
    return states

# @fsm
# def CoinFlip():
#     return {
#         'start': (False, (0.,))
#         'heads': (False, (+1.,), [('end', +1.)]),
#         'tails': (False, (-1.,), [('end', -1.)]),
#         'end': (True, (0.,), [('end', 0.)])}