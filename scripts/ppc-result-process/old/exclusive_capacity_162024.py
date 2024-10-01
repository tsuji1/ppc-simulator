import os
import json
from models.MultiLayerCacheExclusive import MultiLayerCacheExclusive,AnalysisResults
import heapq
src_file_name = '16-24bits_cap4-cap12_exclusive.json'
src_file_path = os.path.join('../result', src_file_name)
# result_data[refbits][cache_32bit_cap][cache_nbit_cap]
with open(src_file_path, 'r') as file:
    data = json.load(file)

refbits_list = ['16', '20', '24']
cap_first = 4
cap_last = 12
capacity = [str(2**i) for i in range(cap_first, cap_last+1)]

hitrate_dict = {refbits: [] for refbits in refbits_list}
parsed_data = {}
for refbits in refbits_list:
    parsed_data[refbits] = {}
    for cache_32bit_cap in capacity:
        parsed_data[refbits][cache_32bit_cap] = {}
        for cache_nbit_cap in capacity:
            parsed_data[refbits][cache_32bit_cap][cache_nbit_cap] = MultiLayerCacheExclusive(data[refbits][cache_32bit_cap][cache_nbit_cap])
            d = data[refbits][cache_32bit_cap][cache_nbit_cap]



def find_top_n_hitrate(res, n=3):
    # ヒット率とそれに対応するrefbits_layer2, refbits_layer3のタプルを格納するリスト
    hitrate_list = []

    for refbits in refbits_list:
        for cache_32bit_cap in capacity:
            for cache_nbit_cap in capacity:
                hitrate = res[refbits][cache_32bit_cap][cache_nbit_cap].HitRate
                # (ヒット率, refbits_layer2, refbits_layer3)のタプルを追加
                hitrate_list.append((hitrate, refbits, cache_32bit_cap, cache_nbit_cap))

    # hitrate_listをヒット率で降順にソートして上位n個を取得
    top_n = heapq.nlargest(n, hitrate_list, key=lambda x: x[0])

    return top_n


analysis_results = AnalysisResults(parsed_data)


analysis_results.find_top_n_hitrate(10,2048)
analysis_results.print_results()

