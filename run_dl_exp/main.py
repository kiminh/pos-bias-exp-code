import torch
import os
import time
import tqdm
import numpy as np
import sys
from sklearn.metrics import roc_auc_score, log_loss
from torch.utils.data import Dataset, DataLoader
import torch.nn.utils.rnn as rnn_utils

from src.dataset.position import PositionDataset
from src.model.lr import LogisticRegression
from src.model.bilr import BiLogisticRegression
from src.model.extlr import ExtLogisticRegression
from src.model.dssm import DSSM
from src.model.bidssm import BiDSSM
from src.model.extdssm import ExtDSSM
from src.model.ffm import FFM
from src.model.biffm import BiFFM
from src.model.extffm import ExtFFM
from src.model.xdfm import ExtremeDeepFactorizationMachineModel
from src.model.bixdfm import BiExtremeDeepFactorizationMachineModel
from src.model.extxdfm import ExtExtremeDeepFactorizationMachineModel
from src.model.dfm import DeepFactorizationMachineModel
from src.model.dcn import DeepCrossNetworkModel
from utility import recommend


class CombDataset(Dataset):
    def __init__(self, dataset1, dataset2, sim=False):
        assert len(dataset1) == len(dataset2), "Can't combine 2 datasets for their different length!"
        self.dataset1 = dataset1 # datasets should be sorted!
        self.dataset2 = dataset2
        self.sim = sim

    def __getitem__(self, index):
        if self.sim:
            x1 = self.dataset1[index]
            x2 = self.dataset2[index]
        else:
            x1 = self.dataset1[index]
            index = (np.random.randint(len(self.dataset1)) + index) // len(self.dataset1) 
            x2 = self.dataset2[int(index)]
        return x1, x2

    def __len__(self):
        return len(self.dataset1)

def merge_dims(t):
    return t.view(tuple(-1 if i==0 else _s for i, _s in enumerate(t.size()[1:])))

class data_prefetcher():
    def __init__(self, loader, device):
        #self.device = device
        self.device = None
        self.loader = iter(loader)
        self.stream = torch.cuda.Stream()
        self.preload()

    #@profile
    def preload(self):
        try:
            self.context, self.item, self.target, self.pos, _, self.value = next(self.loader)
        except StopIteration:
            self.context, self.item, self.target, self.pos, self.value = None, None, None, None, None
            return
        with torch.cuda.stream(self.stream):
            self.context = merge_dims(self.context).cuda(device=self.device, non_blocking=True) 
            self.item = merge_dims(self.item).cuda(device=self.device, non_blocking=True)
            self.target = merge_dims(self.target).cuda(device=self.device, non_blocking=True) 
            self.pos = merge_dims(self.pos).cuda(device=self.device, non_blocking=True) 
            self.value = merge_dims(self.value).cuda(device=self.device, non_blocking=True) 
            
    def next(self):
        torch.cuda.current_stream().wait_stream(self.stream)
        context = self.context 
        item = self.item
        target = self.target 
        pos = self.pos 
        value = self.value 
        self.preload()

        return context, item, target, pos, None, value

def mkdir_if_not_exist(path):
    if not os.path.exists(path):
        os.makedirs(path)

def hook(self, input, output):
    tmp = torch.sigmoid(output.data).flatten().tolist()
    ratio = [tmp[0]]
    for i in range(1, 10):
        ratio.append(tmp[i+1]/tmp[i])
    print(tmp)
    print(ratio, np.mean(ratio[1:]))

def get_dataset(name, path, data_prefix, rebuild_cache, max_dim=-1, read_flag=0):
    if name == 'pos':
        return PositionDataset(path, data_prefix, rebuild_cache, max_dim, read_flag)
    else:
        raise ValueError('unknown dataset name: ' + name)

def get_model(name, dataset, embed_dim):
    """
    Hyperparameters are empirically determined, not opitmized.
    """
    input_dims = dataset.max_dim
    max_ctx_num = dataset.max_ctx_num
    max_item_num = dataset.max_item_num
    #if name == 'lr':
    #    return LogisticRegression(input_dims)
    #elif name == 'bilr':
    #    return BiLogisticRegression(input_dims, dataset.pos_num)
    #elif name == 'extlr':
    #    return ExtLogisticRegression(input_dims, dataset.pos_num)
    #elif name == 'dssm':
    #    return DSSM(input_dims, embed_dim)
    #elif name == 'bidssm':
    #    return BiDSSM(input_dims, embed_dim, dataset.pos_num)
    #elif name == 'extdssm':
    #    return ExtDSSM(input_dims, embed_dim, dataset.pos_num)
    #elif name == 'xdfm':
    #    return ExtremeDeepFactorizationMachineModel(input_dims, embed_dim=embed_dim*2, mlp_dims=(embed_dim, embed_dim), dropout=0.2, cross_layer_sizes=(embed_dim, embed_dim), split_half=True)
    #elif name == 'bixdfm':
    #    return BiExtremeDeepFactorizationMachineModel(input_dims, dataset.pos_num, embed_dim=embed_dim*2, mlp_dims=(embed_dim, embed_dim), dropout=0.2, cross_layer_sizes=(embed_dim, embed_dim), split_half=True)
    #elif name == 'extxdfm':
    #    return ExtExtremeDeepFactorizationMachineModel(input_dims, dataset.pos_num, embed_dim=embed_dim*2, mlp_dims=(embed_dim, embed_dim), dropout=0.2, cross_layer_sizes=(embed_dim, embed_dim), split_half=True)
    #elif name == 'dfm':
    #    return DeepFactorizationMachineModel(input_dims, embed_dim=embed_dim, mlp_dims=(embed_dim, embed_dim), dropout=0.2)
    if name == 'ffm':
        return FFM(input_dims, embed_dim)
    elif name == 'biffm':
        return BiFFM(input_dims, dataset.pos_num, embed_dim)
    elif name == 'extffm':
        return ExtFFM(input_dims, dataset.pos_num, embed_dim)
    elif name == 'dcn':
        return DeepCrossNetworkModel(input_dims, embed_dim=embed_dim, feats_num=max_ctx_num + max_item_num, num_layers=3, mlp_dims=(embed_dim, embed_dim), dropout=0.2)
    else:
        raise ValueError('unknown model name: ' + name)

#@profile
def model_helper(data_pack, model, model_name, device, mode='wps'):
    context, item, target, pos, _, value = data_pack
    #context, item, target, value = context.to(device, torch.long), item.to(device, torch.long), target.to(device, torch.float), value.to(device, torch.float)
    context, item, target, value = merge_dims(context.to(device, non_blocking=True)), merge_dims(item.to(device, non_blocking=True)), merge_dims(target.to(device, non_blocking=True)), merge_dims(value.to(device, non_blocking=True))
    if model_name.startswith(('bi', 'ext')):
        #pos = pos.to(device, torch.long)
        if mode == 'wops':
            pos = torch.zeros_like(pos)
        elif mode == 'wps':
            pass
        else:
            raise(ValueError, "model_helper's mode %s is wrong!"%mode)
        y = model(context, item, pos, value)
    else:
        y = model(context, item, value)
    return y, target

#@profile
def train(model, optimizer, data_loader, criterion, device, model_name, log_interval=200):
    model.train()
    total_loss = 0
    pbar = tqdm.tqdm(data_loader, smoothing=0, mininterval=1.0, ncols=100)
    for i, data_pack in enumerate(pbar):

    #prefetcher = data_prefetcher(data_loader, device)
    #pbar = tqdm.tqdm(total=len(data_loader), smoothing=0, mininterval=1.0, ncols=100)
    #data_pack = prefetcher.next()
    #i = 0
    #while data_pack[0] is not None:

        y, target = model_helper(data_pack, model, model_name, device, 'wps')
        loss = criterion(y, target.float())
        model.zero_grad()
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
        if (i + 1) % log_interval == 0:
            closs = total_loss/log_interval
            pbar.set_postfix(loss=closs)
            total_loss = 0
    #    data_pack = prefetcher.next()
    #    i += 1
    #    pbar.update(1)
    #pbar.close()
    return loss.item()

def imp_train(omega, model, imp_model, optimizer, data_loader, criterion, imp_criterion, device, model_name, log_interval=200):
    model.train()
    imp_model.eval()
    total_loss1 = 0
    total_loss2 = 0
    total_loss = 0
    pbar = tqdm.tqdm(data_loader, smoothing=0, mininterval=1.0, ncols=100)
    for i, (data_pack, imp_data_pack) in enumerate(pbar):

    #prefetcher = data_prefetcher(data_loader, device)
    #imp_prefetcher = data_prefetcher(imp_data_loader, device)
    #data_pack = prefetcher.next()
    #imp_data_pack = imp_prefetcher.next()
    #pbar = tqdm.tqdm(total=len(data_loader), smoothing=0, mininterval=1.0, ncols=100)
    #i = 0
    #while data_pack[0] is not None:

        y, target = model_helper(data_pack, model, model_name, device, 'wps')
        imp_y, _ = model_helper(imp_data_pack, imp_model, model_name, device, 'wps')
        hat_y, _ = model_helper(imp_data_pack, model, model_name, device, 'wps')

        loss1 = criterion(y, target.float())
        loss2 = imp_criterion(hat_y, imp_y)
        loss = loss1 + omega*loss2

        model.zero_grad()
        loss.backward()
        optimizer.step()

        total_loss1 += loss1.item()
        total_loss2 += loss2.item()
        total_loss += loss.item()
        if (i + 1) % log_interval == 0:
            total_loss1 /= log_interval
            total_loss2 /= log_interval
            total_loss /= log_interval
            pbar.set_postfix(nll='%.4f'%total_loss1, mse='%.4f'%total_loss2, loss='%.4f'%total_loss)
            total1_loss = 0
            total2_loss = 0
            total_loss = 0

    #    data_pack = prefetcher.next()
    #    imp_data_pack = imp_prefetcher.next()
    #    i += 1
    #    pbar.update(1)
    #pbar.close()
    return loss.item()

def test(model, data_loader, device, model_name, mode='wps'):
    model.eval()
    targets, predicts = list(), list()
    with torch.no_grad():
        for i, data_pack in enumerate(tqdm.tqdm(data_loader, smoothing=0, mininterval=1.0, ncols=100)):

        #prefetcher = data_prefetcher(data_loader, device)
        #pbar = tqdm.tqdm(total=len(data_loader), smoothing=0, mininterval=1.0, ncols=100)
        #data_pack = prefetcher.next()
        #i = 0
        #while data_pack[0] is not None:

            y, target = model_helper(data_pack, model, model_name, device, 'wps')
            targets.extend(torch.flatten(target.to(torch.int)).tolist())
            predicts.extend(torch.sigmoid(torch.flatten(y)).tolist())

        #    data_pack = prefetcher.next()
        #    i += 1
        #    pbar.update(1)
        #pbar.close()
    return roc_auc_score(targets, predicts), log_loss(targets, predicts)


def pred(model, data_loader, device, model_name, item_num):
    num_of_pos = 10
    res = np.empty(data_loader.batch_size//item_num*num_of_pos, dtype=np.int32)
    rngs = [np.random.RandomState(seed) for seed in [0,3,4,5,6]]
    bids = np.empty((len(rngs), item_num)) 
    for i, rng in enumerate(rngs):
        bids[i, :] = rng.gamma(10, 0.4, item_num)
    bids = torch.tensor(bids).to(device)

    model.eval()
    targets, predicts = list(), list()
    with torch.no_grad():
        fs = list()
        for j in range(len(rngs)):
            fs.append(open(os.path.join('tmp.pred.%d'%j), 'w'))
        for i, tmp in enumerate(tqdm.tqdm(data_loader, smoothing=0, mininterval=1.0, ncols=100)):
            y, target = model_helper(tmp, model, model_name, device, mode='wops')
            num_of_user = y.size()[0]//item_num
            for j in range(len(rngs)):
                fp = fs[j]
                out = y*(bids[j, :].repeat(num_of_user))
                recommend.get_top_k_by_greedy(out.cpu().numpy(), num_of_user, item_num, num_of_pos, res[:num_of_user*num_of_pos])
                _res = res[:num_of_user*num_of_pos].reshape(num_of_user, num_of_pos)
                for r in range(num_of_user):
                    tmp = ['%d:%.4f:%0.4f'%(ad, y[r*item_num+ad], bids[j, ad]) for ad in _res[r, :]]
                    fp.write('%s\n'%(' '.join(tmp)))


def main(dataset_name,
         train_part,
         valid_part,
         imp_part,
         dataset_path,
         flag,
         model_name,
         model_path,
         imp_model_path,
         epoch,
         learning_rate,
         batch_size,
         embed_dim,
         weight_decay,
         omega,
         device,
         save_dir,
         ps):
    mkdir_if_not_exist(save_dir)
    #device = torch.device(device)
    device = torch.device('cuda') 
    if flag == 'train':
        train_dataset = get_dataset(dataset_name, dataset_path, train_part, False)
        valid_dataset = get_dataset(dataset_name, dataset_path, valid_part, False, train_dataset.get_max_dim() - 1)

        train_data_loader = DataLoader(train_dataset, batch_size=batch_size, num_workers=8, pin_memory=True, shuffle=True)
        valid_data_loader = DataLoader(valid_dataset, batch_size=batch_size, num_workers=8, pin_memory=True)
        log_interval = len(train_data_loader)//10

        model = get_model(model_name, train_dataset, embed_dim)#.to(device)
        model = torch.nn.parallel.DataParallel(model).cuda()
        criterion = torch.nn.BCEWithLogitsLoss()
        optimizer = torch.optim.Adam(params=model.parameters(), lr=learning_rate, weight_decay=weight_decay)
        model_file_name = '_'.join([model_name, 'lr-'+str(learning_rate), 'l2-'+str(weight_decay), 'bs-'+str(batch_size), 'k-'+str(embed_dim), train_part])
        with open(os.path.join(save_dir, model_file_name+'.log'), 'w') as log:
            for epoch_i in range(epoch):
                tr_logloss = train(model, optimizer, train_data_loader, criterion, device, model_name, log_interval)
                torch.cuda.synchronize()
                va_auc, va_logloss = test(model, valid_data_loader, device, model_name, ps)
                print('epoch:%d\ttr_logloss:%.6f\tva_auc:%.6f\tva_logloss:%.6f'%(epoch_i, tr_logloss, va_auc, va_logloss))
                log.write('epoch:%d\ttr_logloss:%.6f\tva_auc:%.6f\tva_logloss:%.6f\n'%(epoch_i, tr_logloss, va_auc, va_logloss))
        torch.save(model, f'{save_dir}/{model_file_name}.pt')
    elif flag == 'imp_train':
        st_dataset = get_dataset(dataset_name, dataset_path, imp_part, False)
        train_dataset = get_dataset(dataset_name, dataset_path, train_part, False, st_dataset.get_max_dim()-1)
        imp_train_dataset = get_dataset(dataset_name, dataset_path, train_part, False, st_dataset.get_max_dim()-1, 3)
        valid_dataset = get_dataset(dataset_name, dataset_path, valid_part, False, st_dataset.get_max_dim()-1)
        sim_train_dataset = CombDataset(train_dataset, imp_train_dataset)

        train_data_loader = DataLoader(sim_train_dataset, batch_size=batch_size, num_workers=8, pin_memory=True, shuffle=True)
        #imp_train_data_loader = DataLoader(imp_train_dataset, batch_size=imp_bs, num_workers=8, pin_memory=True, shuffle=True)
        valid_data_loader = DataLoader(valid_dataset, batch_size=batch_size, num_workers=8, pin_memory=True)
        log_interval = len(train_data_loader)//10

        model = get_model(model_name, st_dataset, embed_dim).to(device)
        imp_model = torch.load(imp_model_path).to(device)

        criterion = torch.nn.BCEWithLogitsLoss()
        imp_criterion = torch.nn.MSELoss()  
        optimizer = torch.optim.Adam(params=model.parameters(), lr=learning_rate, weight_decay=weight_decay)
        model_file_name = '_'.join([model_name, 'lr-'+str(learning_rate), 'l2-'+str(weight_decay), 'bs-'+str(batch_size), 'k-'+str(embed_dim), 'o-'+str(omega), train_part])
        with open(os.path.join(save_dir, model_file_name+'.log'), 'w') as log:
            for epoch_i in range(epoch):
                tr_logloss = imp_train(omega, model, imp_model, optimizer, train_data_loader, criterion, imp_criterion, device, model_name, log_interval)
                va_auc, va_logloss = test(model, valid_data_loader, device, model_name, ps)
                print('epoch:%d\ttr_logloss:%.6f\tva_auc:%.6f\tva_logloss:%.6f'%(epoch_i, tr_logloss, va_auc, va_logloss))
                log.write('epoch:%d\ttr_logloss:%.6f\tva_auc:%.6f\tva_logloss:%.6f\n'%(epoch_i, tr_logloss, va_auc, va_logloss))
        torch.save(model, f'{save_dir}/{model_file_name}.pt')
    elif flag == 'test':
        train_dataset = get_dataset(dataset_name, dataset_path, train_part, False)
        valid_dataset = get_dataset(dataset_name, dataset_path, valid_part, False, train_dataset.get_max_dim() - 1)
        valid_data_loader = DataLoader(valid_dataset, batch_size=batch_size, num_workers=8, pin_memory=True)
        model = torch.load(model_path, map_location=device)
        va_auc, va_logloss = test(model, valid_data_loader, device, model_name, ps)
        print("model logloss auc")
        print("%s %.6f %.6f"%(model_name, va_logloss, va_auc))
    elif flag == 'pred':
        train_dataset = get_dataset(dataset_name, dataset_path, train_part, False)
        valid_dataset = get_dataset(dataset_name, dataset_path, valid_part, False, train_dataset.get_max_dim() - 1, 1)
        item_num = valid_dataset.get_item_num()
        refine_batch_size = int(batch_size//item_num*item_num)  # batch_size should be a multiple of item_num 
        valid_data_loader = DataLoader(valid_dataset, batch_size=refine_batch_size, num_workers=8, pin_memory=True)
        model = torch.load(model_path).to(device)
        pred(model, valid_data_loader, device, model_name, item_num)
    else:
        raise ValueError('Flag should be "train"/"imp_train"/"pred"/"test"!')



if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset_name', default='pos')
    parser.add_argument('--train_part', default='tr')
    parser.add_argument('--valid_part', default='va')
    parser.add_argument('--imp_part', default='st_tr')
    parser.add_argument('--dataset_path', help='the path that contains item.svm, va.svm, tr.svm trva.svm')
    parser.add_argument('--flag', default='train')
    parser.add_argument('--model_name', default='dssm')
    parser.add_argument('--model_path', default='', help='the path of model file')
    parser.add_argument('--imp_model_path', default='', help='the path of imp model file')
    parser.add_argument('--epoch', type=float, default=30.)
    parser.add_argument('--learning_rate', type=float, default=0.001)
    parser.add_argument('--batch_size', type=float, default=8192.)
    parser.add_argument('--embed_dim', type=float, default=16.)
    parser.add_argument('--weight_decay', type=float, default=1e-6)
    parser.add_argument('--omega', type=float, default=1)
    parser.add_argument('--device', default='cuda:0', help='format like "cuda:0" or "cpu"')
    parser.add_argument('--save_dir', default='logs')
    parser.add_argument('--ps', default='wps')
    args = parser.parse_args()
    main(args.dataset_name,
         args.train_part,
         args.valid_part,
         args.imp_part,
         args.dataset_path,
         args.flag,
         args.model_name,
         args.model_path,
         args.imp_model_path,
         int(args.epoch),
         args.learning_rate,
         int(args.batch_size),
         int(args.embed_dim),
         args.weight_decay,
         args.omega,
         args.device,
         args.save_dir,
         args.ps)

