"""
@file   : model.py
@time   : 2024-07-19
"""
import torch
from torch import nn


class Expert(nn.Module):
    def __init__(self, input_size, output_size, hidden_size):
        super(Expert, self).__init__()
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.fc2 = nn.Linear(hidden_size, output_size)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(0.3)

    def forward(self, x):
        out = self.fc1(x)
        out = self.relu(out)
        out = self.dropout(out)
        out = self.fc2(out)
        return out


class Tower(nn.Module):
    def __init__(self, input_size, output_size, hidden_size):
        super(Tower, self).__init__()
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.fc2 = nn.Linear(hidden_size, output_size)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(0.4)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        out = self.fc1(x)
        out = self.relu(out)
        out = self.dropout(out)
        out = self.fc2(out)
        out = self.sigmoid(out)
        return out


class MMOE(nn.Module):
    def __init__(self, user_feature_dict, item_feature_dict, emb_dim=128, num_experts=6, experts_out=16, experts_hidden=32, towers_hidden=8, expert_activation=None, num_task=2):
        super(MMOE, self).__init__()
        self.user_feature_dict = user_feature_dict
        self.item_feature_dict = item_feature_dict
        self.expert_activation = expert_activation
        self.num_task = num_task

        # 1. embedding模块
        user_cate_feature_nums, item_cate_feature_nums = 0, 0
        # 用户侧embedding
        for user_cate, num in self.user_feature_dict.items():
            if num[0] > 1:
                user_cate_feature_nums += 1
                setattr(self, user_cate, nn.Embedding(num[0], emb_dim))
        # item侧embedding
        for item_cate, num in self.item_feature_dict.items():
            if num[0] > 1:
                item_cate_feature_nums += 1
                setattr(self, item_cate, nn.Embedding(num[0], emb_dim))

        # user embedding + item embedding
        self.input_size = emb_dim * (user_cate_feature_nums + item_cate_feature_nums) + (
                len(self.user_feature_dict) - user_cate_feature_nums) + (
                len(self.item_feature_dict) - item_cate_feature_nums)
        # print(self.input_size)   # 454

        self.num_experts = num_experts
        self.experts_out = experts_out
        self.experts_hidden = experts_hidden
        self.towers_hidden = towers_hidden
        self.tasks = num_task

        self.softmax = nn.Softmax(dim=1)

        self.experts = nn.ModuleList([Expert(self.input_size, self.experts_out, self.experts_hidden)
                                      for i in range(self.num_experts)])
        self.w_gates = nn.ParameterList([nn.Parameter(torch.randn(self.input_size, num_experts), requires_grad=True)
                                         for i in range(self.tasks)])
        self.towers = nn.ModuleList([Tower(self.experts_out, 1, self.towers_hidden)
                                     for i in range(self.tasks)])

    def forward(self, x):
        user_embed_list, item_embed_list = list(), list()
        for user_feature, num in self.user_feature_dict.items():
            if num[0] > 1:
                user_embed_list.append(getattr(self, user_feature)(x[:, num[1]].long()))
            else:
                user_embed_list.append(x[:, num[1]].unsqueeze(1))

        for item_feature, num in self.item_feature_dict.items():
            if num[0] > 1:
                item_embed_list.append(getattr(self, item_feature)(x[:, num[1]].long()))
            else:
                item_embed_list.append(x[:, num[1]].unsqueeze(1))

        # embedding 融合
        user_embed = torch.cat(user_embed_list, axis=1)
        item_embed = torch.cat(item_embed_list, axis=1)
        # print(user_embed.size())    # torch.Size([32, 259])
        # print(item_embed.size())    # torch.Size([32, 195])

        x = torch.cat([user_embed, item_embed], axis=1).float()  # batch * hidden_size
        # print(x.size())   # torch.Size([32, 454])

        experts_o = [e(x) for e in self.experts]
        experts_o_tensor = torch.stack(experts_o)
        # print(experts_o_tensor.size())   # torch.Size([6, 32, 16])  # expert_num, batch_size, experts_out

        # for g in self.w_gates:
        #     print(g.size())    # torch.Size([454, 6])
        #     print(x.size())    # torch.Size([32, 454])
        gates_o = [self.softmax(x @ g) for g in self.w_gates]
        # print(gates_o[0].size())   # torch.Size([32, 6])

        tower_input = [g.t().unsqueeze(2).expand(-1, -1, self.experts_out) * experts_o_tensor for g in gates_o]
        # print(tower_input[0].size())   # torch.Size([6, 32, 16])
        tower_input = [torch.sum(ti, dim=0) for ti in tower_input]
        # print(tower_input[0].size())    # torch.Size([32, 16])

        final_output = [t(ti) for t, ti in zip(self.towers, tower_input)]
        return final_output