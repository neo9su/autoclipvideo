#!/usr/bin/env python3
"""
GPU Service Auto-Recovery Script
可用作 Windows 服务或定时任务
"""
import sys
import os
import time
import urllib.request
import subprocess
import json
from datetime import datetime

CONFIG = {
    'work_dir': r'C:\Users\neo\douyin_processor',
    'python': r'C:\Python313\python.exe',
    'service_port': 8877,
    'log_file': r'C:\Temp\gpu_recover.log'
}

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}\n'
    print(line, end='', flush=True)
    try:
        os.makedirs(os.path.dirname(CONFIG['log_file']), exist_ok=True)
        with open(CONFIG['log_file'], 'a', encoding='utf-8') as f:
            f.write(line)
    except:
        pass

def check_health():
    try:
        url = f'http://localhost:{CONFIG["service_port"]}/health'
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get('health') == 'healthy'
    except:
        return False

def get_status():
    try:
        url = f'http://localhost:{CONFIG["service_port"]}/health'
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except:
        return None

def start_service():
    log('Starting GPU service...')
    try:
        os.chdir(CONFIG['work_dir'])
        subprocess.Popen(
            [CONFIG['python'], '-m', 'gpu_service.main'],
            stdout=open(r'C:\Temp\gpu.out.log', 'w'),
            stderr=open(r'C:\Temp\gpu.err.log', 'w'),
            cwd=CONFIG['work_dir']
        )
        log('Start command sent')
        return True
    except Exception as e:
        log(f'Start failed: {e}')
        return False

def stop_service():
    log('Stopping existing processes...')
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], 
                      capture_output=True, timeout=10)
        log('Stopped')
    except:
        pass

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Check health')
    parser.add_argument('--start', action='store_true', help='Start service')
    parser.add_argument('--stop', action='store_true', help='Stop service')
    parser.add_argument('--restart', action='store_true', help='Restart service')
    parser.add_argument('--monitor', action='store_true', help='Run as monitor')
    args = parser.parse_args()
    
    if args.check:
        status = get_status()
        if status:
            print(json.dumps(status, indent=2))
            sys.exit(0)
        else:
            print('Service unavailable')
            sys.exit(1)
    
    if args.start:
        start_service()
        sys.exit(0)
    
    if args.stop:
        stop_service()
        sys.exit(0)
    
    if args.restart:
        stop_service()
        time.sleep(3)
        start_service()
        sys.exit(0)
    
    if args.monitor:
        log('Starting monitor mode...')
        last_state = None
        while True:
            time.sleep(30)
            healthy = check_health()
            status = get_status()
            
            if healthy:
                jobs = status.get('jobs', 0)
                queue = status.get('queue_depth', 0)
                if last_state != 'healthy':
                    log(f'GPU healthy: jobs={jobs} queue={queue}')
                last_state = 'healthy'
            else:
                if last_state != 'unhealthy':
                    log('GPU service down, restarting...')
                    stop_service()
                    time.sleep(2)
                    start_service()
                last_state = 'unhealthy'

if __name__ == '__main__':
    main()
