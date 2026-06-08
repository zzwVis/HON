import pandas as pd
import pickle

# 读取Excel文件（你的新数据）
# 假设你的新数据在 'new_data.xlsx' 文件中
df = pd.read_excel('semantic_agavue_50.xlsx')

# 按id分组，并按position排序（position代表时间顺序）
grouped = df.sort_values(['id', 'position']).groupby('id')

# 构建每个id的raw_event序列（作为列表）
sequences_list = []
for id_val, group in grouped:
    # 获取该组的所有raw_event，作为列表
    raw_events_list = group['event'].tolist()
    sequences_list.append(raw_events_list)

# 将结果写入pkl文件（列表的列表）
with open('semantic_agavue_50.pkl', 'wb') as f:
    pickle.dump(sequences_list, f)

# 查看前10个序列
print("前10个序列：")
print("-" * 50)
for i, sequence in enumerate(sequences_list[:10]):  # 只取前10个
    print(f"序列 {i+1}: {sequence}")
print("-" * 50)
print(f"总共处理了 {len(sequences_list)} 个序列，这里显示了前10个")

# 可选：如果还需要保存原始数据帧
# with open('full_data_new.pkl', 'wb') as f:
#     pickle.dump(df, f)