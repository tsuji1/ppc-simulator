import uuid


# ファイルパス
input_file_path = '../rules/wide.rib.20240625.1400.rule'
output_file_path = '../rules/wide.rib.20240625.1400.unique.rule'

# 元のデータを読み出す
with open(input_file_path, 'r') as file:
    data = file.readlines()

# 新しいファイル用のリスト
new_data = []

# 1行目の重複をまとめるための辞書
summary = {}

# 1行目と2行目を基に3行目をランダムにするための処理
for line in data:
    parts = line.strip().split()
    if len(parts) != 3:
        continue
    
    key = f"{parts[0]} {parts[1]}"
    
    # 1行目のまとめ処理
    if key not in summary:
        summary[key] = []
    
    # 3行目をランダムに一意化する
    random_value = str(uuid.uuid4())
    summary[key].append(random_value)

# まとめたデータを新しいファイル形式で書き出す
for key, values in summary.items():
    for value in values:
        new_data.append(f"{key} {value}")

# 新しいファイルの書き出し
with open(output_file_path, 'w') as f:
    for line in new_data:
        f.write(line + '\n')

print(f"新しいファイル '{output_file_path}' が生成されました。")
