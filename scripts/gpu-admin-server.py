#!/usr/bin/env python3
"""
GPU Service Admin Server
一个简单的 HTTP 管理服务器，用于远程重启 GPU 服务
运行在 GPU 服务器本地 (localhost:9999)
"""
import http.server
import subprocess
import threading
import os
import sys
from datetime import datetime

WORK_DIR = r"C:\Users\neo\douyin_processor"
PYTHON = r"C:\Python313\python.exe"
LOG_FILE = r"C:\Temp\gpu_admin.log"

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}\n"
    print(line, end='')
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line)

def restart_gpu_service():
    """重启 GPU 服务"""
    log("收到重启请求，开始重启 GPU 服务...")
    
    # 停止现有进程
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'python.exe', '/FI', f'WINDOWTITLE eq GPU Service*'], 
                      capture_output=True, timeout=10)
    except:
        pass
    
    # 更彻底的方式：杀所有 python.exe
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], capture_output=True, timeout=10)
    except:
        pass
    
    log("已停止现有进程")
    
    # 启动新服务
    try:
        os.chdir(WORK_DIR)
        subprocess.Popen([PYTHON, '-m', 'gpu_service.main'], 
                        stdout=open(r'C:\Temp\gpu_service.out.log', 'w'),
                        stderr=open(r'C:\Temp\gpu_service.err.log', 'w'),
                        cwd=WORK_DIR)
        log("GPU 服务已启动")
        return True
    except Exception as e:
        log(f"启动失败: {e}")
        return False

class AdminHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        elif self.path == '/restart':
            log(f"收到重启请求 from {self.client_address[0]}")
            if restart_gpu_service():
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "restarted"}')
            else:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "restart failed"}')
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        self.do_GET()

def run_server(port=9999):
    server = http.server.HTTPServer(('0.0.0.0', port), AdminHandler)
    log(f"管理服务器启动于端口 {port}")
    print(f"GPU Admin Server running on port {port}")
    print("Endpoints:")
    print("  GET /health - Check status")
    print("  GET /restart - Restart GPU service")
    server.serve_forever()

if __name__ == '__main__':
    run_server()
