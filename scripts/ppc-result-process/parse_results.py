import json
import matplotlib.pyplot as plt
from typing import List, Dict
from MultiLayerCacheExclusive import MultiLayerExclusiveCache

        
def plot_graph_hit_rates(dst_path,refbits: List[int], hit_rates: List[float]):
    # グラフの作成
    plt.figure(figsize=(10, 6))
    plt.plot(refbits, hit_rates, marker='o')

    # グラフのタイトルとラベル
    plt.title('Hit Rate vs. Refbits')
    plt.xlabel('Refbits')
    plt.ylabel('HitRate')

    # グリッドを表示
    plt.grid(True)

    # グラフの保存
    plt.savefig(dst_path)
def plot_graph_all(dst_path,refbits: List[int], data):
        
    # グラフの作成
    fig, axs = plt.subplots(3, 2, figsize=(15, 15))

    # ヒット率
    axs[0, 0].bar(['Hit Rate'], [data['HitRate']])
    axs[0, 0].set_title('Hit Rate')

    # 参照された回数
    axs[0, 1].bar(['Layer 1', 'Layer 2'], data['StatDetail']['Refered'])
    axs[0, 1].set_title('Refered')

    # 置き換えられた回数
    axs[1, 0].bar(['Layer 1', 'Layer 2'], data['StatDetail']['Replaced'])
    axs[1, 0].set_title('Replaced')

    # ヒット回数
    axs[1, 1].bar(['Layer 1', 'Layer 2'], data['StatDetail']['Hit'])
    axs[1, 1].set_title('Hit')

    # マッチマップ
    axs[2, 0].plot(data['StatDetail']['MatchMap'])
    axs[2, 0].set_title('Match Map')

    # 最長マッチマップ
    axs[2, 1].plot(data['StatDetail']['LongestMatchMap'])
    axs[2, 1].set_title('Longest Match Map')
    plt.tight_layout()
    plt.savefig(dst_path)
    
filename = '10-24bits_exclusive.json'

src_file_path = f'../result/{filename}'
# JSONファイルを読み込む
with open(src_file_path, 'r') as file:
    data:dict = json.load(file)


plot_graph_all('../result/test',16,data['16'])
# refbits_list= []
# HitRate_list = []
# for key, value in data.items():
#     refbits = key
#     cache = MultiLayerCache(value)
#     print("Refbits:", key, "HitRate:",cache.HitRate)
#     refbits_list.append(refbits)
#     HitRate_list.append(cache.HitRate)
# else:
#     dst_path = f'../result/{filename[:-5]}.png'
#     plot_graph(dst_path, refbits_list, HitRate_list)
    
    

