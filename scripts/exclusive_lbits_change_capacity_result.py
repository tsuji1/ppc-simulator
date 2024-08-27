import os
import json
import matplotlib.pyplot as plt
from models.MultiLayerCacheExclusive import MultiLayerCacheExclusive

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

for refbits in refbits_list:
    for cache_32bit_cap in capacity:
        for cache_nbit_cap in capacity:
            d = data[refbits][cache_32bit_cap][cache_nbit_cap]
            parsed_d = MultiLayerCacheExclusive(d)
            hitrate = parsed_d.HitRate
            hitrate_dict[refbits].append((cache_32bit_cap, cache_nbit_cap, hitrate))



def show_hitrate(hitrate_d):
    # max hitrate
    max_hitrate:float= 0
    max_hitrate_refbits:int = 0
    max_hitrate_c32:int = 0
    max_hitrate_cn = 0
    max_hitrate_with_restrict =[0,0,0,0]
    k = 1024/3
    for refbits, hitrate_data in hitrate_d.items():
        for c32, cn, h in hitrate_data:
            if h > max_hitrate:
                max_hitrate = float(h)
                max_hitrate_refbits = int(refbits)
                max_hitrate_c32 = int(c32)
                max_hitrate_cn = int(cn)
            if max_hitrate_with_restrict[0] < float(h) and int(c32)+int(cn) <= k:
                max_hitrate_with_restrict = [float(h), int(refbits), int(c32), int(cn)]
            if(int(c32)==16 and 1024 == int(cn) and refbits == '24'):
                print(f"refbits={refbits}, c32={c32}, cn={cn}, hitrate={h}")
                
    print(f"Max HitRate: {max_hitrate} (refbits={max_hitrate_refbits}, c32={max_hitrate_c32}, cn={max_hitrate_cn})")
    print(f"Max HitRate with restriction: {max_hitrate_with_restrict[0]} (refbits={max_hitrate_with_restrict[1]}, c32={max_hitrate_with_restrict[2]}, cn={max_hitrate_with_restrict[3]})")
    return max_hitrate
    


# グラフ描画
def plot_graph_all(hitrate_d):
    for refbits, hitrate_data in hitrate_d.items():
        labels = [f"{c32}-{cn}" for c32, cn, _ in hitrate_data]
        hitrates = [h for _, _, h in hitrate_data]

        plt.figure(figsize=(20, 8))
        plt.bar(labels, hitrates, color='blue')
        plt.xlabel('Configurations (/32キャッシュサイズ-/nビットキャッシュサイズ)',fontname ='Noto Sans CJK JP')
        plt.ylabel('HitRate')
        plt.title(f'HitRate for Different Cache Configurations (refbits={refbits})')
        plt.ylim(0.6, 1.0)
        plt.xticks(rotation=45, ha='right', fontsize=8,position=(0.5, 0))  # ラベルを45度回転させ、フォントサイズを小さくする
        plt.tight_layout()
        plt.savefig(f'../result/{src_file_name[:-5]}_refbits{refbits}_hitrate.png')
# plot_graph_all(hitrate_dict)
max_hitrate = show_hitrate(hitrate_dict)
