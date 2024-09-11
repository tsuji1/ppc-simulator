import os
import subprocess
import copy
import concurrent.futures
import json
import time
import logging
from datetime import datetime
from models.MultiLayerCacheExclusive import MultiLayerCacheExclusive,AnalysisResults
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt

import heapq
import numpy as np
#
def _make_join(refbits,cache_capacity):
    refbits_string = "-".join([str(i) for i in refbits])
    cache_capacity_string = "-".join([str(i) for i in cache_capacity])
    return f"{refbits_string}_{cache_capacity_string}"
def make_tmp_file_path(base_dir, refbits, cache_capacity):
    joined = _make_join(refbits,cache_capacity)
    p = os.path.join(base_dir , f'tmp_{joined}.json')
    return p


def aggregate_result(first_refbits,last_refbits,cache_capacity,force_update=False):
    
    json_result_data = []
    parsed_result_data = [] 
    tmp_dir = '../result/tmp_results'
    
    cache_num = len(cache_capacity)
    cache_capacity_string = "-".join([str(i) for i in cache_capacity])
    dst_file_path = f'../result/multilayer_{cache_num}layer_{cache_capacity_string}.json'

    if (not os.path.exists(dst_file_path) or force_update):
        for refbits_layer2 in range(first_refbits,last_refbits+1): # layer 2
            if(cache_capacity[0] == 1 and refbits_layer2 != 24):
                # 1bitのキャッシュは24bitのrefbitsの時だけ
                continue
                
            for refbits_layer3 in range(first_refbits, refbits_layer2):
                refbits = [32,refbits_layer2,refbits_layer3]
                refbits_string = "-".join([str(i) for i in refbits])
                tmp_dir_refbits = os.path.join(tmp_dir, f'{refbits_string}')
                partial_result_file = make_tmp_file_path(tmp_dir_refbits,refbits,cache_capacity)
                with open(partial_result_file, 'r') as file:
                    _json_data = json.load(file)
                    json_result_data.append(_json_data)
                if(l1c==1):
                    print(_json_data["HitRate"])
                
        with open(dst_file_path, 'w') as file:
            json.dump(json_result_data, file, indent=4)
    else:
        with open(dst_file_path,'r') as file:
            json_result_data = json.load(file)

        
    for i in range(len(json_result_data)):        
        parsed_result_data.append(MultiLayerCacheExclusive(json_result_data[i]))
    return json_result_data,parsed_result_data


def find_top_n_hitrate(res, n=3):
    # ヒット率とそれに対応するrefbits_layer2, refbits_layer3のタプルを格納するリスト
    hitrate_list = []

    for refbits_layer2, v in res.items():
        for refbits_layer3, data in v.items():
            hitrate = data.HitRate
            # (ヒット率, refbits_layer2, refbits_layer3)のタプルを追加
            hitrate_list.append((hitrate, refbits_layer2, refbits_layer3))

    # hitrate_listをヒット率で降順にソートして上位n個を取得
    top_n = heapq.nlargest(n, hitrate_list, key=lambda x: x[0])

    return top_n
first = 1
last = 32
# j,p = aggregate_result(1,32,[256,256,256])

analy = AnalysisResults(None)
# analy.add_result(p)


cap_first = 64 * 4
cap_last = 64 * 20
interval =64 * 4
capacity = [i for i in range(cap_first,cap_last+1,interval)] # 64から4096
layer1_capacity = copy.copy(capacity)
layer2_capacity = copy.copy(capacity)
layer3_capacity = copy.copy(capacity)
layer1_capacity.append(1)


first = 16
last = 24

# for l1c in layer1_capacity:
#     for l2c in layer2_capacity:
        
#         for l3c in layer3_capacity:
            
#             cache_capacity = [l1c,l2c,l3c]
#             if(sum(cache_capacity) == 1024 or  sum(cache_capacity) == 1025):
#                 if(l1c == 1 ):
#                     print(f"l1c == 1 added {cache_capacity}") 
#                 j,p = aggregate_result(first,last,cache_capacity,True)
#                 for s in p:
                    
#                     analy.add_result(s)
cap_first = 64 * 2
cap_last = 64 * 20
interval =64 * 2
capacity = [i for i in range(cap_first,cap_last+1,interval)] # 64から4096
layer1_capacity = copy.copy(capacity)
layer2_capacity = copy.copy(capacity)
layer3_capacity = copy.copy(capacity)
layer1_capacity.append(1)
first = 16
last = 24
for l1c in layer1_capacity:
    for l2c in layer2_capacity:
        
        for l3c in layer3_capacity:
            
            cache_capacity = [l1c,l2c,l3c]
            if(sum(cache_capacity) == 1024 or  sum(cache_capacity) == 1025):
                if(l1c == 1 ):
                    print(f"l1c == 1 added {cache_capacity}") 
                j,p = aggregate_result(first,last,cache_capacity,True)
                for s in p:
                    
                    analy.add_result(s)
a=analy.find_top_n_hitrate(10)
analy.print_results()
analy.check_results()
# analy.display_stat_detail(a)
# analy.stat_detail_plot(3)
# analy.hitrate_3dplot_3layer()
# analy.hitrate_3dplot_3layer(type="heatmap")

# res.print_results(a)

# make_hitrate_plot(res)

# n = 10  # 上位5個を取得
# top_n_hitrates = find_top_n_hitrate(res, n)

# for i, (hitrate, refbits_layer2, refbits_layer3) in enumerate(top_n_hitrates, 1):
#     print(f"順位 {i}: HitRate = {hitrate}, refbits_layer2 = {refbits_layer2}, refbits_layer3 = {refbits_layer3}")


