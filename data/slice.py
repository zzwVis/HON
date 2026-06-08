import pandas as pd
import os


def filter_sequences(input_path, output_path, min_length=10, max_length=200, max_ids=None):
    """
    保留序列长度在指定范围内的id，并可选择最多保留多少个id

    Parameters:
    input_path: 输入文件路径
    output_path: 输出文件路径
    min_length: 最小序列长度
    max_length: 最大序列长度
    max_ids: 最多保留多少个id（None表示保留所有符合条件的id）
    """
    try:
        # 读取Excel文件
        print(f"正在读取文件: {input_path}")
        df = pd.read_excel(input_path)

        # 统计每个id的事件数量（序列长度）
        event_counts = df.groupby('id').size().reset_index(name='sequence_length')

        # 先筛选序列长度在范围内的id
        valid_ids_df = event_counts[
            (event_counts['sequence_length'] >= min_length) &
            (event_counts['sequence_length'] <= max_length)
            ]

        # 如果指定了最多保留多少条，则按序列长度降序排序后取前N个
        if max_ids is not None and len(valid_ids_df) > max_ids:
            valid_ids_df = valid_ids_df.sort_values('sequence_length', ascending=False).head(max_ids)
            selection_method = f"按序列长度降序取前{max_ids}个"
        else:
            selection_method = f"保留所有符合条件的{len(valid_ids_df)}个id"

        # 获取最终要保留的id列表
        filtered_ids = valid_ids_df['id'].tolist()

        # 筛选数据
        df_filtered = df[df['id'].isin(filtered_ids)]

        # 根据输出文件扩展名选择保存格式
        if output_path.endswith('.xlsx'):
            df_filtered.to_excel(output_path, index=False, engine='openpyxl')
        elif output_path.endswith('.csv'):
            df_filtered.to_csv(output_path, index=False, encoding='utf-8')
        else:
            df_filtered.to_csv(output_path, sep='\t', index=False, encoding='utf-8')

        # 输出统计信息
        print("\n" + "=" * 60)
        print("处理完成！")
        print("=" * 60)
        print(f"原始数据:")
        print(f"  - 唯一id总数: {df['id'].nunique():,}")
        print(f"  - 总事件数: {len(df):,}")

        print(f"\n序列长度筛选条件:")
        print(f"  - 范围: {min_length} ≤ 长度 ≤ {max_length}")
        print(f"  - 符合条件的id数: {len(valid_ids_df):,} 个")

        print(f"\nid筛选方式:")
        print(f"  - {selection_method}")

        print(f"\n最终结果:")
        print(f"  - 保留的id数: {len(filtered_ids):,}")
        print(f"  - 保留的事件数: {len(df_filtered):,}")
        print(f"  - 保留比例: {len(df_filtered) / len(df) * 100:.2f}%")

        # 显示序列长度统计
        if len(filtered_ids) > 0:
            retained_lengths = event_counts[event_counts['id'].isin(filtered_ids)]['sequence_length']
            print(f"\n保留的id序列长度统计:")
            print(f"  - 最小长度: {retained_lengths.min()}")
            print(f"  - 最大长度: {retained_lengths.max()}")
            print(f"  - 平均长度: {retained_lengths.mean():.2f}")
            print(f"  - 中位数长度: {retained_lengths.median():.0f}")

        print(f"\n文件已保存到: {output_path}")

        # 可选：保存统计信息到单独文件
        stats_path = output_path.replace('.xlsx', '_stats.xlsx').replace('.tsv', '_stats.tsv').replace('.csv',
                                                                                                       '_stats.csv')
        valid_ids_df.to_csv(stats_path, index=False, encoding='utf-8-sig')
        print(f"统计信息已保存到: {stats_path}")

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


def main():
    """
    主函数 - 可以根据需要修改参数
    """
    # 设置文件路径
    input_file = r'semantic_agavue_full.xlsx'  # 修改为你的实际文件名
    output_file = r'semantic_agavue_50.xlsx'

    # ========== 在这里修改你的筛选参数 ==========
    MIN_LENGTH = 10  # 最小序列长度
    MAX_LENGTH = 40  # 最大序列长度
    MAX_IDS = 50  # 最多保留多少个id（设置为None表示不限制）
    # ========================================

    # 执行筛选
    filter_sequences(
        input_path=input_file,
        output_path=output_file,
        min_length=MIN_LENGTH,
        max_length=MAX_LENGTH,
        max_ids=MAX_IDS
    )


if __name__ == "__main__":
    main()