import os
import subprocess
import copy
import concurrent.futures
import json
import time
import logging
from datetime import datetime
import traceback

# 現在の日付と時刻を取得
now = datetime.now()
date_str = now.strftime("%Y%m%d")  # 年月日を YYYYMMDD 形式で取得
time_str = now.strftime("%H%M")    # 時間と分を HHMM 形式で取得
# ログファイル名を指定された形式で作成

# 保存先のディレクトリを指定
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)  # ディレクトリが存在しない場合は作成する

log_filename = f"exclusive_ch_cap{date_str}-{time_str}.log"

log_file_path = os.path.join(log_dir, log_filename)

# ロギングの設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filename=log_file_path, filemode='w')

# JSONファイルのパス
src_file_path = '../simulator-settings/template_2layer_capacity.json'
first = 16
last = 24

cap_first = 64 
cap_last = int(4096 /4)
interval =64 
capacity = [i for i in range(cap_first,cap_last+1,interval)] # 64から4096
capacity_nbits = copy.copy(capacity)
capacity_32bits = copy.copy(capacity)
capacity_32bits.append(1)


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

# キャッシュのヒット率を計算する ,updateは基本Falseであり、ファイルを更新したい場合はTrueにする
def calc_hit_rate(cache_settings,refbits, cache_32bit_cap, cache_nbit_cap,update):
    tmp_dir = '../result/tmp_results'

    tmp_setting_file_path = make_tmp_setting_file(cache_settings,refbits, cache_32bit_cap, cache_nbit_cap)
    tmp_dir_refbits = os.path.join(tmp_dir, f'{refbits}')
    if(os.path.exists(tmp_dir_refbits) == False):
        print(f"Create directory: {tmp_dir_refbits}")
        os.makedirs(tmp_dir_refbits)


    partial_result_file = os.path.join(tmp_dir_refbits, f'tmp_result_{cache_32bit_cap}_{cache_nbit_cap}.json')
    if(os.path.exists(partial_result_file) == True and update == False):
        print(f"Refbits: {refbits}, Cache 32bit cap: {cache_32bit_cap}, Cache nbit cap: {cache_nbit_cap}, Skipped")
        return 2

    print(f"Refbits: {refbits}, Cache 32bit cap: {cache_32bit_cap}, Cache nbit cap: {cache_nbit_cap}, Start")
    # シミュレータを実行する
    cmd = f'./main -cacheparam {tmp_setting_file_path} -trace ../parsed-pcap/202406251400.p7'
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _json_data = json.loads(result.stdout)
    with open(partial_result_file, 'w') as file:
        json.dump(_json_data, file, indent=4)
    print(f"Refbits: {refbits}, Cache 32bit cap: {cache_32bit_cap}, Cache nbit cap: {cache_nbit_cap}, Done")
    return 0



def process_cache_settings(refbits, cache_nbit_cap, cache_32bit_cap, cache_settings,update=False):
    copy_cache_settings = copy.deepcopy(cache_settings)
    v = calc_hit_rate(copy_cache_settings, refbits, cache_32bit_cap, cache_nbit_cap,update)
    return cache_32bit_cap, cache_nbit_cap, refbits,v
try:
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        for refbits in range(first, last + 1):
            start_time = time.time()
            print(f"Refbits: {refbits} Start")
            logging.info(f"Refbits: {refbits} Start")
            futures = []
            total = len(capacity) * len(capacity)
            completed = 0
            not_skipped_completed = 0
            update = True
            # 現在のrefbitsに対するキャッシュ設定の組み合わせを非同期に処理
            for cache_nbit_cap in capacity_nbits:
                for cache_32bit_cap in capacity_32bits:
                    futures.append(
                        executor.submit(process_cache_settings, refbits, cache_nbit_cap, cache_32bit_cap, cache_settings,update=False)
                    )
            # 現在のrefbitsに対するすべての処理が完了するまで待機
            for future in concurrent.futures.as_completed(futures):
                try:
                    excpectation = future.exception()
                    print(f"Exception: {excpectation}")
                    cache_32bit_cap, cache_nbit_cap, refbits ,v= future.result()
                    print(f"Refbits: {refbits}, Cache 32bit cap: {cache_32bit_cap}, Cache nbit cap: {cache_nbit_cap}, Result: {v}")
        
                    completed += 1
                    percentage = (completed / total) * 100  # 完了割合を計算
                    
                    print(f"Refbits: {refbits} Completed: {completed}/{total} ({percentage:.1f}%)")
                    logging.info(f"Refbits: {refbits} Completed: {completed}/{total} ({percentage:.1f}%)")
                    if(v == 0):
                        not_skipped_completed += 1
                        now = time.time()
                        avg_time = (now - start_time) / not_skipped_completed
                        print(f"Average time to deal with one simulation: {avg_time} second")
                        logging.info(f"Average time to deal with one simulation {avg_time} second")
                except Exception as e:
                    print(f"An error occurred: {e}")
                    logging.error(f"An error occurred: {e}")
                    # error_msg = ''.join(traceback.format_expection(None,e,e.__traceback__))
                    # print(f"Traceback:{error_msg}")
                    # logging.error(f"Traceback:{error_msg}")
            end_time = time.time()
            elapsed_time = end_time - start_time;
            # すべての処理が完了した時点で次のrefbitsに進む
            print(f"All tasks for refbits={refbits} completed.")
            print(f"Elapsed time: {elapsed_time:.2f} seconds")
            logging.info(f"All tasks for refbits={refbits} completed.")
            logging.info(f"Elapsed time: {elapsed_time:.2f} seconds")
            # aggregate_result(refbits,capacity, capacity)

except Exception as e:
    print(f"A general error occurred: {e}")
    logging.error(f"A general error occurred: {e}")
