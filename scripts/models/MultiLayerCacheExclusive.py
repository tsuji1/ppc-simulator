from typing import List, Dict, Literal
import warnings
import heapq
from typing_extensions import deprecated
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt
import heapq
import numpy as np


MultiLayerCacheExclusiveType =Literal['MultiLayerCacheExclusive']
class CacheLayer:
    def __init__(self,data:Dict):
        self.Type:str=str(data['Type'])
        self.Size:int =int(data['Size'])
        self.Refbits:int = int(data['Refbits'])
        
class CacheLayers:
    def __init__(self,data:List[CacheLayer]|None=None):
        if data is not None:
            self.CacheLayers:List[CacheLayer] = [CacheLayer(c) for c in data]
        else:
            self.CacheLayers = []
    def capacity_sum(self):
        return sum([c.Size for c in self.CacheLayers])
    
    def shortly_display(self):
        for i,c in enumerate(self.CacheLayers):
            print(f"Layer{i+1}(Size: {c.Size}, Refbits: {c.Refbits})",end=" ")
    
class MultiLayerCacheParameter:
    
    @deprecated("削除予定")
    @staticmethod
    def parseCacheLayers(cache_layers_data:Dict) -> List['CacheLayer']:
        warnings.warn("deprecated", DeprecationWarning)
        result = []
        for c in cache_layers_data:
            result.append(CacheLayer(c))
        return result
            
            
    
    def __init__(self , data:Dict|None=None):
        if data is not None:
            self.Type:str = data["Type"]
            self.CacheLayers:CacheLayers = CacheLayers(data["CacheLayers"])
        else:
            self.Type = ""
            self.CacheLayers = CacheLayers([])
class MultiLayerCacheExclusive:
    
    class MultiLayerCacheStatDetail:
        def __init__(self, data: Dict|None=None):
            if data is not None:
                self.Refered:List[int] = data["Refered"]
                self.Replaced:List[int] = data["Replaced"]
                self.Hit:List[int] = data["Hit"]
                self.MatchMap:List[int] = data["MatchMap"]
                self.LongestMatchMap:List[int] = data["LongestMatchMap"]
                self.DepthSum:List[int] = data["DepthSum"]
                self.Inserted:List[int] = data.get("Inserted", []) 
                self.NotInserted:List[int] = data.get("NotInserted", []) # Deprecated
            else:
                self.Refered = []
                self.Replaced = []
                self.Hit = []
                self.MatchMap = []
                self.LongestMatchMap = []
                self.DepthSum = []
                self.Inserted = []
                self.NotInserted = []
                
    def __init__(self, data: Dict|None=None):
        if data is not None:
            self.Type = data["Type"]
            self.Parameter = MultiLayerCacheParameter(data["Parameter"])
            self.Processed:int = int(data["Processed"])
            self.Hit :int= int(data["Hit"])
            self.HitRate:float =float(data["HitRate"])
            self.StatDetail = self.MultiLayerCacheStatDetail(data["StatDetail"]) 
        else:
            self.Type = ""
            self.Parameter = MultiLayerCacheParameter()
            self.Processed = 0
            self.Hit = 0
            self.HitRate = 0.0
            self.StatDetail = self.MultiLayerCacheStatDetail()
    def shortly_display(self):
        print(f"HitRate:{self.HitRate:.5f}",end=" ")
        self.Parameter.CacheLayers.shortly_display()
        print("")
        
        
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
class AnalysisResults:
    
    results:List[MultiLayerCacheExclusive] = []
    _tmp_results:List[MultiLayerCacheExclusive] = []
    
    def __init__(self,res:List[MultiLayerCacheExclusive]) -> None:
        self.results = res
        
    def __init__(self, data: Dict):
        self._explore_and_parse(data)
        
  
    def _explore_and_parse(self, data:any) -> None:
        if isinstance(data, dict):
            # 辞書の中に`Type`キーがあり、その値が'MultiLayerCacheExclusive'なら
            v = list(data.values())
            first_element =  v[0] if v else None
            if data.get('Processed',False):
  
                # MultiLayerCacheExclusiveに変換してリストに追加
                self.results.append(MultiLayerCacheExclusive(data))
            elif isinstance(first_element, MultiLayerCacheExclusive):
                self.results.extend([d for d in data.values()])
            # 辞書のすべてのキーに対して再帰的に探索
            else:
                for key, value in data.items():
                    self._explore_and_parse(value)
                    

    def find_top_n_hitrate(self, top=3,capacity_limit=float('inf'))->List[MultiLayerCacheExclusive]:
        '''  
        セットされた結果から上位topのヒット率を持つデータを取得。
        capacity_limitでキャッシュの容量制限を設定することができます。
        内部のtmp_resultsに結果を保持しておくため、print_results()を呼び出すことで表示できます。
        '''
        
        
        # 上位topヒット率を保持するための最小ヒープを利用
        top_hitrate_heap = []
        
        for data in self.results:
            if data.Parameter.CacheLayers.capacity_sum() <= capacity_limit:
                hitrate = data.HitRate
                
                # ヒット率とそのデータをヒープに追加
                if len(top_hitrate_heap) < top:
                    
                    heapq.heappush(top_hitrate_heap, (hitrate, id(data),data))
                    
                else:
                    # 既存の最小値より大きければ置き換える
                    heapq.heappushpop(top_hitrate_heap, (hitrate,id(data), data))
        
        # ヒット率の高い順に並べ替え
        top_hitrate_heap.sort(reverse=True, key=lambda x: x[0])
        self._tmp_results = [data for _ ,_, data in top_hitrate_heap]
        # ヒット率の高い順にデータを返す
        return [data for _,_, data in top_hitrate_heap]
    def print_results(self,result:List[MultiLayerCacheExclusive]|None=None):
        res:List[MultiLayerCacheExclusive] = [] 
        if(result is None):
            res = self._tmp_results
        for i, data in enumerate(res, 1):
            print(f"Result {i}: ", end=" ")
            data.shortly_display()
    def display(self):
        for data in self.results:
            data.shortly_display()
    
    
    def make_hitrate_plot_3dplot_3layer(self, type="mesh",rotate=[0,100,200,300]):
        # データを格納するリストの
        # データを格納するリスト
        x = []
        y = []
        z = []
        
        for data in self.results:
            x.append(data.Parameter.CacheLayers.CacheLayers[0].Size)
            y.append(data.Parameter.CacheLayers.CacheLayers[1].Size)
            z.append(data.HitRate)
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
        r = rotate[0]
        ax1 = fig.add_subplot(221, projection='3d')
        ax1.plot_wireframe(X, Y, Z)
        ax1.set_xlabel('refbits_layer2')
        ax1.set_ylabel('refbits_layer3')
        ax1.set_zlabel('hitrate')
        ax1.view_init(elev=30, azim=r)  # 視点設定
        ax1.set_title(f'{rotate}度回転',fontname ='Noto Sans CJK JP')

        # View 2
        r = rotate[1]
        ax2 = fig.add_subplot(222, projection='3d')
        ax2.plot_wireframe(X, Y, Z)
        ax2.set_xlabel('refbits_layer2')
        ax2.set_ylabel('refbits_layer3')
        ax2.set_zlabel('hitrate')
        ax2.view_init(elev=30, azim=r)  # 視点設定
        ax2.set_title(f'{rotate}度',fontname ='Noto Sans CJK JP')
        # View 3
        
        r = rotate[2]
        ax3 = fig.add_subplot(223, projection='3d')
        ax3.plot_wireframe(X, Y, Z)
        ax3.set_xlabel('refbits_layer2')
        ax3.set_ylabel('refbits_layer3')
        ax3.set_zlabel('hitrate')
        ax3.view_init(elev=30, azim=r)  # 視点設定
        ax3.set_title(f'{rotate}度',fontname ='Noto Sans CJK JP')
        # View 4
        
        r = rotate[3]
        ax4 = fig.add_subplot(224, projection='3d')
        ax4.plot_wireframe(X, Y, Z)
        ax4.set_xlabel('refbits_layer2')
        ax4.set_ylabel('refbits_layer3')
        ax4.set_zlabel('hitrate')
        ax4.view_init(elev=30, azim=r)  # 視点設定
        ax4.set_title(f'{rotate}度',fontname ='Noto Sans CJK JP')
        # 使用例
        top_d = self.find_top_n_hitrate(1)
        max_hitrate, max_refbits_layer2, max_refbits_layer3 =top_d, top_d.Parameter.CacheLayers.CacheLayers[0].Size,top_d.Parameter.CacheLayers.CacheLayers[1].Size 
        
        
        fig.text(0.1,0.06,f"Layer1は/32キャッシュで他のLayer2(/mキャッシュ)とLayer3(/nキャッシュ)の参照bitを変えている。32>m>nとなる。",fontsize=12,fontname ='Noto Sans CJK JP')

        fig.text(0.1,0.04,f"最大のヒット率: {max_hitrate:.5f} (refbits_layer2: {max_refbits_layer2}, refbits_layer3: {max_refbits_layer3})",fontsize=12,fontname ='Noto Sans CJK JP')
        
        parameter_description = ""
        for i,p in enumerate(top_d.Parameter.CacheLayers):
            parameter_description += f"Layer{i+1}, Size: {p.Size}    "
            
                
        fig.text(0.1, 0.02, parameter_description, fontsize=12,fontname ='Noto Sans CJK JP')
        plt.savefig("../result/multilayer_exclusive.png")
    def plot_graph_2layer_refbits_capacity(self):
        labels = []
        hitrates = []
        for data in self.results:
            c32 = data.Parameter.CacheLayers.CacheLayers[0].Size
            cn = data.Parameter.CacheLayers.CacheLayers[1].Size
            labels.append(f"{c32}-{cn}")
            hitrates.append(data.HitRate)

        plt.figure(figsize=(20, 8))
        plt.bar(labels, hitrates, color='blue')
        plt.xlabel('Configurations (/32キャッシュサイズ-/nビットキャッシュサイズ)',fontname ='Noto Sans CJK JP')
        plt.ylabel('HitRate')
        plt.title(f'HitRate for Different Cache Configurations (refbits={refbits})')
        plt.ylim(0.6, 1.0)
        plt.xticks(rotation=45, ha='right', fontsize=8,position=(0.5, 0))  # ラベルを45度回転させ、フォントサイズを小さくする
        plt.tight_layout()
        plt.savefig(f'../result/{src_file_name[:-5]}_refbits{refbits}_hitrate.png')
