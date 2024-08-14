import os
import subprocess


import json

# JSONファイルのパス
src_file_path = '../simulator-settings/MultiLayerCacheExclusive.json'
first = 16
last = 24

cap_first = 4
cap_last = 12
capacity = [2**i for i in range(cap_first, cap_last+1)]

tmp_dir = '../result/tmp_results'
# JSONファイルを読み込む
with open(src_file_path, 'r') as file:
    data:dict = json.load(file)

result_data = {}
dst_file_path = f'../result/{first}-{last}bits_cap{cap_first}-cap{cap_last}`_exclusive.json'
with open(dst_file_path, 'w') as file:
    json.dump({}, file, indent=4)

data["Cache"]["Rule"] = "../rules/wide.rib.20240625.1400.rule"  
# Refbitsを変更する
for refbits in range(first, last+1):
    
    tmp_file_path = '../simulator-settings/tmp.json'
    
    data["Cache"]["CacheLayers"][1]["Refbits"] = refbits
    
    for cache_nbit_cap in capacity:
        for  cache_32bit_cap in capacity:
            data["Cache"]["CacheLayers"][0]["Size"] = cache_32bit_cap
            data["Cache"]["CacheLayers"][1]["Size"] = cache_nbit_cap
            
        
            # 更新されたJSONデータをファイルに書き込む
            with open(tmp_file_path, 'w') as file:
                json.dump(data, file, indent=4)
            
            # シミュレータを実行する
            cmd = f'../main ../simulator-settings/tmp.json ../parsed-pcap/202406251400.p7'
            result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            _json_data = json.loads(result.stdout)
            
            partial_result_file = os.path.join(tmp_dir, f'tmp_result_{refbits}_{cache_32bit_cap}_{cache_nbit_cap}.json')
            with open(partial_result_file, 'w') as file:
                json.dump(_json_data, file, indent=4)
        else:
            print(f"cache 32bit cap: {cache_32bit_cap} Done")
    else:
        print(f"Cache nbit cap: {cache_nbit_cap} Done")
    print(f"Refbits: {refbits} Done")
else:
    # with open(dst_file_path, 'w') as file:
    #     json.dump(result_data, file, indent=4)
    #     print("Done")
    result_data = {}
    for refbits in range(first, last+1):
        result_data[refbits] = {}
        for cache_32bit_cap in capacity:
            result_data[refbits][cache_32bit_cap] = {}
            for cache_nbit_cap in capacity:
                partial_result_file = os.path.join(tmp_dir, f'tmp_result_{refbits}_{cache_32bit_cap}_{cache_nbit_cap}.json')
                with open(partial_result_file, 'r') as file:
                    _json_data = json.load(file)
                    result_data[refbits][cache_32bit_cap][cache_nbit_cap] = _json_data

    # 最終的な結果を一つの大きなファイルに書き込む
    with open(dst_file_path, 'w') as file:
        json.dump(result_data, file, indent=4)

    print("All Done")
