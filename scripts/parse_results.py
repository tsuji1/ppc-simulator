import json
import matplotlib.pyplot as plt
from typing import List, Dict

class MultiLayerCache:
    def __init__(self, data: Dict):
        self.Type = data["Type"]
        self.Parameter = data["Parameter"]
        self.Processed = data["Processed"]
        self.Hit = data["Hit"]
        self.HitRate = data["HitRate"]
        self.StatDetail = data["StatDetail"]
        
    def display(self):
        print("Type:", self.Type)
        print("Processed:", self.Processed)
        print("Hit:", self.Hit)
        print("HitRate:", self.HitRate)

        print("\nParameter Details:")
        for layer in self.Parameter["CacheLayers"]:
            print(f"Cache Layer Type: {layer['Type']}, Size: {layer['Size']}, Refbits: {layer['Refbits']}")

        print("\nCache Policies:", self.Parameter["CachePolicies"])

        print("\nStatDetail:")
        stat_detail = self.StatDetail
        print("Refered:", stat_detail["Refered"])
        print("Replaced:", stat_detail["Replaced"])
        print("Hit:", stat_detail["Hit"])
        print("MatchMap:", stat_detail["MatchMap"])
        print("LongestMatchMap:", stat_detail["LongestMatchMap"])
        print("DepthSum:", stat_detail["DepthSum"])
        print("NotInserted:", stat_detail["NotInserted"])
        
def plot_graph(dst_path,refbits: List[int], hit_rates: List[float]):
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
filename = '10-24bits_exclusive.json'

src_file_path = f'../result/{filename}'
# JSONファイルを読み込む
with open(src_file_path, 'r') as file:
    data:dict = json.load(file)

refbits_list= []
HitRate_list = []
for key, value in data.items():
    refbits = key
    cache = MultiLayerCache(value)
    print("Refbits:", key, "HitRate:",cache.HitRate)
    refbits_list.append(refbits)
    HitRate_list.append(cache.HitRate)
else:
    dst_path = f'../result/{filename[:-5]}.png'
    plot_graph(dst_path, refbits_list, HitRate_list)
    
    

