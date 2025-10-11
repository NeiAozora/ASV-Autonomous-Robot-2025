from flask import Flask, jsonify
import psutil
import platform
import socket
import datetime
import os
import subprocess
import re

app = Flask(__name__)

def get_jetson_power_info():
    """Get power information specific to Jetson Nano"""
    power_info = {}
    
    try:
        # Get CPU power usage
        result = subprocess.run(['cat', '/sys/bus/i2c/drivers/ina3221/0-0040/iio:device0/in_power0_input'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['cpu_power_mw'] = float(result.stdout.strip()) / 1000  # Convert to mW
        
        # Get GPU power usage
        result = subprocess.run(['cat', '/sys/bus/i2c/drivers/ina3221/0-0040/iio:device0/in_power1_input'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['gpu_power_mw'] = float(result.stdout.strip()) / 1000  # Convert to mW
        
        # Get SOC power usage
        result = subprocess.run(['cat', '/sys/bus/i2c/drivers/ina3221/0-0040/iio:device0/in_power2_input'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['soc_power_mw'] = float(result.stdout.strip()) / 1000  # Convert to mW
        
        # Get total power consumption
        result = subprocess.run(['cat', '/sys/bus/i2c/drivers/ina3221/0-0041/iio:device1/in_power0_input'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['total_power_mw'] = float(result.stdout.strip()) / 1000  # Convert to mW
        
        # Get current values
        result = subprocess.run(['cat', '/sys/bus/i2c/drivers/ina3221/0-0040/iio:device0/in_current0_input'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['cpu_current_ma'] = float(result.stdout.strip()) / 1000  # Convert to mA
            
        result = subprocess.run(['cat', '/sys/bus/i2c/drivers/ina3221/0-0040/iio:device0/in_current1_input'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['gpu_current_ma'] = float(result.stdout.strip()) / 1000  # Convert to mA
            
        result = subprocess.run(['cat', '/sys/bus/i2c/drivers/ina3221/0-0040/iio:device0/in_current2_input'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['soc_current_ma'] = float(result.stdout.strip()) / 1000  # Convert to mA
        
        # Get voltage values
        result = subprocess.run(['cat', '/sys/bus/i2c/drivers/ina3221/0-0040/iio:device0/in_voltage0_input'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['cpu_voltage_mv'] = float(result.stdout.strip())  # Already in mV
            
        result = subprocess.run(['cat', '/sys/bus/i2c/drivers/ina3221/0-0040/iio:device0/in_voltage1_input'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['gpu_voltage_mv'] = float(result.stdout.strip())
            
        result = subprocess.run(['cat', '/sys/bus/i2c/drivers/ina3221/0-0040/iio:device0/in_voltage2_input'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['soc_voltage_mv'] = float(result.stdout.strip())
        
        # Get temperature
        result = subprocess.run(['cat', '/sys/class/thermal/thermal_zone0/temp'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['temperature_c'] = float(result.stdout.strip()) / 1000  # Convert to Celsius
        
        # Get GPU frequency
        result = subprocess.run(['cat', '/sys/devices/gpu.0/devfreq/17000000.gv11b/cur_freq'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['gpu_frequency_hz'] = int(result.stdout.strip())
            
        # Get CPU frequency
        result = subprocess.run(['cat', '/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            power_info['cpu_frequency_hz'] = int(result.stdout.strip())
            
    except Exception as e:
        power_info['error'] = str(e)
    
    return power_info

def get_jetson_model():
    """Get Jetson model information"""
    try:
        result = subprocess.run(['cat', '/proc/device-tree/model'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip().replace('\x00', '')
        return "Jetson Nano"
    except:
        return "Jetson Nano"

@app.route('/')
def index():
    """Root endpoint with API information"""
    return jsonify({
        "message": "Jetson Nano System Information API",
        "model": get_jetson_model(),
        "endpoints": {
            "/": "This information",
            "/cpu": "CPU information and usage",
            "/memory": "Memory and swap usage",
            "/network": "Network information and statistics",
            "/power": "Power consumption and sensors (Jetson specific)",
            "/all": "All system information"
        }
    })

@app.route('/cpu')
def cpu_info():
    """Get CPU information and usage"""
    try:
        cpu_freq = psutil.cpu_freq()
        return jsonify({
            "cpu": {
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
                "current_usage_percent": psutil.cpu_percent(interval=0.1),
                "per_core_usage": psutil.cpu_percent(interval=0.1, percpu=True),
                "frequency": {
                    "current": f"{cpu_freq.current:.2f} MHz" if cpu_freq else "N/A",
                    "min": f"{cpu_freq.min:.2f} MHz" if cpu_freq else "N/A",
                    "max": f"{cpu_freq.max:.2f} MHz" if cpu_freq else "N/A"
                } if cpu_freq else "N/A",
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/memory')
def memory_info():
    """Get memory and swap usage"""
    try:
        virtual_memory = psutil.virtual_memory()
        swap_memory = psutil.swap_memory()
        
        return jsonify({
            "memory": {
                "total_bytes": virtual_memory.total,
                "available_bytes": virtual_memory.available,
                "used_bytes": virtual_memory.used,
                "used_percent": virtual_memory.percent,
                "swap_total_bytes": swap_memory.total,
                "swap_used_bytes": swap_memory.used,
                "swap_free_bytes": swap_memory.free,
                "swap_used_percent": swap_memory.percent
            },
            "memory_human": {
                "total": f"{virtual_memory.total / (1024**3):.2f} GB",
                "available": f"{virtual_memory.available / (1024**3):.2f} GB",
                "used": f"{virtual_memory.used / (1024**3):.2f} GB",
                "used_percent": f"{virtual_memory.percent}%",
                "swap_total": f"{swap_memory.total / (1024**3):.2f} GB",
                "swap_used": f"{swap_memory.used / (1024**3):.2f} GB",
                "swap_free": f"{swap_memory.free / (1024**3):.2f} GB",
                "swap_used_percent": f"{swap_memory.percent}%"
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/network')
def network_info():
    """Get network information and statistics"""
    try:
        net_io = psutil.net_io_counters()
        net_interfaces = psutil.net_if_addrs()
        net_stats = psutil.net_if_stats()
        
        interfaces = {}
        for interface_name, interface_addresses in net_interfaces.items():
            interfaces[interface_name] = {
                "addresses": [],
                "is_up": net_stats[interface_name].isup if interface_name in net_stats else False,
                "speed": f"{net_stats[interface_name].speed} Mbps" if interface_name in net_stats and net_stats[interface_name].speed else "N/A"
            }
            for address in interface_addresses:
                interfaces[interface_name]["addresses"].append({
                    "family": str(address.family),
                    "address": address.address,
                    "netmask": address.netmask if address.netmask else "N/A",
                    "broadcast": address.broadcast if address.broadcast else "N/A"
                })
        
        return jsonify({
            "network_io": {
                "bytes_sent": net_io.bytes_sent,
                "bytes_received": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_received": net_io.packets_recv,
                "errors_in": net_io.errin,
                "errors_out": net_io.errout,
                "drops_in": net_io.dropin,
                "drops_out": net_io.dropout
            },
            "network_io_human": {
                "bytes_sent": f"{net_io.bytes_sent / (1024**2):.2f} MB",
                "bytes_received": f"{net_io.bytes_recv / (1024**2):.2f} MB",
                "packets_sent": f"{net_io.packets_sent:,}",
                "packets_received": f"{net_io.packets_recv:,}",
                "errors_in": net_io.errin,
                "errors_out": net_io.errout,
                "drops_in": net_io.dropin,
                "drops_out": net_io.dropout
            },
            "interfaces": interfaces
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/power')
def power_info():
    """Get power consumption information specific to Jetson Nano"""
    try:
        power_data = get_jetson_power_info()
        
        return jsonify({
            "power_consumption": {
                "cpu_power_mw": power_data.get('cpu_power_mw', 'N/A'),
                "gpu_power_mw": power_data.get('gpu_power_mw', 'N/A'),
                "soc_power_mw": power_data.get('soc_power_mw', 'N/A'),
                "total_power_mw": power_data.get('total_power_mw', 'N/A'),
                "cpu_current_ma": power_data.get('cpu_current_ma', 'N/A'),
                "gpu_current_ma": power_data.get('gpu_current_ma', 'N/A'),
                "soc_current_ma": power_data.get('soc_current_ma', 'N/A'),
                "cpu_voltage_mv": power_data.get('cpu_voltage_mv', 'N/A'),
                "gpu_voltage_mv": power_data.get('gpu_voltage_mv', 'N/A'),
                "soc_voltage_mv": power_data.get('soc_voltage_mv', 'N/A')
            },
            "sensors": {
                "temperature_c": power_data.get('temperature_c', 'N/A'),
                "gpu_frequency_hz": power_data.get('gpu_frequency_hz', 'N/A'),
                "cpu_frequency_hz": power_data.get('cpu_frequency_hz', 'N/A'),
                "gpu_frequency_mhz": f"{power_data.get('gpu_frequency_hz', 0) / 1000000:.2f} MHz" if power_data.get('gpu_frequency_hz') else 'N/A',
                "cpu_frequency_mhz": f"{power_data.get('cpu_frequency_hz', 0) / 1000:.2f} MHz" if power_data.get('cpu_frequency_hz') else 'N/A'
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/all')
def all_info():
    """Get all system information in one endpoint"""
    try:
        return jsonify({
            "system": {
                "model": get_jetson_model(),
                "hostname": socket.gethostname(),
                "platform": platform.platform()
            },
            "cpu": cpu_info().get_json()["cpu"],
            "memory": memory_info().get_json()["memory"],
            "network": network_info().get_json(),
            "power": power_info().get_json()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Run the Flask app
    print("Starting Jetson Nano System Information API Server...")
    print(f"Device Model: {get_jetson_model()}")
    print("Available endpoints:")
    print("  http://localhost:5000/")
    print("  http://localhost:5000/cpu")
    print("  http://localhost:5000/memory")
    print("  http://localhost:5000/network")
    print("  http://localhost:5000/power")
    print("  http://localhost:5000/all")
    
    app.run(host='0.0.0.0', port=5000, debug=True)