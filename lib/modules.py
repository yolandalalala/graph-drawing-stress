from .imports import *
from .functions import *

    
class SoftAdaptController:
    def __init__(self, criteria, *, gamma=None, warmup=2, exploit_rate=0, tau=0.95, beta=1):
        assert warmup >= 2
        assert beta >= 0
        if gamma is None:
            gamma = np.ones(len(criteria))
        self.set_gamma(gamma)
        self.criteria = criteria
        self.warmup = warmup
        self.exploit_rate = exploit_rate
        self.tau = tau
        self.beta = beta
        self.history = []
        self.policy = None
        self.last_policy = None
        self.weights = None
        self.last_weights = None
        self.step()
        
    def __len__(self):
        return len(self.history)
        
    @staticmethod
    def _exp_smooth(array, tau):
        array = np.array(array)
        for i in range(1, len(array)):
            array[i] = array[i-1] * tau + array[i] * (1 - tau)
        return array
        
    @staticmethod
    def _soft_adapt(losses, gamma, beta, eps=1e-5):
        roc = np.diff(losses, axis=0) / (losses[:-1] + eps)
        normalized_roc = roc / (np.abs(roc).sum(axis=1)[:, None] + eps)
        weight = np.array(gamma)[None, :] * np.exp(beta * normalized_roc) / (losses[1:] + eps)
        return weight / (weight.sum(axis=1)[:, None] + eps)

    def step(self, loss_components=None):
        if loss_components is not None:
            self.history.append(loss_components)
        if len(self) >= self.warmup:
            smoothed = self._exp_smooth(self.history, tau=self.tau)
        else:
            smoothed = np.zeros([2, len(self.criteria)])
        self.last_policy = self.policy
        self.policy = -1 if random.random() < self.exploit_rate else 1
        self.last_weights = self.weights
        self.weights = self._soft_adapt(smoothed, gamma=self.gamma, beta=self.policy*self.beta)[-1]
        self.criteria.update_weights(self.weights)
    
    @property
    def n_criteria(self):
        return len(self.criteria)
    
    def set_gamma(self, gamma):
        self.gamma = np.array(gamma) / np.sum(gamma)
    
    def get_weights(self):
        return self.weights
    
    def get_last_weights(self):
        return self.last_weights
    
    def get_policy(self):
        return self.policy
    
    def get_last_policy(self):
        return self.last_policy
    
    
class CompositeLoss(nn.Module):
    def __init__(self, criteria, weights=None):
        super().__init__()
        self.weights = np.ones(len(criteria)) if weights is None else np.array(weights)
        self.criteria = criteria
        
    def __len__(self):
        return len(self.criteria)
        
    def update_weights(self, weights):
        self.weights = np.array(weights)
        
    def forward(self, *args, return_components=False, **kwargs):
        losses = []
        components = []
        for criterion, weight in zip(self.criteria, self.weights):
            loss = criterion(*args, **kwargs)
            losses += [loss.mul(weight)]
            components += [loss]
        result = (sum(losses),)
        if return_components:
            result += (components,)
        return result[0] if len(result) == 1 else result
        
        
class GNNLayer(nn.Module):
    def __init__(self, in_vfeat, out_vfeat, in_efeat, edge_net=None, bn=False, act=False, dp=None, aggr='mean'):
        super().__init__()
        self.enet = nn.Linear(in_efeat, in_vfeat * out_vfeat) if edge_net is None else edge_net
        self.conv = gnn.NNConv(in_vfeat, out_vfeat, self.enet, aggr=aggr)
        self.bn = gnn.BatchNorm(out_vfeat) if bn else nn.Identity()
        self.act = nn.LeakyReLU() if act else nn.Identity()
        self.dp = nn.Dropout(dp) if dp is not None else nn.Identity()
        
    def forward(self, v, e, data):
        return self.dp(self.act(self.bn(self.conv(v, data.edge_index, e))))


class GNNBlock(nn.Module):
    def __init__(self, feat_dims, 
                 efeat_hid_dims=[], 
                 efeat_hid_acts=nn.LeakyReLU,
                 bn=False, 
                 act=True, 
                 dp=None, 
                 extra_efeat='skip', 
                 euclidian=False, 
                 direction=False, 
                 n_weights=0,
                 residual=False):
        '''
        extra_efeat: {'skip', 'first', 'prev'}
        '''
        super().__init__()
        self.extra_efeat = extra_efeat
        self.euclidian = euclidian
        self.direction = direction
        self.n_weights = n_weights
        self.residual = residual
        self.gnn = nn.ModuleList()
        self.n_layers = len(feat_dims) - 1
        
        for idx, (in_feat, out_feat) in enumerate(zip(feat_dims[:-1], feat_dims[1:])):
            direction_dim = feat_dims[idx] if self.extra_efeat == 'prev' else feat_dims[0]
            in_efeat_dim = 2
            if self.extra_efeat != 'first': 
                in_efeat_dim += self.euclidian + self.direction * direction_dim + self.n_weights
            edge_net = nn.Sequential(*chain.from_iterable(
                [nn.Linear(idim, odim),
                 nn.BatchNorm1d(odim),
                 act()]
                for idim, odim, act in zip([in_efeat_dim] + efeat_hid_dims,
                                           efeat_hid_dims + [in_feat * out_feat],
                                           [efeat_hid_acts] * len(efeat_hid_dims) + [nn.Tanh])
            ))
            self.gnn.append(GNNLayer(in_vfeat=in_feat, 
                                     out_vfeat=out_feat, 
                                     in_efeat=in_efeat_dim, 
                                     edge_net=edge_net,
                                     bn=bn, 
                                     act=act, 
                                     dp=dp))
        
    def _get_edge_feat(self, pos, data, euclidian=False, direction=False, weights=None):
        e = data.edge_attr
        if euclidian or direction:
            start_pos, end_pos = get_full_edges(pos, data)
            u, d = l2_normalize(end_pos - start_pos, return_norm=True)
            if euclidian:
                e = torch.cat([e, u], dim=1)
            if direction:
                e = torch.cat([e, d], dim=1)
        if weights is not None:
            w = weights.repeat(len(e), 1)
            e = torch.cat([e, w], dim=1)
        return e
        
    def forward(self, v, data, weights=None):
        vres = v
        for layer in range(self.n_layers):
            vsrc = v if self.euclidian == 'prev' else vres
            get_extra = not (self.extra_efeat == 'first' and layer != 0)
            
            e = self._get_edge_feat(vsrc, data, 
                                    euclidian=self.euclidian and get_extra, 
                                    direction=self.direction and get_extra,
                                    weights=weights if get_extra and self.n_weights > 0 else None)
            v = self.gnn[layer](v, e, data)
        return v + vres if self.residual else v
        
        
class Model(nn.Module):
    def __init__(self, num_blocks=9, n_weights=0):
        super().__init__()
        
        self.in_blocks = nn.ModuleList([
            GNNBlock(feat_dims=[2, 8, 8], bn=True, dp=0.2)
        ])
        self.hid_blocks = nn.ModuleList([
            GNNBlock(feat_dims=[8, 8, 8, 8], 
                     efeat_hid_dims=[16],
                     bn=True, 
                     act=True,
                     dp=0.2, 
                     extra_efeat='skip', 
                     euclidian=True, 
                     direction=True, 
                     n_weights=n_weights,
                     residual=True)
            for _ in range(num_blocks)
        ])
        self.out_blocks = nn.ModuleList([
            GNNBlock(feat_dims=[8, 8], bn=True),
            GNNBlock(feat_dims=[8, 2], act=False)
        ])

    def forward(self, data, weights=None, output_hidden=False, numpy=False, with_initial_pos=False):
        v = data.x if with_initial_pos else generate_rand_pos(len(data.x)).to(data.x.device)       
        v = rescale_with_minimized_stress(v, data)
          
        hidden = []
        for block in chain(self.in_blocks, 
                           self.hid_blocks, 
                           self.out_blocks):
            v = block(v, data, weights)
            if output_hidden:
                hidden.append(v.detach().cpu().numpy() if numpy else v)
        if not output_hidden:
            vout = v.detach().cpu().numpy() if numpy else v
        
        return hidden if output_hidden else vout