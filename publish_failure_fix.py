#!/usr/bin/env python3
"""
发布失败问题诊断和修复
解决浏览器超时和页面加载问题
"""

import sqlite3
from datetime import datetime

def diagnose_publish_failures():
    print("🔍 发布失败问题诊断和修复")
    print("=" * 35)
    
    # 连接数据库
    db_path = "/Users/claw/work/douyin-recorder/douyin.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 统计失败类型
    cursor.execute("""
        SELECT 
            CASE 
                WHEN error_msg LIKE '%Timeout%' OR error_msg LIKE '%timeout%' THEN 'timeout'
                WHEN error_msg LIKE '%closed%' OR error_msg LIKE '%关闭%' THEN 'browser_closed'  
                WHEN error_msg LIKE '%时长不足%' OR error_msg LIKE '%质量不达标%' THEN 'video_quality'
                WHEN error_msg LIKE '%split%' THEN 'data_error'
                ELSE 'other'
            END as error_type,
            COUNT(*) as count,
            GROUP_CONCAT(id LIMIT 3) as example_ids
        FROM publish_tasks 
        WHERE status = 'failed'
        GROUP BY error_type
        ORDER BY count DESC
    """)
    
    error_stats = cursor.fetchall()
    
    print("📊 失败类型统计:")
    total_failed = sum(count for _, count, _ in error_stats)
    for error_type, count, example_ids in error_stats:
        percentage = (count / total_failed) * 100
        print(f"  {error_type}: {count}个任务 ({percentage:.1f}%)")
        print(f"    示例任务ID: {example_ids}")
    
    print(f"\n总失败任务数: {total_failed}")
    
    # 超时问题详细分析
    print("\n🕒 超时问题详细分析:")
    cursor.execute("""
        SELECT error_msg, COUNT(*) as count
        FROM publish_tasks 
        WHERE status = 'failed' AND (error_msg LIKE '%Timeout%' OR error_msg LIKE '%timeout%')
        GROUP BY error_msg
        ORDER BY count DESC
        LIMIT 5
    """)
    
    timeout_details = cursor.fetchall()
    for msg, count in timeout_details:
        print(f"  • {count}次: {msg[:100]}...")
    
    conn.close()
    
    return error_stats

def create_publish_fix():
    print("\n🛠️ 创建发布系统修复方案:")
    
    fix_content = '''"""
发布系统超时问题修复补丁
主要解决文件上传元素等待超时问题
"""

# 原配置的超时时间
ORIGINAL_TIMEOUTS = {
    "page_load": 60000,        # 页面加载
    "file_input": 60000,       # 文件上传元素等待  
    "upload_processing": 300,  # 视频处理等待
}

# 修复后的超时配置
FIXED_TIMEOUTS = {
    "page_load": 120000,       # 页面加载: 60s → 120s  
    "file_input": 180000,      # 文件上传元素: 60s → 180s
    "upload_processing": 600,  # 视频处理: 300s → 600s
    "browser_startup": 30000,  # 浏览器启动等待
    "retry_attempts": 3,       # 失败重试次数
}

# 建议的修复步骤
FIX_RECOMMENDATIONS = [
    "1. 增加文件上传元素等待时间：60s → 180s",
    "2. 增加页面加载超时：60s → 120s", 
    "3. 增加视频处理等待：300s → 600s",
    "4. 添加重试机制：失败后自动重试3次",
    "5. 添加更详细的错误日志",
    "6. 优化浏览器启动配置"
]
'''
    
    with open("/Users/claw/work/douyin-recorder/publish_fix_analysis.py", "w", encoding="utf-8") as f:
        f.write(fix_content)
    
    print("  ✅ 分析报告已保存: publish_fix_analysis.py")

def apply_immediate_fixes():
    print("\n⚡ 立即应用修复:")
    
    # 修复方案1: 重启所有失败的发布任务
    db_path = "/Users/claw/work/douyin-recorder/douyin.db" 
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 统计可重试的失败任务
    cursor.execute("""
        SELECT COUNT(*) 
        FROM publish_tasks 
        WHERE status = 'failed' 
        AND error_msg NOT LIKE '%质量不达标%'
        AND error_msg NOT LIKE '%时长不足%'
        AND created_at > datetime('now', '-7 days')
    """)
    
    retry_count = cursor.fetchone()[0]
    
    print(f"  📋 发现 {retry_count} 个可重试的失败任务")
    
    if retry_count > 0:
        # 将超时失败的任务重置为pending状态
        cursor.execute("""
            UPDATE publish_tasks 
            SET status = 'pending', 
                error_msg = NULL,
                scheduled_at = NULL
            WHERE status = 'failed' 
            AND error_msg NOT LIKE '%质量不达标%'
            AND error_msg NOT LIKE '%时长不足%'
            AND created_at > datetime('now', '-7 days')
        """)
        
        updated = cursor.rowcount
        conn.commit()
        
        print(f"  ✅ 已重置 {updated} 个失败任务为pending状态")
        print(f"  🔄 这些任务将在下次调度时自动重试")
    
    conn.close()

def check_browser_environment():
    print("\n🌐 检查浏览器环境:")
    
    checks = [
        ("Playwright安装", "python3 -c 'import playwright; print(\"✅ Playwright已安装\")'"),
        ("Chromium可用", "python3 -c 'from playwright.sync_api import sync_playwright; p = sync_playwright().start(); print(\"✅ Chromium可用\"); p.stop()'"),
        ("系统内存", "vm_stat | head -5"),
        ("磁盘空间", "df -h /Users/claw/work/douyin-recorder | tail -1")
    ]
    
    for check_name, command in checks:
        print(f"\n  🔍 {check_name}:")
        import subprocess
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print(f"    {result.stdout.strip()}")
            else:
                print(f"    ❌ 检查失败: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            print(f"    ⏱️ 检查超时")
        except Exception as e:
            print(f"    ❌ 检查异常: {e}")

def monitor_system_resources():
    print("\n💻 系统资源监控:")
    
    import subprocess
    import json
    
    # 内存使用
    try:
        result = subprocess.run(["vm_stat"], capture_output=True, text=True)
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            for line in lines[:6]:
                if line.strip():
                    print(f"    {line}")
    except:
        print("    ❌ 无法获取内存信息")
    
    # 磁盘空间
    print("\n  💾 磁盘空间:")
    try:
        result = subprocess.run(["df", "-h", "/Users/claw/work/douyin-recorder"], capture_output=True, text=True)
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            for line in lines:
                if line.strip():
                    print(f"    {line}")
    except:
        print("    ❌ 无法获取磁盘信息")

def main():
    print("🚨 发布失败问题紧急修复")
    print("分析超时原因并应用修复措施")
    print("")
    
    # 诊断失败原因
    error_stats = diagnose_publish_failures()
    
    # 创建修复方案
    create_publish_fix()
    
    # 检查系统环境
    check_browser_environment() 
    monitor_system_resources()
    
    # 应用立即修复
    apply_immediate_fixes()
    
    print("\n🎯 修复建议总结:")
    print("1. 🔄 已重置失败任务为待发布状态")
    print("2. ⏱️ 建议增加浏览器超时配置")
    print("3. 🔧 考虑升级为无头模式避免UI干扰")
    print("4. 📊 监控系统资源使用情况")
    print("5. 🔁 添加自动重试机制")
    
    print("\n💡 下一步行动:")
    print("• 监控重置后的发布任务执行情况")
    print("• 如仍有超时，修改publisher_douyin.py中的超时配置")
    print("• 考虑分批发布减少并发压力")

if __name__ == "__main__":
    main()