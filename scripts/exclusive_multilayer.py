import os
import subprocess
import copy
import concurrent.futures
import json
import time
import logging
from datetime import datetime

# 現在の日付と時刻を取得
now = datetime.now()
date_str = now.strftime("%Y%m%d")  # 年月日を YYYYMMDD 形式で取得
time_str = now.strftime("%H%M")    # 時間と分を HHMM 形式で取得
# ログファイル名を指定された形式で作成

# 保存先のディレクトリを指定
log_dir = "logs/muti_refbits"
os.makedirs(log_dir, exist_ok=True)  # ディレクトリが存在しない場合は作成する

log_filename = f"exclusive_ch_cap{date_str}-{time_str}.log"

log_file_path = os.path.join(log_dir, log_filename)

# ロギングの設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filename=log_file_path, filemode='w')

# JSONファイルのパス
src_file_path = '../simulator-settings/template_3layer_capacity.json'
first = 16
last = 24

cap_first = 64 
cap_last = 64 * 20
interval =64 

# cap_first = 64 * 4
# cap_last = 64 * 20
# interval =64 * 4
capacity = [i for i in range(cap_first,cap_last+1,interval)] # 64から4096
layer1_capacity = copy.copy(capacity)
layer2_capacity = copy.copy(capacity)
layer3_capacity = copy.copy(capacity)
layer1_capacity.append(1)


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

# 大きいほうから小さいほうにrefbitsはかく

def _make_join(refbits,cache_capacity):
    refbits_string = "-".join([str(i) for i in refbits])
    cache_capacity_string = "-".join([str(i) for i in cache_capacity])
    return f"{refbits_string}_{cache_capacity_string}"
def make_tmp_file_path(base_dir, refbits, cache_capacity):
    joined = _make_join(refbits,cache_capacity)
    p = os.path.join(base_dir , f'tmp_{joined}.json')
    return p
def make_tmp_setting_file(cache_settings,refbits:list[int], cache_capacity:list[int]):
    if(len(refbits) != len(cache_capacity)):
        print("Refbits and cache_capacity must be the same length")
        logging.error("Refbits and cache_capacity must be the same length")
        raise ValueError("Refbits and cache_capacity must be the same length")
    tmp_setting_file_path = make_tmp_file_path('../simulator-settings/tmp',refbits,cache_capacity)
    print(refbits)
    for i,_ in enumerate(refbits):
        cache_settings["Cache"]["CacheLayers"][i]["Refbits"] = refbits[i]
        cache_settings["Cache"]["CacheLayers"][i]["Size"] = cache_capacity[i]
    # 更新されたJSONデータをファイルに書き込む
    with open(tmp_setting_file_path, 'w') as file:
        json.dump(cache_settings, file, indent=4)
    return tmp_setting_file_path

def calc_hit_rate(cache_settings,refbits:list[int], cache_capacity:list[int]):
    tmp_dir = '../result/tmp_results'

    tmp_setting_file_path = make_tmp_setting_file(cache_settings,refbits,cache_capacity)
    refbits_string = "-".join([str(i) for i in refbits])
    tmp_dir_refbits = os.path.join(tmp_dir, f'{refbits_string}')
    if(os.path.exists(tmp_dir_refbits) == False):
        print(f"Create directory: {tmp_dir_refbits}")
        os.makedirs(tmp_dir_refbits)


    partial_result_file = make_tmp_file_path(tmp_dir_refbits,refbits,cache_capacity)
    if(os.path.exists(partial_result_file) == True):
        print(f"Refbits: {refbits}, Cache Capacity: {cache_capacity}, Skipped")
        return 2
    
    print(f"Refbits: {refbits}, Cache Capacity: {cache_capacity}, Start")
    # シミュレータを実行する
    
    cmd = f'./main -cacheparam {tmp_setting_file_path} -trace ../parsed-pcap/202406251400.p7'
    print(cmd)
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print(result.returncode)
    _json_data = json.loads(result.stdout)
    with open(partial_result_file, 'w') as file:
        json.dump(_json_data, file, indent=4)
    print(f"Refbits: {refbits}, Cache capacity: {cache_capacity}, Done")
    return 0

# refbitsごとにまとめよう
def aggregate_result(refbits,cache_32bit_capacity, cache_nbit_capacity):
    result_data = {}
    tmp_dir = '../result/tmp_results'
    tmp_dir_refbits = os.path.join(tmp_dir, f'{refbits}')

    result_data[refbits] = {}
    for cache_32bit_cap in cache_32bit_capacity:
        result_data[refbits][cache_32bit_cap] = {}
        for cache_nbit_cap in cache_nbit_capacity:
            partial_result_file = os.path.join(tmp_dir_refbits, f'tmp_result_{cache_32bit_cap}_{cache_nbit_cap}.json')
            with open(partial_result_file, 'r') as file:
                _json_data = json.load(file)
                result_data[refbits][cache_32bit_cap][cache_nbit_cap] = _json_data
    dst_file_path = f'../result/{refbits}bits_cap{cap_first}-cap{cap_last}-interval{interval}-exclusive.json'

    # 最終的な結果を一つの大きなファイルに書き込む
    with open(dst_file_path, 'w') as file:
        json.dump(result_data, file, indent=4)

    return 0



def process_cache_settings(refbits:list[int], cache_capacity:list[int],cache_settings):
    copy_cache_settings = copy.deepcopy(cache_settings)
    copy_refbits = copy.copy(refbits)
    
    copy_cache_capacity = copy.copy(cache_capacity)
    copy_refbits.insert(0,32)
    v = calc_hit_rate(copy_cache_settings, copy_refbits,copy_cache_capacity)
    return copy_cache_capacity, copy_refbits,v


refbits = [i for i in range(first, last + 1)]

with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:

            start_time = time.time()
            
            # print(f"Refbits: {refbits} Start")
            # logging.info(f"Refbits: {refbits} Start")
            futures = []
            # 現在のrefbitsに対するキャッシュ設定の組み合わせを非同期に処理
            for refbits_layer2 in range(first, last + 1): # layer 2
                for refbits_layer3 in range(first, refbits_layer2):
                    refbits = [refbits_layer2,refbits_layer3]
                    for l1c in layer1_capacity:
                        for l2c in layer2_capacity:
                            if(l1c == 1 and refbits_layer2 != 24):
                                # 1bitのキャッシュは24bitのrefbitsの時だけ
                                continue
                            for l3c in layer3_capacity:
                                
                                cache_capacity = [l1c,l2c,l3c]
                                if(sum(cache_capacity) != 1024 and  sum(cache_capacity) != 1025 ):
                                    continue  
                                futures.append(
                                    executor.submit(process_cache_settings, refbits, cache_capacity, cache_settings)
                                )
            total = len(futures)
            completed = 0
            not_skipped_completed = 0

            # 現在のrefbitsに対するすべての処理が完了するまで待機
            for future in concurrent.futures.as_completed(futures):
                # try:
                cache_capacity, refbits ,v= future.result()
    
                completed += 1
                percentage = (completed / total) * 100  # 完了割合を計算
                
                print(f"Completed: {completed}/{total} ({percentage:.1f}%)")
                logging.info(f"Completed: {completed}/{total} ({percentage:.1f}%)")
                if(v == 0):
                    not_skipped_completed += 1
                    now = time.time()
                    avg_time = (now - start_time) / not_skipped_completed
                    print(f"Average time to deal with one simulation: {avg_time} second")
                    logging.info(f"Average time to deal with one simulation {avg_time} second")
                # except Exception as e:
                #     print(f"An error occurred: {e}")
                #     logging.error(f"An error occurred: {e}")
            end_time = time.time()
            elapsed_time = end_time - start_time;
            # すべての処理が完了した時点で次のrefbitsに進む
            print(f"All tasks for refbits={refbits} completed.")
            print(f"Elapsed time: {elapsed_time:.2f} seconds")
            logging.info(f"All tasks for refbits={refbits} completed.")
            logging.info(f"Elapsed time: {elapsed_time:.2f} seconds")
            # aggregate_result(refbits,cache_capacity)

