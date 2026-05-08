#!/usr/bin/env python3
"""
继续批量转换经典模式为导演模式 - 第二批次
专注于有较高质量分数的分组
"""

import json
import subprocess
import sys
import time

def get_high_quality_classic_groups(limit=20):
    """获取高质量的经典模式分组"""
    result = subprocess.run([
        'curl', '-s', 'http://localhost:8899/api/groups'
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        return []
    
    groups = json.loads(result.stdout)
    
    # 筛选条件：
    # 1. 经典模式
    # 2. 有剪辑内容
    # 3. 无质量问题（或轻微问题）
    # 4. 优先选择有分组标签的
    candidates = []
    for g in groups:
        if (g.get('editing_mode') == 'classic' and 
            g.get('clip_count', 0) > 0 and
            g.get('merge_status') == 2):  # 已合并完成
            
            # 计算优先级分数
            score = 0
            if g.get('quality_issue') is None:
                score += 10  # 无质量问题
            elif '时长超限' in g.get('quality_issue', ''):
                score += 5   # 时长超限可以通过导演模式优化
            
            if g.get('label') and len(g.get('label', '')) > 3:
                score += 5   # 有详细标签
            
            if g.get('published_count', 0) > 0:
                score += 3   # 已发布过，说明质量不错
                
            candidates.append((score, g))
    
    # 按分数排序，选择前N个
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [g for _, g in candidates[:limit]]

def switch_to_director_mode(group_id: int, label: str) -> bool:
    """切换分组为导演模式"""
    print(f"   🎬 切换分组 {group_id} 为导演模式...")
    result = subprocess.run([
        'curl', '-X', 'PUT', '-H', 'Content-Type: application/json',
        '-d', '{"editing_mode": "director"}',
        f'http://localhost:8899/api/groups/{group_id}'
    ], capture_output=True, text=True)
    
    return result.returncode == 0

def main():
    print("🎭 开始第二批次导演模式转换...")
    print("🎯 专注转换高质量、无问题的经典模式分组\n")
    
    groups = get_high_quality_classic_groups(15)  # 限制15个避免过载
    
    if not groups:
        print("❌ 未找到合适的转换候选分组")
        return
    
    print(f"📊 找到 {len(groups)} 个高质量候选分组")
    
    converted = 0
    for i, group in enumerate(groups, 1):
        group_id = group['id']
        label = group.get('label', f'分组{group_id}')
        quality = group.get('quality_issue', '✅ 无问题')
        clip_count = group.get('clip_count', 0)
        
        print(f"\n[{i}/{len(groups)}] 转换分组 {group_id}: {label}")
        print(f"   📊 剪辑数: {clip_count}, 质量: {quality}")
        
        if switch_to_director_mode(group_id, label):
            print(f"   ✅ 成功转换为导演模式")
            converted += 1
        else:
            print(f"   ❌ 转换失败")
        
        # 避免API过载
        time.sleep(1)
    
    print(f"\n🎉 第二批次转换完成!")
    print(f"📈 成功转换 {converted}/{len(groups)} 个分组为导演模式")
    print(f"📋 当前系统应该有约 {3 + converted} 个导演模式分组")
    print("\n💡 建议：")
    print("   1. 等待当前185个剪辑队列任务完成")
    print("   2. 检查导演模式剪辑效果")
    print("   3. 根据效果决定是否继续批量转换")

if __name__ == "__main__":
    main()