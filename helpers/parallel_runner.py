import subprocess
import time
import threading
import signal
import sys
from typing import List, Dict, Optional

class ProcessInfo:
    def __init__(self, name: str, command: str, autorestart: bool, max_restarts: Optional[int]):
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
        self.processes: Dict[str, ProcessInfo] = {}
        self.running = False
        self.lock = threading.Lock()
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print(f"\nReceived signal {signum}, shutting down...")
        self.stop_all()
    
    def add_process(self, name: str, command: str, autorestart: bool = True, max_restarts: Optional[int] = None):
        """Add a process to be managed
        
        Args:
            name: Unique name for the process
            command: Command to execute
            autorestart: Whether to automatically restart on failure
            max_restarts: Maximum number of restarts (None for infinite)
        """
        with self.lock:
            if name in self.processes:
                raise ValueError(f"Process with name '{name}' already exists")
            
            self.processes[name] = ProcessInfo(name, command, autorestart, max_restarts)
            print(f"Added process: {name} - Command: {command} - Auto-restart: {autorestart} - Max restarts: {max_restarts}")
    
    def _run_process(self, proc_info: ProcessInfo):
        """Run a single process in a thread"""
        while self.running and proc_info.running:
            try:
                print(f"[{proc_info.name}] Starting process...")
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
                        print(f"[{proc_info.name}] {output.strip()}")
                
                # Get remaining output
                for output in proc_info.process.stdout:
                    if output.strip():
                        print(f"[{proc_info.name}] {output.strip()}")
                
                return_code = proc_info.process.wait()
                
                if return_code == 0:
                    print(f"[{proc_info.name}] Process completed successfully")
                    break
                else:
                    print(f"[{proc_info.name}] Process exited with code {return_code}")
                    
                    if not proc_info.autorestart:
                        print(f"[{proc_info.name}] Auto-restart disabled, not restarting")
                        break
                    
                    if proc_info.max_restarts is not None:
                        proc_info.restart_count += 1
                        if proc_info.restart_count >= proc_info.max_restarts:
                            print(f"[{proc_info.name}] Maximum restart limit ({proc_info.max_restarts}) reached")
                            break
                    
                    print(f"[{proc_info.name}] Restarting... (attempt {proc_info.restart_count + 1})")
                    time.sleep(2)  # Wait before restarting
                    
            except Exception as e:
                print(f"[{proc_info.name}] Error: {e}")
                
                if not proc_info.autorestart:
                    break
                    
                if proc_info.max_restarts is not None:
                    proc_info.restart_count += 1
                    if proc_info.restart_count >= proc_info.max_restarts:
                        print(f"[{proc_info.name}] Maximum restart limit ({proc_info.max_restarts}) reached")
                        break
                
                print(f"[{proc_info.name}] Restarting after error... (attempt {proc_info.restart_count + 1})")
                time.sleep(2)
        
        proc_info.running = False
        print(f"[{proc_info.name}] Process thread stopped")
    
    def run(self):
        """Start all processes"""
        if not self.processes:
            print("No processes to run")
            return
        
        self.running = True
        print(f"Starting {len(self.processes)} processes...")
        
        # Start all processes
        for proc_info in self.processes.values():
            proc_info.running = True
            proc_info.thread = threading.Thread(
                target=self._run_process, 
                args=(proc_info,),
                daemon=True
            )
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
                print(f"[{proc_info.name}] Terminating process...")
                proc_info.process.terminate()
                
                # Wait for process to terminate
                try:
                    proc_info.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print(f"[{proc_info.name}] Force killing process...")
                    proc_info.process.kill()
        
        # Wait for threads to finish
        for proc_info in self.processes.values():
            if proc_info.thread and proc_info.thread.is_alive():
                proc_info.thread.join(timeout=3)
        
        print("All processes stopped")

def main():
    """Example usage"""
    runner = ParallelRunner()
    
    # Add processes with different configurations
    runner.add_process(
        "web_server", 
        "python -m http.server 8000", 
        autorestart=True, 
        max_restarts=3
    )
    
    runner.add_process(
        "long_running", 
        "python -c \"import time; i=0; while True: print(f'Running {i}'); i+=1; time.sleep(1)\"", 
        autorestart=True, 
        max_restarts=None  # Infinite restarts
    )
    
    runner.add_process(
        "one_shot", 
        "python -c \"print('One shot task'); exit(0)\"", 
        autorestart=False, 
        max_restarts=None
    )
    
    # Start the runner
    runner.run()

if __name__ == "__main__":
    main()