#!/usr/bin/env python3
"""
GPU Service Admin Server
监听端口 9999，提供重启和管理接口
"""
import http.server
import subprocess
import threading
import os
import sys
import json
import socketserver
from datetime import datetime

# 配置
WORK_DIR = r"C:\Users\neo\douyin_processor"
PYTHON = r"C:\Python313\python.exe"
LOG_FILE = r"C:\Temp\gpu_admin.log"
PORT = 9999

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}\n"
    print(line, end='', flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line)
    except:
        pass

def get_gpu_status():
    """获取 GPU 服务状态"""
    try:
        import urllib.request
        with urllib.request.urlopen('http://localhost:8877/health', timeout=5) as resp:
            return json.loads(resp.read())
    except:
        return {"status": "unavailable"}

def restart_gpu_service():
    """重启 GPU 服务"""
    log("收到重启请求，开始重启 GPU 服务...")
    
    # 停止现有 Python 进程
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], 
                      capture_output=True, timeout=15)
        log("已停止现有进程")
    except Exception as e:
        log(f"停止进程失败: {e}")
    
    # 等待端口释放
    import time
    for _ in range(10):
        time.sleep(1)
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', 8877))
            sock.close()
            if result != 0:
                log("端口 8877 已释放")
                break
        except:
            pass
    
    # 启动新服务
    try:
        os.makedirs(WORK_DIR, exist_ok=True)
        os.chdir(WORK_DIR)
        
        # 启动服务（后台运行）
        with open(r'C:\Temp\gpu_service.out.log', 'w', encoding='utf-8') as fout:
            with open(r'C:\Temp\gpu_service.err.log', 'w', encoding='utf-8') as ferr:
                subprocess.Popen(
                    [PYTHON, '-m', 'gpu_service.main'],
                    stdout=fout,
                    stderr=ferr,
                    cwd=WORK_DIR,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
                )
        
        log("GPU 服务启动命令已发送")
        
        # 等待服务启动
        for i in range(30):
            time.sleep(2)
            status = get_gpu_status()
            if status.get('health') == 'healthy':
                log(f"GPU 服务已恢复健康: {status.get('jobs')} 任务已完成")
                return True
        
        log("服务启动，但健康检查未通过")
        return True
    except Exception as e:
        log(f"启动失败: {e}")
        return False

class AdminHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        log(f"{self.client_address[0]} - {format % args}")
    
    def do_GET(self):
        if self.path == '/health':
            status = get_gpu_status()
            self.send_json(200, status)
        elif self.path == '/restart':
            if restart_gpu_service():
                self.send_json(200, {"status": "restarted"})
            else:
                self.send_json(500, {"error": "restart failed"})
        elif self.path == '/':
            self.send_json(200, {
                "service": "gpu-admin",
                "endpoints": {
                    "GET /": "This help",
                    "GET /health": "GPU service health",
                    "GET /restart": "Restart GPU service"
                }
            })
        else:
            self.send_json(404, {"error": "not found"})
    
    def do_POST(self):
        self.do_GET()
    
    def send_json(self, code, data):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

def main():
    server = ThreadedHTTPServer(('0.0.0.0', PORT), AdminHandler)
    log(f"GPU Admin Server started on port {PORT}")
    print(f"GPU Admin Server running on port {PORT}")
    print("Endpoints:")
    print("  GET /health  - Check GPU service status")
    print("  GET /restart - Restart GPU service")
    server.serve_forever()

if __name__ == '__main__':
    main()
