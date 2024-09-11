import os
import json
from models.MultiLayerCacheExclusive import MultiLayerCacheExclusive,AnalysisResults
import copy
# refbitsごとにまとめよう
first = 1
last = 25

cap_first = 64 * 2 
cap_last = int(4096 /2)
interval =64 * 2 
capacity = [i for i in range(cap_first,cap_last+1,interval)] # 64から4096
capacity_nbits = copy.copy(capacity)
capacity_32bits = copy.copy(capacity)
capacity_32bits.append(1)

def aggregate_result(refbits,cache_32bit_capacity, cache_nbit_capacity):
    result_data = {}
    tmp_dir = '../result/tmp_results'
    tmp_dir_refbits = os.path.join(tmp_dir, f'{refbits}')
    
    try:
        result_data[refbits] = {}
        for cache_32bit_cap in cache_32bit_capacity:
            result_data[refbits][cache_32bit_cap] = {}
            for cache_nbit_cap in cache_nbit_capacity:
                if(cache_32bit_cap == 1 and refbits!=24):
                    continue
                partial_result_file = os.path.join(tmp_dir_refbits, f'tmp_result_{cache_32bit_cap}_{cache_nbit_cap}.json')
                with open(partial_result_file, 'r') as file:
                    _json_data = json.load(file)
                    result_data[refbits][cache_32bit_cap][cache_nbit_cap] = _json_data
        dst_file_path = f'../result/{refbits}bits_cap{cap_first}-cap{cap_last}-interval{interval}-exclusive.json'
    except Exception as e:
        print(e)
    # 最終的な結果を一つの大きなファイルに書き込む
    with open(dst_file_path, 'w') as file:
        json.dump(result_data, file, indent=4)

    return 0


anly = AnalysisResults(None)
for refbits in range(first, last + 1):
    
    aggregate_result(refbits,capacity_32bits,capacity_nbits) # jsonを作成
    data_file_path = f'../result/{refbits}bits_cap{cap_first}-cap{cap_last}-interval{interval}-exclusive.json'
    with open(data_file_path, 'r') as file:
        json_data = json.load(file)
    anly.add_result(json_data)
    
# anly.hitrate_3dplot_2layer(type="heatmap")
d = anly.query_results_with_refbits_all()

for k,v in d.items():
    if(k>=16 and k<=24):
        top_n = anly.find_top_n_hitrate(10, capacity_maximum_limit=1025,refbits=k)
anly.find_top_n_hitrate(10, capacity_maximum_limit=1025)
anly.print_results()
anly.check_results()
