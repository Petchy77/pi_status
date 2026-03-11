import psutil
import time
import os
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
import numpy as np
import subprocess
import re
import threading

# 1. ตั้งค่าโฟลเดอร์ Log
log_dir = '/home/pi/pi_status/log'
if not os.path.exists(log_dir): os.makedirs(log_dir)

# 2. Data Storage (ลบ [0]*60 ออก เพื่อไม่ให้มีค่า 0 ปลอมหลุดไปใน Log)
MAX_POINTS = 60
data_store = {
    'cpu_temp': deque(maxlen=MAX_POINTS),
    'cpu_usage': deque(maxlen=MAX_POINTS),
    'ram_usage': deque(maxlen=MAX_POINTS),
    'gpu_usage': deque(maxlen=MAX_POINTS),
    'npu_usage': deque(maxlen=MAX_POINTS)
}

current_npu_usage = 0.0
last_log_time = time.time()

# 3. NPU Monitor Thread
def monitor_npu_background():
    global current_npu_usage
    try:
        process = subprocess.Popen(['hailortcli', 'monitor'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in iter(process.stdout.readline, ''):
            if '/' not in line:
                match = re.search(r'([a-zA-Z0-9_.-]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)', line)
                if match: current_npu_usage = float(match.group(2))
    except: pass

threading.Thread(target=monitor_npu_background, daemon=True).start()

# 4. Data Retrieval Functions
def get_cpu_temp():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f: return float(f.read()) / 1000.0
    except: return 0.0

def get_gpu_usage_pro():
    try:
        clients = subprocess.check_output(['sudo', 'cat', '/sys/kernel/debug/dri/0/clients'], text=True)
        lines = clients.strip().split('\n')
        active_clients = 0
        if len(lines) > 1:
            for line in lines[1:]:
                parts = line.split()
                if len(parts) > 2 and int(parts[2]) > 0: active_clients += 1

        if active_clients > 0:
            usage = (active_clients * 0.4) + (psutil.cpu_percent() * 0.02)
            return max(0.5, min(usage, 100.0))
            
        ident = subprocess.check_output(['sudo', 'cat', '/sys/kernel/debug/dri/0/v3d_ident'], text=True).lower()
        if 'active' in ident or 'busy' in ident: return 0.8
    except: pass
    return 0.0

# 5. Logic สำหรับเปลี่ยนสี (Dynamic Colors)
def get_status_color(val, key):
    warn_limit = 60.0
    danger_limit = 85.0
    
    if 'temp' in key:
        warn_limit = 65.0
        danger_limit = 80.0

    if val >= danger_limit:
        return '#d62728' # แดง
    elif val >= warn_limit:
        return '#ff7f0e' # ส้ม/เหลือง
    else:
        return '#2ca02c' # เขียว

# 6. UI Layout
plt.rcParams['font.family'] = 'sans-serif'
fig, axs = plt.subplots(3, 2, figsize=(12, 8))
fig.tight_layout(pad=3.0)
titles = ['CPU Temp (C)', 'CPU Usage (%)', 'RAM Usage (%)', 'GPU Usage (%)', 'NPU Usage (%)']
keys = list(data_store.keys())
lines = {}

for i, ax in enumerate(axs.flat):
    if i < len(keys):
        lines[keys[i]], = ax.plot([], [], lw=2.5)
        ax.set_title(titles[i], fontweight='bold')
        ax.set_xlim(0, MAX_POINTS)
        ax.set_facecolor('#ffffff') 
        ax.grid(True, linestyle='--', alpha=0.6)
    else: ax.set_visible(False)

def update(frame):
    global last_log_time
    
    data_store['cpu_temp'].append(get_cpu_temp())
    data_store['cpu_usage'].append(psutil.cpu_percent())
    data_store['ram_usage'].append(psutil.virtual_memory().percent)
    data_store['gpu_usage'].append(get_gpu_usage_pro())
    data_store['npu_usage'].append(current_npu_usage)

    for i, key in enumerate(keys):
        y_data = list(data_store[key])
        x_data = range(len(y_data))
        lines[key].set_data(x_data, y_data)
        
        ax = axs.flat[i]
        
        if ax.get_navigate_mode() is None:
            curr_max = max(y_data) if max(y_data) > 0 else 1.0
            limit = 5.0 if (key in ['gpu_usage', 'npu_usage'] and curr_max < 4.0) else curr_max / 0.8
            ax.set_ylim(0, limit)
            
        latest_val = y_data[-1] if len(y_data) > 0 else 0
        theme_color = get_status_color(latest_val, key)
        
        lines[key].set_color(theme_color)
        ax.collections.clear()
        ax.fill_between(x_data, 0, y_data, color=theme_color, alpha=0.2)

    # 7. Custom Logging Logic
    current_time = time.time()
    if current_time - last_log_time >= 60:
        date_str = time.strftime("%Y-%m-%d")
        time_str = time.strftime("%H:%M")
        log_filename = os.path.join(log_dir, f'system_monitor_{date_str}.log')
        
        log_msgs = []
        for key in keys:
            y_data = list(data_store[key])
            if y_data: # ป้องกันกรณีข้อมูลว่าง
                val_min = min(y_data)
                val_max = max(y_data)
                log_msgs.append(f"{key.upper()} [Min:{val_min:.1f} Max:{val_max:.1f}]")
        
        log_line = f"{date_str} {time_str} - " + " | ".join(log_msgs) + "\n"
        
        with open(log_filename, "a") as f:
            f.write(log_line)
            
        last_log_time = current_time

    return list(lines.values())

ani = animation.FuncAnimation(fig, update, interval=1000, blit=False)
plt.show()
