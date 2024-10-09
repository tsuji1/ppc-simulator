from typing import List, Dict, Literal
import warnings
import heapq
from typing_extensions import deprecated
import matplotlib.pyplot as plt
import os
import datetime
import numpy as np

from matplotlib import rcParams

# デフォルトのフォントを 'Noto Sans CJK JP' に設定
rcParams['font.family'] = 'sans-serif'
rcParams['font.sans-serif'] = ['Noto Sans CJK JP']

MultiLayerCacheExclusiveType =Literal['MultiLayerCacheExclusive']
class CacheLayer:
    def __init__(self,data:Dict):
        self.Type:str=str(data['Type'])
        self.Size:int =int(data['Size'])
        self.Refbits: int = int(data.get('Refbits', data.get('Ref')))
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
    def check_capacity_match(self, capacity: List[int]) -> bool:
        """
        キャッシュレイヤーのサイズと与えられた capacity リストが一致するかどうかをチェックする。
        """
        cache_sizes = [c.Size for c in self.CacheLayers]
        res = cache_sizes == capacity
        return res
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
        print(f"Replaced:{self.StatDetail.Replaced}",end=" ")
        print(f"Replaced(Sum):{sum(self.StatDetail.Replaced)}",end=" ")
        print(f"Replaced(Std):{int(np.std(self.StatDetail.Replaced))}",end=" ")
        print(f"Replaced(MAE):{int(np.mean(np.abs(self.StatDetail.Replaced - np.mean(self.StatDetail.Replaced))))}",end=" ")
        print("")
        print("Hit:",self.StatDetail.Hit)
        print("")
        print("")
        
        
    def display(self):
        # print("Type:", self.Type)
        # print("Processed:", self.Processed)
        # print("Hit:", self.Hit)
        # print("HitRate:", self.HitRate)

        # print("\nParameter Details:")
        # for layer in self.Parameter["CacheLayers"]:
        #     print(f"Cache Layer Type: {layer['Type']}, Size: {layer['Size']}, Refbits: {layer['Refbits']}")

        # print("\nCache Policies:", self.Parameter["CachePolicies"])

        # print("\nStatDetail:")
        # stat_detail = self.StatDetail
        # print("Refered:", stat_detail["Refered"])
        # print("Replaced:", stat_detail["Replaced"])
        # print("Hit:", stat_detail["Hit"])
        # print("MatchMap:", stat_detail["MatchMap"])
        # print("LongestMatchMap:", stat_detail["LongestMatchMap"])
        # print("DepthSum:", stat_detail["DepthSum"])
        # print("NotInserted:", stat_detail["NotInserted"])
        
        
        print(f"Processed:{self.Processed}",end=" ")
        print(f"Hit:{self.Hit}",end=" ")
        print(f"HitRate:{self.HitRate:.5f}",end=" ")
        self.Parameter.CacheLayers.shortly_display()
        print("StatDetail:")
        print("Refered:", self.StatDetail.Refered)
        print("Replaced:", self.StatDetail.Replaced)
        print("Hit:", self.StatDetail.Hit)
        print("MatchMap:", self.StatDetail.MatchMap)
        print("LongestMatchMap:", self.StatDetail.LongestMatchMap)
        print("DepthSum:", self.StatDetail.DepthSum)
        print("Inserted:", self.StatDetail.Inserted)
        print("NotInserted:", self.StatDetail.NotInserted)
        
        


class AnalysisResults:
    
    class SummarizedResults:
        def __init__(self,result) -> None:
            self.HitRate:list[float] = []
            self.Hit:List[int] = []
            self.Processed:List[int] = []
            self.Refered:List[List[int]] = []
            self.Replaced:List[List[int]] = []
            self.Hits:List[List[int]] = []
            self.MatchMap:List[List[int]] = []
            self.LongestMatchMap:List[List[int]] = []
            self.DepthSum:List[List[int]] = []
            self.Inserted:List[List[int]] = []
            self.NotInserted:List[List[int]] = [] # Deprecated
            for r in result:
                self.HitRate.append(r.HitRate)
                self.Hit.append(r.Hit)
                self.Processed.append(r.Processed)
                self.Refered.append(r.StatDetail.Refered)
                self.Replaced.append(r.StatDetail.Replaced)
                self.Hits.append(r.StatDetail.Hit)
                self.MatchMap.append(r.StatDetail.MatchMap)
                self.LongestMatchMap.append(r.StatDetail.LongestMatchMap)
                self.DepthSum.append(r.StatDetail.DepthSum)
                self.Inserted.append(r.StatDetail.Inserted)
                self.NotInserted.append(r.StatDetail.NotInserted)           
    results:List[MultiLayerCacheExclusive] = []
    _tmp_results:List[MultiLayerCacheExclusive] = []
    def __init__(self) -> None:
        self.results = []
        self._tmp_results = []
        
    def __init__(self, data: any):
        self.results: List[MultiLayerCacheExclusive] = []
        self._tmp_results: List[MultiLayerCacheExclusive] = []
        if(data is not None):
            self.__explore_and_parse(data)
  
    def __explore_and_parse(self, data:any) -> None:
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
                    self.__explore_and_parse(value)
        elif isinstance(data, list):
            for item in data:
                print(item)
                self.__explore_and_parse(item)
        elif isinstance(data, MultiLayerCacheExclusive):
            self.results.append(data)
        else:
            print("Invalid data")
            return 1
    def add_result(self, data: MultiLayerCacheExclusive) -> None:
        self.__explore_and_parse(data)
    
    # ヒット率を
    def divide_results(self, count=3) -> list[MultiLayerCacheExclusive]:
        if(count > len(self.results) or count < 1):
            print("Invalid count")
            return 1
        res = []            
        hitrate_sorted_results = self.find_top_n_hitrate(len(self.results))
        res.append(hitrate_sorted_results[0])
       
        step = len(hitrate_sorted_results)//(count+1)
        r = range(1+step,len(hitrate_sorted_results)-2,step)
        for i in r:
            res.append(hitrate_sorted_results[i])
        res.append(hitrate_sorted_results[-1])
        return res
    def find_top_n_hitrate(self, top=3,res=None,refbits_limit=None,capacity_maximum_limit=float('inf'),hit_rate_maximum_limit=float(1),reverse=False)->List[MultiLayerCacheExclusive]:
        '''  
        セットされた結果から上位topのヒット率を持つデータを取得。0だとすべて取ってきます。
        capacity_limitでキャッシュの容量制限を設定することができます。
        また、hitrate_limitでヒット率の上限を設定することができます。
        内部のtmp_resultsに結果を保持しておくため、print_results()を呼び出すことで表示できます。
        refbits_limitでrefbitsの制限を設定することができます。[[layer2_refbits_minimum,layer2_refbits_maximum],...]
        '''
        
        
        if res is None:
            result = self.results
        else:
            result = res
        if(top == 0):
            top = float('inf')
        # 上位topヒット率を保持するための最小ヒープを利用
        top_hitrate_heap = []
        
        for data in result:
            if data.Parameter.CacheLayers.capacity_sum() <= capacity_maximum_limit and data.HitRate <= hit_rate_maximum_limit:
                skip = False
                if(refbits_limit is not None):
                    for l,restrict in enumerate(refbits_limit):
                        layer = l+1 #  1ayer1は必ず32より、 layer2をみるため
                        ref = data.Parameter.CacheLayers.CacheLayers[layer].Refbits
                        if ref < restrict[0] or ref > restrict[1]:
                            skip = True 
                if(skip):
                    continue
                hitrate = data.HitRate
                
                # ヒット率とそのデータをヒープに追加
                if len(top_hitrate_heap) < top:
                    
                    heapq.heappush(top_hitrate_heap, (hitrate, id(data),data))
                    
                else:
                    
                    if(reverse):
                        heapq.heappushpop(top_hitrate_heap, (-hitrate, id(data), data))
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
        else:
            res = result
        for i, data in enumerate(res, 1):
            print(f"Result {i}: ", end=" ")
            data.shortly_display()
            
            
            
    def check_results(self,result:List[MultiLayerCacheExclusive]|None=None):
        res:List[MultiLayerCacheExclusive] = [] 
        if(result is None):
            res = self._tmp_results
        else:
            res = result
        print("check unimodal for hitrate and replace(Sum)")
        for r in range(1,len(res)-1):
            prevReplaceSum = sum(res[r-1].StatDetail.Replaced)
            currentReplaceSum = sum(res[r].StatDetail.Replaced)
            nextReplaceSum = sum(res[r+1].StatDetail.Replaced)
            if currentReplaceSum >= prevReplaceSum and currentReplaceSum <= nextReplaceSum:
                pass
            else:
                print(f"Unimodal is not satisfied at {r}th data")
                print(f"prev:{prevReplaceSum}, current:{currentReplaceSum}, next:{nextReplaceSum}")
                break
        else:
            print(f"Unimodal is satisfied in {r+1}data")
            
        
    def display(self):
        for data in self.results:
            data.shortly_display()
            
    # CacheLayerの容量の最小値と最大値を取得
    def get_capacity_range(self,res:list[MultiLayerCacheExclusive]):
        capacity = []
        for d in res:
            for c in d.Parameter.CacheLayers.CacheLayers:
                capacity.append(c.Size)
        return min(capacity),max(capacity)
        
    def hitrate_3dplot_3layer(self, type="wire",rotate=[0,100,200,300]):
        # データを格納するリストの
        # データを格納するリスト
        data = self.results
        d = data
        x = []
        y = []
        z = []
        
        for k in self.results:
            x.append(k.Parameter.CacheLayers.CacheLayers[1].Refbits)
            y.append(k.Parameter.CacheLayers.CacheLayers[2].Refbits)
            z.append(k.HitRate)
        xnp = np.array(x)
        ynp = np.array(y)
        znp = np.array(z)

        # データの整形
        unique_x = np.unique(xnp)
        unique_y = np.unique(ynp)
        # print(xnp)

        X, Y = np.meshgrid(unique_x, unique_y)
        Z = np.full_like(X,np.nan, dtype=float)
        # print(Z)
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
      
        if(type=="heatmap"):
            ax = fig.add_subplot(111)
            plt.pcolormesh(X, Y, Z, shading='auto', cmap='viridis')  # cmapでカラーマップを指定
            plt.colorbar(label='hitrate')  # カラーバーを追加して強度を表示
            ax.set_xlabel('refbits_layer2',fontsize=18)
            ax.set_ylabel('refbits_layer3',fontsize=18)
        

                # ax.set_title(f'refbits:{refbits}',fontname ='Noto Sans CJK JP')
        else:
            place = 221
            for r in rotate:
                ax = fig.add_subplot(place, projection='3d')
                ax.plot_wireframe(X, Y, Z)
                ax.set_xlabel('refbits_layer2')
                ax.set_ylabel('refbits_layer3')
                ax.set_zlabel('hitrate')
                ax.view_init(elev=30, azim=r)  # 視点設定
                ax.set_title(f'{r}度',fontname ='Noto Sans CJK JP')
                place+=1
        
        top_d = self.find_top_n_hitrate(1)
        top_d= top_d[0]
        max_hitrate, max_refbits_layer2, max_refbits_layer3 =top_d.HitRate, top_d.Parameter.CacheLayers.CacheLayers[1].Refbits,top_d.Parameter.CacheLayers.CacheLayers[2].Refbits 
        
        
        # fig.text(0.1,0.06,f"Layer1は/32キャッシュで他のLayer2(/mキャッシュ)とLayer3(/nキャッシュ)の参照bitを変えている。32>m>nとなる。",fontsize=12,fontname ='Noto Sans CJK JP')

        # fig.text(0.1,0.04,f"最大のヒット率: {max_hitrate:.5f} (refbits_layer2: {max_refbits_layer2}, refbits_layer3: {max_refbits_layer3})",fontsize=12,fontname ='Noto Sans CJK JP')
        # 横軸のラベルを回転して表示（長いラベルの場合に有効）
        plt.xticks(fontsize=18)  # フォントサイズを14に設定
        plt.yticks(fontsize=18)  # y軸の目盛りもフォントサイズを14に設定

        # グラフのレイアウト調整
        plt.tight_layout()
        parameter_description = ""
        for i,p in enumerate(top_d.Parameter.CacheLayers.CacheLayers):
            parameter_description += f"Layer{i+1}, Size: {p.Size}    "
        min_cap,max_cap = self.get_capacity_range(d)    
        src_file_name = f'hitrate_3dplot_3layer_refbits_mincap{min_cap}_maxcap{max_cap}_{type}'
        # fig.text(0.1, 0.02, parameter_description, fontsize=12,fontname ='Noto Sans CJK JP')
        os.makedirs(f"../result/hitrate_3dplot_3layer/{type}",exist_ok=True)
        plt.savefig(f"../result/hitrate_3dplot_3layer/{type}/{src_file_name}.png")

    def hitrate_bar_graph_2cache_refbits_fixed_32bitcapacity(self, capacity_32bit=16, refbits_range=list(range(1, 32)), capacity_range=[2**i for i in range(4, 10)]):
        if (isinstance(capacity_32bit,int)):
            data = self.query_results_with_refbits_all()
            num_refbits = len(refbits_range)  # 参照ビット数の数
            fig, axs = plt.subplots(figsize=(12, 12))
            x_labels = capacity_range
            y_labels = np.arange(0.00, 1.05, 0.05)
            x = np.arange(len(x_labels))  # X軸の位置

            # 各条件での棒グラフの幅
            bar_width = 0.10

            # カラーマップの設定（青色のグラデーション）
            cmap_blue = plt.get_cmap('Blues')
            cmap_green = plt.get_cmap('Greens')
            colors_blue = [cmap_blue((i + 2) / (len(refbits_range) + 2)) for i in range(len(refbits_range))]
            colors_green = [cmap_green((i + 2) / (len(refbits_range) + 2)) for i in range(len(refbits_range))]

            # すでに凡例が設定されたかどうかを追跡するためのフラグ
            # 凡例用のセットを初期化
            legend_labels_32 = set()
            legend_labels_n = set()
            
            # グラフのプロット
            for index, ncap in enumerate(capacity_range):  # キャッシュのエントリ数ごとにプロット
                for i, refbit in enumerate(refbits_range):  # 参照ビット数ごとにプロット
                    d = data[refbit]
                    capacities = [capacity_32bit, ncap]
                    query_data = self.query_results_with_capacity(d, capacities)
                    
                    if len(query_data) != 0:
                        qd = query_data[0]
                        cache32hit = qd.StatDetail.Hit[0] / qd.Processed
                        cachenhit = qd.StatDetail.Hit[1] / qd.Processed
                        
                        # 最初の棒グラフをcache32hitで描画
                        axs.bar(x[index] + bar_width * i, cache32hit, bar_width, color=colors_blue[0],edgecolor='black')
                        # その上にcachenhitを積み上げる
                        axs.bar(x[index] + bar_width * i, cachenhit, bar_width, bottom=cache32hit, color=colors_green[i],edgecolor='black')
                    else:
                        print("capacities:", capacities, "not found")
            axs.bar(0, 0, color=colors_blue[0], label='/32キャッシュ', edgecolor='black')  # 仮の棒グラフで凡例を追加
            legend_labels_32.add(refbit)
            for i, refbit in enumerate(refbits_range):
                if refbit not in legend_labels_n:
                    axs.bar(0, 0, color=colors_green[i], label=f'/{refbit}キャッシュ', edgecolor='black')  # 仮の棒グラフで凡例を追加
                    legend_labels_n.add(refbit)

            # 凡例をグラフの外に表示
            axs.legend(title='キャッシュの種類', title_fontsize=19, fontsize=17, bbox_to_anchor=(1.05, 1.0), loc='upper left', borderaxespad=0.)
            
            # X軸ラベルと目盛りの設定
            axs.set_xlabel('/nキャッシュのエントリ数',fontsize=18)
            axs.set_ylabel('ヒット率',fontsize=18)
            axs.set_xticks(x + bar_width * num_refbits / 2)  # X軸の目盛りの位置
            axs.set_xticklabels(x_labels,fontsize=18)  # X軸のラベル
            
            axs.set_yticks(y_labels)
            axs.set_yticklabels([f'{i:.2f}' for i in y_labels],fontsize=18)  # Y軸のラベル
                # Y軸の範囲を0.5から最大まで設定
            axs.set_ylim(0.0, 1.0)

            
            axs.set_title(f'/32キャッシュのエントリ数を{capacity_32bit}に固定した際のヒット率',fontsize=18)
            
            fig.tight_layout()
        
            # グラフの保存
            now = datetime.datetime.now()
            src_file_name = now.strftime("%Y%m%d-%H%M%S") + f"-32bitcap{capacity_32bit}-refbits{refbits_range[0]}-{refbits_range[-1]}-cap{capacity_range[0]}-{capacity_range[-1]}"
            base_dir = "../result/hitrate_bar_graph_2cache_refbits_fixed_32bitcapacity"
            os.makedirs(base_dir, exist_ok=True)
            file_path = os.path.join(base_dir, f"{src_file_name}.png")
            plt.savefig(file_path, bbox_inches='tight')  # bbox_inches='tight' でグラフと凡例が切れないようにする
            plt.close()
        elif(isinstance(capacity_32bit,list)):
            data = self.query_results_with_refbits_all()
            # 列を2つにしてサブプロットを配置する場合の修正
            num_cols = 2  # 2列にする
            num_refbits = len(refbits_range)  # 参照ビット数の数
            num_plots = len(capacity_32bit)  # サブプロットの数
            num_rows = int(np.ceil(num_plots / num_cols))  # 行数は全体のサブプロット数に基づいて計算
            fig, axs = plt.subplots(num_rows, num_cols, figsize=(12 * num_cols, 12 * num_rows))  # 2列でサブプロットを作成

            x_labels = capacity_range
            y_labels = np.arange(0.00, 1.05, 0.05)
            x = np.arange(len(x_labels))  # X軸の位置

            # 各条件での棒グラフの幅
            bar_width = 0.10

            # カラーマップの設定（青色と緑色のグラデーション）
            cmap_blue = plt.get_cmap('Blues')
            cmap_green = plt.get_cmap('Greens')
            colors_blue = [cmap_blue((i + 2) / (len(refbits_range) + 2)) for i in range(len(refbits_range))]
            colors_green = [cmap_green((i + 2) / (len(refbits_range) + 2)) for i in range(len(refbits_range))]

            for plot_idx, cap_32bit in enumerate(capacity_32bit):  # リスト内の各32bit容量に対してサブプロットを作成
                row = plot_idx // num_cols  # 行のインデックス
                col = plot_idx % num_cols   # 列のインデックス
                ax = axs[row, col]  # サブプロットを指定

                for index, ncap in enumerate(capacity_range):  # キャッシュのエントリ数ごとにプロット
                    for i, refbit in enumerate(refbits_range):  # 参照ビット数ごとにプロット
                        d = data[refbit]
                        capacities = [cap_32bit, ncap]
                        query_data = self.query_results_with_capacity(d, capacities)

                        if len(query_data) != 0:
                            qd = query_data[0]
                            cache32hit = qd.StatDetail.Hit[0] / qd.Processed
                            cachenhit = qd.StatDetail.Hit[1] / qd.Processed

                            # 最初の棒グラフをcache32hitで描画
                            ax.bar(x[index] + bar_width * i, cache32hit, bar_width, color=colors_blue[0], edgecolor='black')
                            # その上にcachenhitを積み上げる
                            ax.bar(x[index] + bar_width * i, cachenhit, bar_width, bottom=cache32hit, color=colors_green[i], edgecolor='black')

                # X軸ラベルと目盛りの設定
                ax.set_xlabel('/nキャッシュのエントリ数', fontsize=18)
                ax.set_ylabel('ヒット率', fontsize=18)
                ax.set_xticks(x + bar_width * len(refbits_range) / 2)
                ax.set_xticklabels(x_labels, fontsize=18)

                ax.set_yticks(y_labels)
                ax.set_yticklabels([f'{i:.2f}' for i in y_labels], fontsize=18)
                ax.set_ylim(0.0, 1.0)

                # 各サブプロットに個別のタイトルを設定
                ax.set_title(f'/32キャッシュのエントリ数を{cap_32bit}に固定した際のヒット率', fontsize=18)

            # 凡例は1つにまとめる
            handles = [plt.Rectangle((0,0),1,1, color=colors_blue[0], edgecolor='black', label='/32キャッシュ')]
            handles += [plt.Rectangle((0,0),1,1, color=colors_green[i], edgecolor='black', label=f'/{refbit}キャッシュ') for i, refbit in enumerate(refbits_range)]

            fig.legend(handles=handles, title='キャッシュの種類', title_fontsize=27, fontsize=25, bbox_to_anchor=(1.02, 1.0), loc='upper left', borderaxespad=0.)

            fig.tight_layout()

            # グラフの保存
            now = datetime.datetime.now()
            src_file_name = now.strftime("%Y%m%d-%H%M%S") + f"-32bitcap{capacity_32bit[0]}-{capacity_32bit[-1]}-refbits{refbits_range[0]}-{refbits_range[-1]}-cap{capacity_range[0]}-{capacity_range[-1]}"
            base_dir = "../result/hitrate_bar_graph_2cache_refbits_fixed_32bitcapacity"
            os.makedirs(base_dir, exist_ok=True)
            file_path = os.path.join(base_dir, f"{src_file_name}.png")
            plt.savefig(file_path, bbox_inches='tight')
            plt.close()
                            
    def hitrate_3dplot_2layer(self, type="wire",rotate=[0,100,200,300]):
        # データを格納するリストの
        # データを格納するリスト
        data = self.query_results_with_refbits_all()
        # print(data.keys())
        for i,d in data.items():
            print(f"refbits: {i} のデータを処理中")
            refbits = i
            x = []
            y = []
            z = []
            
            for k in self.results:
                x.append(k.Parameter.CacheLayers.CacheLayers[0].Size)
                y.append(k.Parameter.CacheLayers.CacheLayers[1].Size)
                z.append(k.HitRate)
            xnp = np.array(x)
            ynp = np.array(y)
            znp = np.array(z)

            # データの整形
            unique_x = np.unique(xnp)
            unique_y = np.unique(ynp)
            X, Y = np.meshgrid(unique_x, unique_y)
            Z = np.full_like(X, np.nan, dtype=float)
            # 各x, yに対応するzをセット
            for i in range(len(znp)):
                xi = np.where(unique_x == xnp[i])[0][0]
                yi = np.where(unique_y == ynp[i])[0][0]
                Z[yi, xi] = znp[i]
            fig = plt.figure(figsize=(12, 12))
            place = 221

            # 3Dグラフの描画

            # カラーマップを使いたい場合は以下を使用
            # ax.plot_surface(X, Y, Z, cmap='bwr')

            # 3Dグラフを4つの異なる視点で描画
            
            
     
            if(type=="heatmap"):
                # ヒートマップ用のデータを作成
                ax = fig.add_subplot(111)
                plt.pcolormesh(X, Y, Z, shading='auto', cmap='viridis')  # cmapでカラーマップを指定
                plt.colorbar(label='hitrate')  # カラーバーを追加して強度を表示
                ax.set_xlabel('refbits_layer1 size')
                ax.set_ylabel('refbits_layer2 size')
                    
            else:
                for r in rotate:
                    ax = fig.add_subplot(place, projection='3d')
                    ax.plot_wireframe(X, Y, Z)
                    ax.set_xlabel('refbits_layer1 size')
                    ax.set_ylabel('refbits_layer2 size')
                    ax.set_zlabel('hitrate')
                    ax.view_init(elev=30, azim=r)  # 視点設定
                    ax.set_title(f'{r}度回転',fontname ='Noto Sans CJK JP')
                
                place+=1
            # 使用例
            top_d = self.find_top_n_hitrate(1)
            top_d= top_d[0]
            max_hitrate, max_32ref_size, max_nref_size =top_d.HitRate,top_d.Parameter.CacheLayers.CacheLayers[0].Size,top_d.Parameter.CacheLayers.CacheLayers[1].Size 
            
            
            # fig.text(0.1,0.06,f"Layer1は/32キャッシュで他のLayer2(/mキャッシュ)とLayer3(/nキャッシュ)の参照bitを変えている。32>m>nとなる。",fontsize=12,fontname ='Noto Sans CJK JP')

            fig.text(0.1,0.04,f"最大のヒット率: {max_hitrate:.5f} (refbits_layer1_size: {max_32ref_size}, refbits_layer2_size: {max_nref_size})",fontsize=12,fontname ='Noto Sans CJK JP')
            
            parameter_description = ""
            for i,p in enumerate(top_d.Parameter.CacheLayers.CacheLayers):
                parameter_description += f"Layer{i+1}, Size: {p.Size}    "
            min_cap,max_cap = self.get_capacity_range(d)    
            src_file_name = f'hitrate_3dplot_2layer_refbits{refbits}_mincap{min_cap}_maxcap{max_cap}_{type}'
            fig.text(0.1, 0.02, parameter_description, fontsize=12,fontname ='Noto Sans CJK JP')
            
            # directory を作成する
 
            os.makedirs(f"../result/hitrate_3dplot_2layer/{type}",exist_ok=True)
            
            
            plt.savefig(f"../result/hitrate_3dplot_2layer/{type}/{src_file_name}.png")
            plt.close()
            
    # layer 2のrefbitsによってデータを分けます。dict[refbits, List[MultiLayerCacheExclusive]]
    def query_results_with_refbits_all(self)->dict[int,list[MultiLayerCacheExclusive]]:
        res :dict[int,list[MultiLayerCacheExclusive]] = {}
        for data in self.results:
            refbits = data.Parameter.CacheLayers.CacheLayers[1].Refbits
            if res.get(refbits) is None:
                res[refbits] = []
            res[refbits].append(data)
        return res
    
    # cache capacityによってデータを分けます。dict[capacity, List[MultiLayerCacheExclusive]]
    def query_results_with_capacity(self,results:list[MultiLayerCacheExclusive],capacity=[])->list[MultiLayerCacheExclusive]:
        res = []
        if capacity:
            for data in results:
                if(data.Parameter.CacheLayers.check_capacity_match(capacity)):
                    res.append(data)        
        return res
    def hitrate_2dplot_2layer_refbits_capacity(self,src_file_name:str="test"):
        if(src_file_name=="test"):
            print("src_file_name is not set")
        data = self.query_results_with_refbits_all()
        for i,d in data.items():
            labels = []
            hitrates = []
            refbits = i
            c32 = d.Parameter.CacheLayers.CacheLayers[0].Size
            cn = d.Parameter.CacheLayers.CacheLayers[1].Size
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
            plt.savefig(f'../result/2layer-refbits-capacity/{src_file_name}_refbits{refbits}_hitrate.png')
    def display_stat_detail(self, result:List[MultiLayerCacheExclusive]):
        for r in result:
            r.display()
    def stat_detail_plot(self,count=3):
        data = self.divide_results(count)
        
        sum_res = self.SummarizedResults(data)
        
        fig, axs = plt.subplots(3, 2, figsize=(20, 40))
        # refbits-refbitsの組み合わせ
        cache_names= []
        for d in data:
            cache_names.append(f"{d.Parameter.CacheLayers.CacheLayers[1].Refbits}-{d.Parameter.CacheLayers.CacheLayers[2].Refbits}")

        # ヒット率
        axs[0, 0].bar(cache_names, sum_res.HitRate)
        axs[0, 0].set_title('Hit Rate')
        axs[0, 0].set_xticklabels(cache_names, rotation=45, ha='right')

        # 参照された回数 (ヒストグラム)
        width = 0.8 / len(cache_names)
        x = np.arange(len(sum_res.Refered[0]))
        for i, (name, ref) in enumerate(zip(cache_names, sum_res.Refered)):
            axs[0, 1].bar(x + i * width, ref, width=width, label=name)
        axs[0, 1].set_title('Refered')
        axs[0, 1].legend()
        axs[0, 1].set_xticks(x + width * (len(cache_names) - 1) / 2)
        axs[0, 1].set_xticklabels(x)

        # 置き換えられた回数 (ヒストグラム)
        x = np.arange(len(sum_res.Replaced[0]))
        for i, (name, rep) in enumerate(zip(cache_names, sum_res.Replaced)):
            axs[1, 0].bar(x + i * width, rep, width=width, label=name)
        axs[1, 0].set_title('Replaced')
        axs[1, 0].legend()
        axs[1, 0].set_xticks(x + width * (len(cache_names) - 1) / 2)
        axs[1, 0].set_xticklabels(x)

        # ヒット回数 (ヒストグラム)
        x = np.arange(len(sum_res.Hits[0]))
        for i, (name, hit) in enumerate(zip(cache_names, sum_res.Hits)):
            axs[1, 1].bar(x + i * width, hit, width=width, label=name)
        axs[1, 1].set_title('Hit')
        axs[1, 1].legend()
        axs[1, 1].set_xticks(x + width * (len(cache_names) - 1) / 2)
        axs[1, 1].set_xticklabels(x)

        # MatchMap (ヒストグラム)
        x = np.arange(len(sum_res.MatchMap[0]))
        for i, (name, mm) in enumerate(zip(cache_names, sum_res.MatchMap)):
            axs[2, 0].bar(x + i * width, mm, width=width, label=name)
        axs[2, 0].set_title('MatchMap')
        axs[2, 0].legend()
        axs[2, 0].set_xticks(x + width * (len(cache_names) - 1) / 2)
        axs[2, 0].set_xticklabels(x)

        # LongestMatchMap (ヒストグラム)
        x = np.arange(len(sum_res.LongestMatchMap[0]))
        for i, (name, lmm) in enumerate(zip(cache_names, sum_res.LongestMatchMap)):
            axs[2, 1].bar(x + i * width, lmm, width=width, label=name)
        axs[2, 1].set_title('LongestMatchMap')
        axs[2, 1].legend()
        axs[2, 1].set_xticks(x + width * (len(cache_names) - 1) / 2)
        axs[2, 1].set_xticklabels(x)
    

        matchmap_correction = []
        longest_matchmap_correction = []
        for hit,process,mm,lmm in zip(sum_res.Hit,sum_res.Processed,sum_res.MatchMap,sum_res.LongestMatchMap):
            mm_correction =  [int(float(m)*(process/hit)) for m in mm]
            lmm_correction = [int(float(lm)*(process/hit)) for lm in lmm]
            matchmap_correction.append(mm_correction)
            longest_matchmap_correction.append(lmm_correction)
        print(matchmap_correction)
        print(sum_res.MatchMap)
            
        # x = np.arange(len(sum_res.MatchMap[0]))
        # for i, (name, ni) in enumerate(zip(cache_names, matchmap_correction)):
        #     axs[3, 0].bar(x + i * width, ni, width=width, label=name)
        # axs[3, 0].set_title('matchmap correction')
        # axs[3, 0].legend()
        # axs[3, 0].set_xticks(x + width * (len(cache_names) - 1) / 2)
        # axs[3, 0].set_xticklabels(x)

        # x = np.arange(len(sum_res.LongestMatchMap[0]))
        # longest_matchmap_correction_sum = [sum(l) for l in longest_matchmap_correction]
        # print(longest_matchmap_correction_sum)
        # for i, (name, ni) in enumerate(zip(cache_names, longest_matchmap_correction)):
        #     axs[3, 1].bar(x + i * width, ni, width=width, label=name)
        # axs[3, 1].set_title('longest matchmap correction')
        # axs[3, 1].legend()
        # axs[3, 1].set_xticks(x + width * (len(cache_names) - 1) / 2)
        # axs[3, 1].set_xticklabels(x)

        # グラフのレイアウト調整
        plt.tight_layout()
        dst_file_name = f'stat_detail_plot_{count}.png'
        plt.savefig(f'../result/{dst_file_name}')

