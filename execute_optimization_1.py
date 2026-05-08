#!/usr/bin/env python3
"""
立即执行：批量转换50个高质量分组为导演模式
基于数据驱动的智能选择算法
"""

import json
import subprocess
import sqlite3
import time

def get_high_value_groups(limit=50):
    """基于多维度评分选择高价值分组"""
    
    result = subprocess.run([
        'curl', '-s', 'http://localhost:8899/api/groups'
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        return []
    
    groups = json.loads(result.stdout)
    candidates = []
    
    for g in groups:
        if (g.get('editing_mode') != 'director' and 
            g.get('clip_count', 0) > 0 and
            g.get('merge_status') == 2):
            
            # 多维度评分算法
            score = 0
            
            # 1. 质量分 (40%)
            if g.get('quality_issue') is None:
                score += 40
            elif '时长超限' in str(g.get('quality_issue', '')):
                score += 20  # 导演模式可以优化
            
            # 2. 发布表现分 (30%)
            published_count = g.get('published_count', 0)
            if published_count > 0:
                score += min(30, published_count * 10)
            
            # 3. 内容丰富度分 (20%)
            label = g.get('label', '')
            if label and len(label) > 5:
                score += 15
            if any(keyword in label for keyword in ['色', '款', '发', '卷', '直']):
                score += 5
            
            # 4. 数据完整性分 (10%)
            if g.get('room_name'):
                score += 5
            if g.get('merged_filename'):
                score += 5
            
            candidates.append((score, g))
    
    # 按分数排序，返回前N个
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [g for _, g in candidates[:limit]]

def batch_convert_to_director(groups):
    """批量转换为导演模式"""
    
    print(f"🚀 开始批量转换 {len(groups)} 个高价值分组为导演模式...\n")
    
    # 数据库批量更新
    group_ids = [g['id'] for g in groups]
    
    conn = sqlite3.connect('douyin.db')
    cursor = conn.cursor()
    
    converted = 0
    for i, group in enumerate(groups, 1):
        group_id = group['id']
        label = group.get('label', f'分组{group_id}')
        score = 0  # 重新计算分数用于显示
        
        # 计算显示分数
        if group.get('quality_issue') is None:
            score += 40
        if group.get('published_count', 0) > 0:
            score += 30
        if len(group.get('label', '')) > 5:
            score += 20
        
        print(f"[{i:2d}/50] 转换分组 {group_id}: {label}")
        print(f"        评分: {score}/90, 已发布: {group.get('published_count', 0)}次")
        
        cursor.execute('UPDATE clip_groups SET editing_mode = ? WHERE id = ?', ('director', group_id))
        if cursor.rowcount > 0:
            converted += 1
            print(f"        ✅ 转换成功")
        else:
            print(f"        ❌ 转换失败")
        
        # 避免过载
        if i % 10 == 0:
            conn.commit()
            time.sleep(0.5)
    
    conn.commit()
    conn.close()
    
    return converted

def verify_conversion():
    """验证转换结果"""
    result = subprocess.run([
        'curl', '-s', 'http://localhost:8899/api/groups'
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        groups = json.loads(result.stdout)
        director_count = len([g for g in groups if g.get('editing_mode') == 'director'])
        total_count = len(groups)
        coverage = director_count / total_count * 100
        
        return director_count, total_count, coverage
    
    return 0, 0, 0

def main():
    print("🎯 立即执行优化行动1: 批量转换高价值分组")
    print("=" * 60)
    
    # 获取当前状态
    print("📊 获取高价值候选分组...")
    groups = get_high_value_groups(50)
    
    if not groups:
        print("❌ 未找到合适的转换候选")
        return
    
    print(f"✅ 找到 {len(groups)} 个高价值分组")
    
    # 显示前5个作为预览
    print(f"\n🔍 转换预览 (前5个):")
    for i, g in enumerate(groups[:5], 1):
        published = g.get('published_count', 0)
        quality = g.get('quality_issue', '✅ 无问题')
        print(f"  {i}. 分组{g['id']}: {g.get('label', '未知')} (发布{published}次, {quality})")
    
    # 确认转换
    print(f"\n🚀 开始转换...")
    converted = batch_convert_to_director(groups)
    
    # 验证结果
    director_count, total_count, coverage = verify_conversion()
    
    print(f"\n🎉 批量转换完成!")
    print(f"📈 转换结果:")
    print(f"  本次成功转换: {converted} 个分组")
    print(f"  导演模式总数: {director_count} 个分组")
    print(f"  新的覆盖率: {coverage:.1f}%")
    print(f"  提升幅度: +{coverage-1.3:.1f}%")
    
    if coverage > 5.0:  # 如果覆盖率超过5%
        print(f"\n🎊 里程碑达成！导演模式覆盖率突破5%")
        print(f"💡 建议下一步: 为这{director_count}个分组生成AI剧本")

if __name__ == "__main__":
    main()