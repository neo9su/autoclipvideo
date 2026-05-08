#!/usr/bin/env python3
"""
批量将经典模式转换为导演模式的工具
1. 转换现有经典模式分组为导演模式
2. 重新剪辑时长不足的分组
3. 合并短片段达到时长要求
"""

import json
import subprocess
import sys
import time
from typing import List, Dict

def get_groups_data() -> List[Dict]:
    """获取所有分组数据"""
    result = subprocess.run([
        'curl', '-s', 'http://localhost:8899/api/groups'
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        return json.loads(result.stdout)
    else:
        print(f"获取分组数据失败: {result.stderr}")
        return []

def switch_to_director_mode(group_id: int) -> bool:
    """将分组切换为导演模式"""
    result = subprocess.run([
        'curl', '-X', 'PUT', '-H', 'Content-Type: application/json',
        '-d', '{"editing_mode": "director"}',
        f'http://localhost:8899/api/groups/{group_id}'
    ], capture_output=True, text=True)
    
    return result.returncode == 0

def generate_director_script(group_id: int) -> bool:
    """为分组生成导演剧本"""
    result = subprocess.run([
        'curl', '-X', 'POST', 
        f'http://localhost:8899/api/v2/director/groups/{group_id}/generate-script'
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        response = json.loads(result.stdout)
        return response.get('success', False)
    return False

def retry_clip_with_director_mode(group_id: int, recording_ids: List[int]) -> bool:
    """使用导演模式重新剪辑"""
    success_count = 0
    for recording_id in recording_ids:
        result = subprocess.run([
            'curl', '-X', 'POST',
            f'http://localhost:8899/api/recordings/{recording_id}/retry-clip'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            response = json.loads(result.stdout)
            if 'recording_id' in response:
                success_count += 1
                print(f"  ✅ Recording {recording_id} 重新排队成功")
            else:
                print(f"  ❌ Recording {recording_id} 重新排队失败: {response}")
        else:
            print(f"  ❌ Recording {recording_id} 请求失败")
    
    return success_count > 0

def get_group_recordings(group_id: int) -> List[int]:
    """获取分组的所有录制ID"""
    result = subprocess.run([
        'curl', '-s', f'http://localhost:8899/api/recordings?group_id={group_id}'
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        data = json.loads(result.stdout)
        return [item['id'] for item in data.get('items', [])]
    return []

def main():
    print("🎬 开始批量转换经典模式为导演模式...")
    
    groups = get_groups_data()
    if not groups:
        print("❌ 无法获取分组数据")
        return
    
    # 筛选需要转换的分组
    classic_groups = [
        g for g in groups 
        if g.get('editing_mode') == 'classic' and g.get('clip_count', 0) > 0
    ]
    
    # 优先处理时长不足的分组
    short_groups = [
        g for g in classic_groups
        if g.get('quality_issue') and '时长不足' in g.get('quality_issue', '')
    ]
    
    print(f"📊 找到 {len(classic_groups)} 个经典模式分组")
    print(f"⚠️  其中 {len(short_groups)} 个时长不足")
    
    # 处理时长不足的分组
    print("\n🔧 优先处理时长不足的分组...")
    for i, group in enumerate(short_groups[:10], 1):  # 限制前10个避免过载
        group_id = group['id']
        label = group['label']
        issue = group.get('quality_issue', '')
        
        print(f"\n[{i}/10] 处理分组 {group_id}: {label}")
        print(f"   问题: {issue}")
        
        # 1. 切换为导演模式
        if switch_to_director_mode(group_id):
            print("   ✅ 切换为导演模式成功")
        else:
            print("   ❌ 切换导演模式失败")
            continue
        
        # 2. 生成剧本
        if generate_director_script(group_id):
            print("   ✅ 生成导演剧本成功")
        else:
            print("   ⚠️  剧本生成失败，继续重新剪辑")
        
        # 3. 获取录制ID并重新剪辑
        recording_ids = get_group_recordings(group_id)
        if recording_ids:
            print(f"   📝 找到 {len(recording_ids)} 个录制")
            if retry_clip_with_director_mode(group_id, recording_ids):
                print("   ✅ 重新剪辑任务已提交")
            else:
                print("   ❌ 重新剪辑失败")
        else:
            print("   ⚠️  未找到录制记录")
        
        # 避免过载，延迟2秒
        time.sleep(2)
    
    print(f"\n🎉 批量转换完成！已处理 {min(len(short_groups), 10)} 个时长不足的分组")
    print("📋 建议监控剪辑队列状态，等待处理完成后评估效果")

if __name__ == "__main__":
    main()