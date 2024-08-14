import json
import matplotlib.pyplot as plt
import numpy as np

# データの読み込み
filename = '10-24bits_exclusive.json'

src_file_path = f'../result/{filename}'
with open(src_file_path, 'r') as file:
    data = json.load(file)

# 各キャッシュの名前を取得
keys_to_extract = [16, 21, 24]
filtered_data = {str(key): data[str(key)] for key in keys_to_extract}
cache_names = list(filtered_data.keys())


# 比較用のデータを抽出
hit_rates = [filtered_data[name]['HitRate'] for name in cache_names]
refered = [filtered_data[name]['StatDetail']['Refered'] for name in cache_names]
replaced = [filtered_data[name]['StatDetail']['Replaced'] for name in cache_names]
hits = [filtered_data[name]['StatDetail']['Hit'] for name in cache_names]
match_map = [filtered_data[name]['StatDetail']['MatchMap'] for name in cache_names]
longest_match_map = [filtered_data[name]['StatDetail']['LongestMatchMap'] for name in cache_names]
depth_sum = [filtered_data[name]['StatDetail']['DepthSum'] for name in cache_names]
not_inserted = [filtered_data[name]['StatDetail']['NotInserted'] for name in cache_names]
# グラフの作成

fig, axs = plt.subplots(4, 2, figsize=(20, 40))

# ヒット率
axs[0, 0].bar(cache_names, hit_rates)
axs[0, 0].set_title('Hit Rate')
axs[0, 0].set_xticklabels(cache_names, rotation=45, ha='right')

# 参照された回数 (ヒストグラム)
width = 0.8 / len(cache_names)
x = np.arange(len(refered[0]))
for i, (name, ref) in enumerate(zip(cache_names, refered)):
    axs[0, 1].bar(x + i * width, ref, width=width, label=name)
axs[0, 1].set_title('Refered')
axs[0, 1].legend()
axs[0, 1].set_xticks(x + width * (len(cache_names) - 1) / 2)
axs[0, 1].set_xticklabels(x)

# 置き換えられた回数 (ヒストグラム)
x = np.arange(len(replaced[0]))
for i, (name, rep) in enumerate(zip(cache_names, replaced)):
    axs[1, 0].bar(x + i * width, rep, width=width, label=name)
axs[1, 0].set_title('Replaced')
axs[1, 0].legend()
axs[1, 0].set_xticks(x + width * (len(cache_names) - 1) / 2)
axs[1, 0].set_xticklabels(x)

# ヒット回数 (ヒストグラム)
x = np.arange(len(hits[0]))
for i, (name, hit) in enumerate(zip(cache_names, hits)):
    axs[1, 1].bar(x + i * width, hit, width=width, label=name)
axs[1, 1].set_title('Hit')
axs[1, 1].legend()
axs[1, 1].set_xticks(x + width * (len(cache_names) - 1) / 2)
axs[1, 1].set_xticklabels(x)

# MatchMap (ヒストグラム)
x = np.arange(len(match_map[0]))
for i, (name, mm) in enumerate(zip(cache_names, match_map)):
    axs[2, 0].bar(x + i * width, mm, width=width, label=name)
axs[2, 0].set_title('MatchMap')
axs[2, 0].legend()
axs[2, 0].set_xticks(x + width * (len(cache_names) - 1) / 2)
axs[2, 0].set_xticklabels(x)

# LongestMatchMap (ヒストグラム)
x = np.arange(len(longest_match_map[0]))
for i, (name, lmm) in enumerate(zip(cache_names, longest_match_map)):
    axs[2, 1].bar(x + i * width, lmm, width=width, label=name)
axs[2, 1].set_title('LongestMatchMap')
axs[2, 1].legend()
axs[2, 1].set_xticks(x + width * (len(cache_names) - 1) / 2)
axs[2, 1].set_xticklabels(x)

# DepthSum
axs[3, 0].bar(cache_names, depth_sum)
axs[3, 0].set_title('DepthSum')
axs[3, 0].set_xticklabels(cache_names, rotation=45, ha='right')

# NotInserted (ヒストグラム)
x = np.arange(len(not_inserted[0]))
for i, (name, ni) in enumerate(zip(cache_names, not_inserted)):
    axs[3, 1].bar(x + i * width, ni, width=width, label=name)
axs[3, 1].set_title('NotInserted')
axs[3, 1].legend()
axs[3, 1].set_xticks(x + width * (len(cache_names) - 1) / 2)
axs[3, 1].set_xticklabels(x)

# グラフのレイアウト調整
plt.tight_layout()
plt.savefig('../result/test.png')
