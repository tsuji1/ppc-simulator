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
    
    json_result_data = {}
    parsed_result_data = {} 
    tmp_dir = '../result/tmp_results'
    
    cache_num = len(cache_capacity)
    cache_capacity_string = "-".join([str(i) for i in cache_capacity])
    dst_file_path = f'../result/multilayer_{cache_num}layer_{cache_capacity_string}.json'
    
    if (not os.path.exists(dst_file_path) or force_update):
        for refbits_layer2 in range(first_refbits,last_refbits+1): # layer 2
            json_result_data[refbits_layer2] = {}
            for refbits_layer3 in range(first, refbits_layer2):
                refbits = [32,refbits_layer2,refbits_layer3]
                refbits_string = "-".join([str(i) for i in refbits])
                tmp_dir_refbits = os.path.join(tmp_dir, f'{refbits_string}')
                partial_result_file = make_tmp_file_path(tmp_dir_refbits,refbits,cache_capacity)
                with open(partial_result_file, 'r') as file:
                    _json_data = json.load(file)
                    json_result_data[str(refbits_layer2)][str(refbits_layer3)] = _json_data
                
        with open(dst_file_path, 'w') as file:
            json.dump(json_result_data, file, indent=4)
    else:
        with open(dst_file_path,'r') as file:
            json_result_data = json.load(file)
            
    print(json_result_data.keys())
    for refbits_layer2 in range(first_refbits,last_refbits+1): # layer 2
        parsed_result_data[refbits_layer2] = {}
        for refbits_layer3 in range(first, refbits_layer2):
            parsed_result_data[refbits_layer2][refbits_layer3] = MultiLayerCacheExclusive(json_result_data[str(refbits_layer2)][str(refbits_layer3)])
    return json_result_data,parsed_result_data
    



def make_hitrate_plot(res):
    refbits_layer2:int
    
    # データを格納するリスト
    x = []
    y = []
    z = []

    # データの取得
    for refbits_layer2, v in res.items():
        for refbits_layer3, data in v.items():
            x.append(refbits_layer2)
            y.append(refbits_layer3)
            z.append(data.HitRate)
    else:
        d:MultiLayerCacheExclusive = data
    # numpy配列に変換
    xnp = np.array(x)
    ynp = np.array(y)
    znp = np.array(z)

    # データの整形
    unique_x = np.unique(xnp)
    unique_y = np.unique(ynp)
    print(xnp)

    X, Y = np.meshgrid(unique_x, unique_y)
    Z = np.full_like(X,np.nan, dtype=float)
    print(Z)
    # 各x, yに対応するzをセット
    for i in range(len(znp)):
        xi = np.where(unique_x == xnp[i])[0][0]
        yi = np.where(unique_y == ynp[i])[0][0]
        Z[yi, xi] = znp[i]

    # 3Dグラフの描画

    # カラーマップを使いたい場合は以下を使用
    # ax.plot_surface(X, Y, Z, cmap='bwr')

    # 3Dグラフを4つの異なる視点で描画
    fig = plt.figure(figsize=(12, 12))

    # View 1
    rotate = 0
    ax1 = fig.add_subplot(221, projection='3d')
    ax1.plot_wireframe(X, Y, Z)
    ax1.set_xlabel('refbits_layer2')
    ax1.set_ylabel('refbits_layer3')
    ax1.set_zlabel('hitrate')
    ax1.view_init(elev=30, azim=rotate)  # 視点設定
    ax1.set_title(f'{rotate}度回転',fontname ='Noto Sans CJK JP')

    # View 2
    rotate += 60
    ax2 = fig.add_subplot(222, projection='3d')
    ax2.plot_wireframe(X, Y, Z)
    ax2.set_xlabel('refbits_layer2')
    ax2.set_ylabel('refbits_layer3')
    ax2.set_zlabel('hitrate')
    ax2.view_init(elev=30, azim=rotate)  # 視点設定
    ax2.set_title(f'{rotate}度',fontname ='Noto Sans CJK JP')
    # View 3
    
    rotate += 60
    ax3 = fig.add_subplot(223, projection='3d')
    ax3.plot_wireframe(X, Y, Z)
    ax3.set_xlabel('refbits_layer2')
    ax3.set_ylabel('refbits_layer3')
    ax3.set_zlabel('hitrate')
    ax3.view_init(elev=30, azim=rotate)  # 視点設定
    ax3.set_title(f'{rotate}度',fontname ='Noto Sans CJK JP')
    # View 4
    
    rotate+=60
    ax4 = fig.add_subplot(224, projection='3d')
    ax4.plot_wireframe(X, Y, Z)
    ax4.set_xlabel('refbits_layer2')
    ax4.set_ylabel('refbits_layer3')
    ax4.set_zlabel('hitrate')
    ax4.view_init(elev=30, azim=rotate)  # 視点設定
    ax4.set_title(f'{rotate}度',fontname ='Noto Sans CJK JP')
    # 使用例
    max_hitrate, max_refbits_layer2, max_refbits_layer3 = find_max_hitrate(res)
    
    
    fig.text(0.1,0.06,f"Layer1は/32キャッシュで他のLayer2(/mキャッシュ)とLayer3(/nキャッシュ)の参照bitを変えている。32>m>nとなる。",fontsize=12,fontname ='Noto Sans CJK JP')

    fig.text(0.1,0.04,f"最大のヒット率: {max_hitrate:.5f} (refbits_layer2: {max_refbits_layer2}, refbits_layer3: {max_refbits_layer3})",fontsize=12,fontname ='Noto Sans CJK JP')
    
    parameter_description = ""
    for i,p in enumerate(d.Parameter.CacheLayers):
        parameter_description += f"Layer{i+1}, Size: {p.Size}    "
        
            
    fig.text(0.1, 0.02, parameter_description, fontsize=12,fontname ='Noto Sans CJK JP')
    plt.savefig("../result/multilayer_exclusive.png")
    plt.close()
def find_max_hitrate(res):
    max_hitrate = float('-inf')  # 初期値として非常に小さい値を設定
    max_refbits_layer2 = None
    max_refbits_layer3 = None

    for refbits_layer2, v in res.items():
        for refbits_layer3, data in v.items():
            hitrate = data.HitRate
            if hitrate > max_hitrate:
                max_hitrate = hitrate
                max_refbits_layer2 = refbits_layer2
                max_refbits_layer3 = refbits_layer3

    return max_hitrate, max_refbits_layer2, max_refbits_layer3


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
j,p = aggregate_result(1,32,[256,256,256])

analy = AnalysisResults(p)
a=analy.find_top_n_hitrate(10)
analy.print_results()
analy.display_stat_detail(a)
analy.stat_detail_plot(3)
# analy.hitrate_3dplot_3layer()
# analy.hitrate_3dplot_3layer(type="heatmap")
# # a = res.find_top_n_hitrate(10)
# print(a)
# res.print_results(a)

# make_hitrate_plot(res)

# n = 10  # 上位5個を取得
# top_n_hitrates = find_top_n_hitrate(res, n)

# for i, (hitrate, refbits_layer2, refbits_layer3) in enumerate(top_n_hitrates, 1):
#     print(f"順位 {i}: HitRate = {hitrate}, refbits_layer2 = {refbits_layer2}, refbits_layer3 = {refbits_layer3}")


