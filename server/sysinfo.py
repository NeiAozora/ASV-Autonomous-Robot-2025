from flask import Flask, jsonify
import psutil
import platform
import socket
import datetime

app = Flask(__name__)

@app.route('/')
def index():
    """Root endpoint with API information"""
    return jsonify({
        "message": "System Information API",
        "endpoints": {
            "/": "This information",
            "/cpu": "CPU information and usage",
            "/memory": "Memory and swap usage",
            "/network": "Network information and statistics",
            "/all": "All system information (CPU, Memory, Network)"
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
                "load_average": {
                    "1min": os.getloadavg()[0] if hasattr(os, 'getloadavg') else "N/A",
                    "5min": os.getloadavg()[1] if hasattr(os, 'getloadavg') else "N/A",
                    "15min": os.getloadavg()[2] if hasattr(os, 'getloadavg') else "N/A"
                }
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
                "total": virtual_memory.total,
                "available": virtual_memory.available,
                "used": virtual_memory.used,
                "used_percent": virtual_memory.percent,
                "swap_total": swap_memory.total,
                "swap_used": swap_memory.used,
                "swap_free": swap_memory.free,
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

@app.route('/all')
def all_info():
    """Get all system information (CPU, Memory, Network) in one endpoint"""
    try:
        return jsonify({
            "cpu": cpu_info().get_json()["cpu"],
            "memory": memory_info().get_json()["memory"],
            "network": network_info().get_json()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Run the Flask app
    print("Starting System Information API Server...")
    print("Available endpoints:")
    print("  http://localhost:5000/")
    print("  http://localhost:5000/cpu")
    print("  http://localhost:5000/memory")
    print("  http://localhost:5000/network")
    print("  http://localhost:5000/all")
    
    app.run(host='0.0.0.0', port=5000, debug=True)