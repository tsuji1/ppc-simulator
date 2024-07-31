import os
import subprocess


import json

# JSONファイルのパス
src_file_path = '../simulator-settings/MultiLayerCacheExclusive.json'
first = 0
last = 32
# JSONファイルを読み込む
with open(src_file_path, 'r') as file:
    data:dict = json.load(file)

result_data = {}
dst_file_path = f'../result/{first}-{last}bits_exclusive.json'
with open(dst_file_path, 'w') as file:
    json.dump({}, file, indent=4)

data["Cache"]["Rule"] = "../rules/wide.rib.20240625.1400.rule"  
# Refbitsを変更する
for refbits in range(first, last+1):
    tmp_file_path = '../simulator-settings/tmp.json'
    
    for layer in data["Cache"]["CacheLayers"]:
        if layer["Type"] == "FullAssociativeDstipNbitLRUCache":
            if layer["Size"] == 256:
                layer["Refbits"] = refbits  # 変更する値


    # 更新されたJSONデータをファイルに書き込む
    with open(tmp_file_path, 'w') as file:
        json.dump(data, file, indent=4)
    
    # シミュレータを実行する
    cmd = f'../main ../simulator-settings/tmp.json ../parsed-pcap/202406251400.p7'
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _json_data = json.loads(result.stdout)
    result_data[refbits] = _json_data
    print(f"Refbits: {refbits} Done")
else:
    with open(dst_file_path, 'w') as file:
        json.dump(result_data, file, indent=4)
        print("Done")
