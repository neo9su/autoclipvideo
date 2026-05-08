#!/usr/bin/env python3
"""
抖音录屏项目持续监控脚本
确保76个导演模式分组和148个剪辑任务稳定运行
"""

import json
import subprocess
import time
from datetime import datetime

class ProjectMonitor:
    def __init__(self):
        self.start_time = datetime.now()
        self.baseline_metrics = {
            'director_groups': 76,
            'total_scripts': 76,
            'queue_baseline': 148
        }
    
    def get_system_status(self):
        """获取系统状态"""
        try:
            # 获取分组统计
            groups_result = subprocess.run([
                'curl', '-s', 'http://localhost:8899/api/groups'
            ], capture_output=True, text=True, timeout=10)
            
            # 获取队列状态  
            queue_result = subprocess.run([
                'curl', '-s', 'http://localhost:8899/api/clip-queue'
            ], capture_output=True, text=True, timeout=10)
            
            # 获取GPU状态
            gpu_result = subprocess.run([
                'curl', '-s', 'http://10.190.0.203:8877/health'
            ], capture_output=True, text=True, timeout=5)
            
            status = {}
            
            if groups_result.returncode == 0:
                groups = json.loads(groups_result.stdout)
                director_groups = [g for g in groups if g.get('editing_mode') == 'director']
                status['groups'] = {
                    'total': len(groups),
                    'director_mode': len(director_groups),
                    'with_scripts': len([g for g in director_groups if g.get('director_script')]),
                    'quality_issues': len([g for g in groups if g.get('quality_issue')])
                }
            
            if queue_result.returncode == 0:
                queue = json.loads(queue_result.stdout)
                status['queue'] = {
                    'running': len(queue.get('running', [])),
                    'queued': len(queue.get('queued', [])),
                    'total': len(queue.get('running', [])) + len(queue.get('queued', []))
                }
            
            if gpu_result.returncode == 0:
                gpu = json.loads(gpu_result.stdout)
                status['gpu'] = {
                    'status': gpu.get('status'),
                    'jobs_completed': gpu.get('jobs', 0),
                    'gpu_busy': gpu.get('gpu_busy', False)
                }
            
            return status
            
        except Exception as e:
            return {'error': str(e)}
    
    def check_system_health(self, status):
        """检查系统健康状态"""
        issues = []
        warnings = []
        
        if 'error' in status:
            issues.append(f"❌ 系统连接失败: {status['error']}")
            return issues, warnings
        
        # 检查导演模式分组
        if 'groups' in status:
            groups = status['groups']
            if groups['director_mode'] < self.baseline_metrics['director_groups']:
                issues.append(f"❌ 导演模式分组数量下降: {groups['director_mode']}/{self.baseline_metrics['director_groups']}")
            
            if groups['with_scripts'] < self.baseline_metrics['total_scripts']:
                issues.append(f"❌ 剧本覆盖率下降: {groups['with_scripts']}/{self.baseline_metrics['total_scripts']}")
            
            if groups['quality_issues'] > 15:
                warnings.append(f"⚠️ 质量问题分组增加: {groups['quality_issues']}个")
        
        # 检查队列状态
        if 'queue' in status:
            queue = status['queue']
            if queue['total'] > self.baseline_metrics['queue_baseline'] * 1.5:
                warnings.append(f"⚠️ 队列任务积压: {queue['total']}个")
            elif queue['total'] == 0:
                warnings.append("ℹ️ 队列已清空，所有任务处理完成")
        
        # 检查GPU状态
        if 'gpu' in status:
            gpu = status['gpu']
            if gpu['status'] != 'ok':
                issues.append(f"❌ GPU服务异常: {gpu['status']}")
        
        return issues, warnings
    
    def generate_status_report(self, status):
        """生成状态报告"""
        current_time = datetime.now()
        runtime = current_time - self.start_time
        
        print(f"\n🎬 抖音录屏项目监控报告")
        print(f"📅 监控时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏱️ 运行时长: {runtime}")
        print("=" * 50)
        
        if 'error' in status:
            print(f"❌ 系统状态: 连接异常 - {status['error']}")
            return
        
        # 核心指标展示
        if 'groups' in status:
            groups = status['groups']
            print(f"📊 分组状态:")
            print(f"  总分组数: {groups['total']}")
            print(f"  导演模式: {groups['director_mode']}/76 ({'✅' if groups['director_mode'] >= 76 else '⚠️'})")
            print(f"  剧本覆盖: {groups['with_scripts']}/76 ({'✅' if groups['with_scripts'] >= 76 else '⚠️'})")
            print(f"  质量问题: {groups['quality_issues']}个 ({'✅' if groups['quality_issues'] <= 15 else '⚠️'})")
        
        if 'queue' in status:
            queue = status['queue']
            progress = max(0, self.baseline_metrics['queue_baseline'] - queue['total'])
            print(f"🔄 队列状态:")
            print(f"  运行中: {queue['running']}个")
            print(f"  排队中: {queue['queued']}个")
            print(f"  总任务: {queue['total']}个")
            print(f"  处理进度: {progress}个已完成 ({progress/self.baseline_metrics['queue_baseline']*100:.1f}%)")
        
        if 'gpu' in status:
            gpu = status['gpu']
            print(f"🚀 GPU服务器:")
            print(f"  状态: {gpu['status']} ({'✅' if gpu['status'] == 'ok' else '❌'})")
            print(f"  完成任务: {gpu['jobs_completed']}个")
            print(f"  GPU忙碌: {'是' if gpu['gpu_busy'] else '否'}")
        
        # 检查健康状态
        issues, warnings = self.check_system_health(status)
        
        if issues:
            print(f"\n🚨 严重问题:")
            for issue in issues:
                print(f"  {issue}")
        
        if warnings:
            print(f"\n⚠️ 注意事项:")
            for warning in warnings:
                print(f"  {warning}")
        
        if not issues and not warnings:
            print(f"\n✅ 系统运行正常，所有指标健康！")
        
        print("\n" + "=" * 50)
    
    def continuous_monitor(self, interval=300):  # 5分钟间隔
        """持续监控模式"""
        print("🔄 启动持续监控模式...")
        print(f"📋 监控间隔: {interval}秒")
        print(f"🎯 基线指标: {self.baseline_metrics}")
        
        while True:
            try:
                status = self.get_system_status()
                self.generate_status_report(status)
                
                if interval > 0:
                    print(f"😴 等待 {interval} 秒后继续监控...")
                    time.sleep(interval)
                else:
                    break  # 单次检查模式
                    
            except KeyboardInterrupt:
                print("\n👋 监控已停止")
                break
            except Exception as e:
                print(f"\n❌ 监控异常: {e}")
                time.sleep(60)  # 异常时等待1分钟

def main():
    monitor = ProjectMonitor()
    
    print("🎬 抖音录屏项目监控工具")
    print("💡 使用说明:")
    print("  - 单次检查: python3 monitor.py")
    print("  - 持续监控: python3 monitor.py --continuous")
    print("  - Ctrl+C 停止监控")
    
    import sys
    if '--continuous' in sys.argv:
        monitor.continuous_monitor(300)  # 5分钟间隔
    else:
        # 单次检查
        status = monitor.get_system_status()
        monitor.generate_status_report(status)
        
        print("\n💡 提示: 使用 --continuous 参数启动持续监控")

if __name__ == "__main__":
    main()