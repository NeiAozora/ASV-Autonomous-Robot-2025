import subprocess
import time
import threading
import signal
import sys
import os

class ProcessInfo:
    def __init__(self, name, command, autorestart, max_restarts):
        self.name = name
        self.command = command
        self.autorestart = autorestart
        self.max_restarts = max_restarts
        self.restart_count = 0
        self.process = None
        self.running = False
        self.thread = None

class ParallelRunner:
    def __init__(self):
        self.processes = {}
        self.running = False
        self.lock = threading.Lock()
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print("\nReceived signal {}, shutting down...".format(signum))
        self.stop_all()
    
    def add_process(self, name, command, autorestart=True, max_restarts=None):
        """Add a process to be managed
        
        Args:
            name: Unique name for the process
            command: Command to execute
            autorestart: Whether to automatically restart on failure
            max_restarts: Maximum number of restarts (None for infinite)
        """
        with self.lock:
            if name in self.processes:
                raise ValueError("Process with name '{}' already exists".format(name))
            
            self.processes[name] = ProcessInfo(name, command, autorestart, max_restarts)
            print("Added process: {} - Command: {} - Auto-restart: {} - Max restarts: {}".format(
                name, command, autorestart, max_restarts))
    
    def _run_process(self, proc_info):
        """Run a single process in a thread"""
        while self.running and proc_info.running:
            try:
                print("[{}] Starting process...".format(proc_info.name))
                proc_info.process = subprocess.Popen(
                    proc_info.command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True
                )
                
                # Read output in real-time
                while proc_info.process.poll() is None and proc_info.running:
                    output = proc_info.process.stdout.readline()
                    if output:
                        print("[{}] {}".format(proc_info.name, output.strip()))
                
                # Get remaining output
                for output in proc_info.process.stdout:
                    if output.strip():
                        print("[{}] {}".format(proc_info.name, output.strip()))
                
                return_code = proc_info.process.wait()
                
                if return_code == 0:
                    print("[{}] Process completed successfully".format(proc_info.name))
                    break
                else:
                    print("[{}] Process exited with code {}".format(proc_info.name, return_code))
                    
                    if not proc_info.autorestart:
                        print("[{}] Auto-restart disabled, not restarting".format(proc_info.name))
                        break
                    
                    if proc_info.max_restarts is not None:
                        proc_info.restart_count += 1
                        if proc_info.restart_count >= proc_info.max_restarts:
                            print("[{}] Maximum restart limit ({}) reached".format(
                                proc_info.name, proc_info.max_restarts))
                            break
                    
                    print("[{}] Restarting... (attempt {})".format(
                        proc_info.name, proc_info.restart_count + 1))
                    time.sleep(2)  # Wait before restarting
                    
            except Exception as e:
                print("[{}] Error: {}".format(proc_info.name, e))
                
                if not proc_info.autorestart:
                    break
                    
                if proc_info.max_restarts is not None:
                    proc_info.restart_count += 1
                    if proc_info.restart_count >= proc_info.max_restarts:
                        print("[{}] Maximum restart limit ({}) reached".format(
                            proc_info.name, proc_info.max_restarts))
                        break
                
                print("[{}] Restarting after error... (attempt {})".format(
                    proc_info.name, proc_info.restart_count + 1))
                time.sleep(2)
        
        proc_info.running = False
        print("[{}] Process thread stopped".format(proc_info.name))
    
    def run(self):
        """Start all processes"""
        if not self.processes:
            print("No processes to run")
            return
        
        self.running = True
        print("Starting {} processes...".format(len(self.processes)))
        
        # Start all processes
        for proc_info in self.processes.values():
            proc_info.running = True
            proc_info.thread = threading.Thread(
                target=self._run_process, 
                args=(proc_info,)
            )
            # Set daemon menggunakan method setDaemon() untuk kompatibilitas Python lama
            proc_info.thread.setDaemon(True)
            proc_info.thread.start()
        
        print("All processes started. Press Ctrl+C to stop.")
        
        # Monitor threads
        try:
            while self.running:
                # Check if any threads are still alive
                alive_threads = sum(1 for p in self.processes.values() if p.thread and p.thread.is_alive())
                
                if alive_threads == 0:
                    print("All processes have stopped")
                    break
                
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\nReceived keyboard interrupt")
            self.stop_all()
    
    def stop_all(self):
        """Stop all running processes"""
        self.running = False
        print("Stopping all processes...")
        
        for proc_info in self.processes.values():
            proc_info.running = False
            if proc_info.process and proc_info.process.poll() is None:
                print("[{}] Terminating process...".format(proc_info.name))
                proc_info.process.terminate()
                
                # Wait for process to terminate
                try:
                    proc_info.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print("[{}] Force killing process...".format(proc_info.name))
                    proc_info.process.kill()
        
        # Wait for threads to finish
        for proc_info in self.processes.values():
            if proc_info.thread and proc_info.thread.is_alive():
                proc_info.thread.join(timeout=3)
        
        print("All processes stopped")


def run():
    p = ParallelRunner()

    # Cek struktur direktori terlebih dahulu
    base_dir = os.getcwd()
    print("Current working directory:", base_dir)
    
    # Cek apakah file server.py ada di server/control
    control_server_path = os.path.join(base_dir, "server", "control", "server.py")
    if os.path.exists(control_server_path):
        print("✓ server.py found at:", control_server_path)
    else:
        print("✗ server.py NOT found at:", control_server_path)
        # List files di direktori control untuk debugging
        control_dir = os.path.join(base_dir, "server", "control")
        if os.path.exists(control_dir):
            print("Files in control directory:", os.listdir(control_dir))

    # Opsi 1: Jika file server.py ada di server/control
    p.add_process("camera_server", "cd server/camera/camera_v2_go/ && bash run_server.sh", True, None)
    p.add_process("controller_server", "cd server/control && python -m uvicorn server:app --host 0.0.0.0 --port 2000 --workers 1", True, None)
    p.add_process("server_tranceiver", "cd server/tranceiver && go run main.go", True, None)

    p.run()

if __name__ == "__main__":
    run()