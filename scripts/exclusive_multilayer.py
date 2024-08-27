import os
import subprocess
import copy
import concurrent.futures
import json

# JSONファイルのパス
src_file_path = '../simulator-settings/MultiLayerCacheExclusive.json'
first = 1
last = 1

cap_first = 64 * 2
cap_last = int(4096 /2)
interval =64 * 2
capacity = [i for i in range(cap_first,cap_last+1,interval)] # 64から4096


# JSONファイルを読み込む
# todo 読み込まなくても自分で型定義して、データを作成すればいい
with open(src_file_path, 'r') as file:
    cache_settings:dict = json.load(file)

cache_settings["Rule"] = "../rules/wide.rib.20240625.1400.rule"
cache_settings["DebugMode"] = "false"
cache_settings["Interval"]  = 10000000000000
# Refbitsを変更する
cmd = "go build ../main.go"
result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def make_tmp_setting_file(cache_settings,refbits, cache_32bit_cap, cache_nbit_cap):
    tmp_setting_file_path = f'../simulator-settings/tmp/tmp_{refbits}_{cache_32bit_cap}_{cache_nbit_cap}.json'
    cache_settings["Cache"]["CacheLayers"][1]["Refbits"] = refbits
    cache_settings["Cache"]["CacheLayers"][0]["Size"] = cache_32bit_cap
    cache_settings["Cache"]["CacheLayers"][1]["Size"] = cache_nbit_cap
    # 更新されたJSONデータをファイルに書き込む
    with open(tmp_setting_file_path, 'w') as file:
        json.dump(cache_settings, file, indent=4)
    return tmp_setting_file_path

def calc_hit_rate(cache_settings,refbits, cache_32bit_cap, cache_nbit_cap):
    tmp_dir = '../result/tmp_results'

    tmp_setting_file_path = make_tmp_setting_file(cache_settings,refbits, cache_32bit_cap, cache_nbit_cap)
    tmp_dir_refbits = os.path.join(tmp_dir, f'{refbits}')
    if(os.path.exists(tmp_dir_refbits) == False):
        print(f"Create directory: {tmp_dir_refbits}")
        os.makedirs(tmp_dir_refbits)


    partial_result_file = os.path.join(tmp_dir_refbits, f'tmp_result_{cache_32bit_cap}_{cache_nbit_cap}.json')
    if(os.path.exists(partial_result_file) == True):
        print(f"Refbits: {refbits}, Cache 32bit cap: {cache_32bit_cap}, Cache nbit cap: {cache_nbit_cap}, Skipped")
        return 0

    print(f"Refbits: {refbits}, Cache 32bit cap: {cache_32bit_cap}, Cache nbit cap: {cache_nbit_cap}, Start")
    # シミュレータを実行する
    cmd = f'./main {tmp_setting_file_path} ../parsed-pcap/202406251400.p7'
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print(result.stdout)
    _json_data = json.loads(result.stdout)
    with open(partial_result_file, 'w') as file:
        json.dump(_json_data, file, indent=4)
    print(f"Refbits: {refbits}, Cache 32bit cap: {cache_32bit_cap}, Cache nbit cap: {cache_nbit_cap}, Done")
    return 0

# refbitsごとにまとめよう
def aggregate_result(refbits,cache_32bit_cap, cache_nbit_cap):
    result_data = {}
    tmp_dir = '../result/tmp_results'
    tmp_dir_refbits = os.path.join(tmp_dir, f'{refbits}')

    result_data[refbits] = {}
    for cache_32bit_cap in capacity:
        result_data[refbits][cache_32bit_cap] = {}
        for cache_nbit_cap in capacity:
            partial_result_file = os.path.join(tmp_dir_refbits, f'tmp_result_{cache_32bit_cap}_{cache_nbit_cap}.json')
            with open(partial_result_file, 'r') as file:
                _json_data = json.load(file)
                result_data[refbits][cache_32bit_cap][cache_nbit_cap] = _json_data
    dst_file_path = f'../result/{refbits}bits_cap{cap_first}-cap{cap_last}-interval{interval}-exclusive.json'

    # 最終的な結果を一つの大きなファイルに書き込む
    with open(dst_file_path, 'w') as file:
        json.dump(result_data, file, indent=4)

    return 0



def process_cache_settings(refbits, cache_nbit_cap, cache_32bit_cap, cache_settings):
    copy_cache_settings = copy.deepcopy(cache_settings)
    calc_hit_rate(copy_cache_settings, refbits, cache_32bit_cap, cache_nbit_cap)
    return cache_32bit_cap, cache_nbit_cap, refbits

with concurrent.futures.ThreadPoolExecutor() as executor:
    futures = []
    for refbits in range(first, last + 1):
        for cache_nbit_cap in capacity:
            for cache_32bit_cap in capacity:
                futures.append(
                    executor.submit(process_cache_settings, refbits, cache_nbit_cap, cache_32bit_cap, cache_settings)
                )

    for future in concurrent.futures.as_completed(futures):
        cache_32bit_cap, cache_nbit_cap, refbits = future.result()


result_data = {}
for refbits in range(first, last+1):
    aggregate_result(refbits,cache_32bit_cap, cache_nbit_cap)
else:
    print("Done")
