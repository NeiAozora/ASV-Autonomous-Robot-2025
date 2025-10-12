import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import pygame
import threading
import time
import requests
import uuid
from enum import Enum
from typing import Callable, Dict, List

# Enum untuk tipe event joystick
class JoystickEventType(Enum):
    AXIS = "axis"
    BUTTON = "button"
    HAT = "hat"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"

# Konstanta untuk button PS3
class PS3Button(Enum):
    SELECT = 0
    L3 = 1
    R3 = 2
    START = 3
    UP = 4
    RIGHT = 5
    DOWN = 6
    LEFT = 7
    L2 = 8
    R2 = 9
    L1 = 10
    R1 = 11
    TRIANGLE = 12
    CIRCLE = 13
    CROSS = 14
    SQUARE = 15
    PS = 16

# Konstanta untuk axis PS3
class PS3Axis(Enum):
    LEFT_ANALOG_X = 0
    LEFT_ANALOG_Y = 1
    RIGHT_ANALOG_X = 2
    RIGHT_ANALOG_Y = 3

# Konstanta untuk hat (D-Pad)
class PS3Hat(Enum):
    HAT_0 = 0

# Mode operasi robot
class RobotMode(Enum):
    AUTONOMOUS = "autonomous"
    REMOTE = "remote"

class PS3JoystickApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Universal Robot Controller - PS3 Joystick")
        
        # Variabel untuk koneksi server
        self.server_connected = False
        self.server_host = "http://jetson-api.neiaozora.my.id"
        self.client_id = None
        self.client_name = f"robot_client_{uuid.uuid4().hex[:8]}"
        self.ping_thread = None
        self.ping_running = False
        
        # Mode operasi
        self.current_mode = RobotMode.AUTONOMOUS
        
        # Dictionary untuk menyimpan listener
        self.listeners: Dict[JoystickEventType, List[Callable]] = {
            JoystickEventType.AXIS: [],
            JoystickEventType.BUTTON: [],
            JoystickEventType.HAT: [],
            JoystickEventType.CONNECTED: [],
            JoystickEventType.DISCONNECTED: []
        }
        
        # Nilai sebelumnya untuk deteksi perubahan
        self.previous_axis_values = {}
        self.previous_button_values = {}
        self.previous_hat_values = {}
        
        # Inisialisasi pygame dan joystick
        pygame.init()
        pygame.joystick.init()
        
        self.joystick = None
        self.joystick_count = 0
        
        # Setup UI
        self.setup_ui()
        
        # Coba koneksi joystick
        self.connect_joystick()
        
        # Thread untuk membaca joystick
        self.is_running = True
        self.joystick_thread = threading.Thread(target=self.update_joystick)
        self.joystick_thread.daemon = True
        self.joystick_thread.start()
        
        # Handler saat window ditutup
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def setup_ui(self):
        # Frame untuk status server
        server_frame = ttk.LabelFrame(self.root, text="Status Server")
        server_frame.pack(padx=10, pady=5, fill='x')
        
        # Status koneksi server
        self.server_status_label = ttk.Label(server_frame, text="Server: Tidak Terhubung", foreground="red")
        self.server_status_label.pack(side='left', padx=5)
        
        # Tombol koneksi server
        self.server_connect_button = ttk.Button(server_frame, text="Sambungkan ke Server", 
                                               command=self.toggle_server_connection)
        self.server_connect_button.pack(side='left', padx=5)
        
        # Client ID display
        self.client_id_label = ttk.Label(server_frame, text="Client: -")
        self.client_id_label.pack(side='left', padx=20)
        
        # Frame untuk mode operasi
        mode_frame = ttk.LabelFrame(self.root, text="Mode Operasi Robot")
        mode_frame.pack(padx=10, pady=5, fill='x')
        
        # Variabel untuk radio button
        self.mode_var = tk.StringVar(value=RobotMode.AUTONOMOUS.value)
        
        # Radio button untuk mode
        self.autonomous_radio = ttk.Radiobutton(mode_frame, text="Autonomous", 
                                               variable=self.mode_var, 
                                               value=RobotMode.AUTONOMOUS.value,
                                               command=self.on_mode_change)
        self.autonomous_radio.pack(side='left', padx=10)
        
        self.remote_radio = ttk.Radiobutton(mode_frame, text="Remote", 
                                           variable=self.mode_var, 
                                           value=RobotMode.REMOTE.value,
                                           command=self.on_mode_change)
        self.remote_radio.pack(side='left', padx=10)
        
        # Status mode dari server
        self.mode_status_label = ttk.Label(mode_frame, text="Mode server: -")
        self.mode_status_label.pack(side='left', padx=20)
        
        # Non-aktifkan radio button sampai terhubung ke server
        self.autonomous_radio.config(state='disabled')
        self.remote_radio.config(state='disabled')
        
        # Frame untuk kontrol joystick
        control_frame = ttk.Frame(self.root)
        control_frame.pack(padx=10, pady=5, fill='x')
        
        # Tombol refresh joystick
        self.refresh_button = ttk.Button(control_frame, text="Refresh Joystick", command=self.refresh_joystick)
        self.refresh_button.pack(side='left', padx=5)
        
        # Status koneksi joystick
        self.joystick_status_label = ttk.Label(control_frame, text="Joystick: Mencari...", foreground="orange")
        self.joystick_status_label.pack(side='left', padx=20)
        
        # Frame untuk menampilkan nilai joystick
        self.joystick_frame = ttk.LabelFrame(self.root, text="Joystick PS3")
        self.joystick_frame.pack(padx=10, pady=10, fill='both', expand=True)
        
        # Label untuk sumbu (axes)
        self.axes_frame = ttk.LabelFrame(self.joystick_frame, text="Sumbu (Axes)")
        self.axes_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        
        self.axes_labels = []
        axes_info = [
            ("Left Analog X", PS3Axis.LEFT_ANALOG_X),
            ("Left Analog Y", PS3Axis.LEFT_ANALOG_Y),
            ("Right Analog X", PS3Axis.RIGHT_ANALOG_X),
            ("Right Analog Y", PS3Axis.RIGHT_ANALOG_Y)
        ]
        
        for i, (name, axis) in enumerate(axes_info):
            ttk.Label(self.axes_frame, text=f"{name}:").grid(row=i, column=0, sticky='w', padx=5)
            label = ttk.Label(self.axes_frame, text="0.000", width=10)
            label.grid(row=i, column=1, sticky='w', padx=5)
            self.axes_labels.append((label, axis))
        
        # Label untuk tombol (buttons)
        self.buttons_frame = ttk.LabelFrame(self.joystick_frame, text="Tombol (Buttons)")
        self.buttons_frame.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
        
        self.button_labels = []
        buttons_info = [
            ("SELECT", PS3Button.SELECT),
            ("START", PS3Button.START),
            ("UP", PS3Button.UP),
            ("RIGHT", PS3Button.RIGHT),
            ("DOWN", PS3Button.DOWN),
            ("LEFT", PS3Button.LEFT),
            ("L2", PS3Button.L2),
            ("R2", PS3Button.R2),
            ("L1", PS3Button.L1),
            ("R1", PS3Button.R1),
            ("TRIANGLE", PS3Button.TRIANGLE),
            ("CIRCLE", PS3Button.CIRCLE),
            ("CROSS", PS3Button.CROSS),
            ("SQUARE", PS3Button.SQUARE),
            ("PS", PS3Button.PS)
        ]
        
        for i, (name, button) in enumerate(buttons_info):
            ttk.Label(self.buttons_frame, text=f"{name}:").grid(row=i, column=0, sticky='w', padx=5)
            label = ttk.Label(self.buttons_frame, text="OFF", width=8)
            label.grid(row=i, column=1, sticky='w', padx=5)
            self.button_labels.append((label, button))
        
        # Frame untuk hat (D-Pad)
        self.hat_frame = ttk.LabelFrame(self.joystick_frame, text="D-Pad (Hat)")
        self.hat_frame.grid(row=0, column=2, sticky='nsew', padx=5, pady=5)
        
        self.hat_label = ttk.Label(self.hat_frame, text="(0, 0)")
        self.hat_label.pack(padx=5, pady=5)
        
        # Frame untuk event log
        self.log_frame = ttk.LabelFrame(self.root, text="Event Log")
        self.log_frame.pack(padx=10, pady=10, fill='both', expand=True)
        
        # Frame untuk kontrol log
        log_control_frame = ttk.Frame(self.log_frame)
        log_control_frame.pack(fill='x', padx=5, pady=5)
        
        ttk.Button(log_control_frame, text="Clear Log", command=self.clear_log).pack(side='left')
        
        self.auto_scroll = True
        self.auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(log_control_frame, text="Auto Scroll", variable=self.auto_scroll_var, 
                       command=self.toggle_auto_scroll).pack(side='left', padx=5)
        
        self.log_text = tk.Text(self.log_frame, height=8, width=80)
        self.log_scrollbar = ttk.Scrollbar(self.log_frame, orient='vertical', command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.log_scrollbar.set)
        self.log_text.pack(side='left', fill='both', expand=True, padx=(5, 0))
        self.log_scrollbar.pack(side='right', fill='y', padx=(0, 5))
        
        # Configure grid weights
        self.joystick_frame.columnconfigure(0, weight=1)
        self.joystick_frame.columnconfigure(1, weight=1)
        self.joystick_frame.columnconfigure(2, weight=1)
        self.joystick_frame.rowconfigure(0, weight=1)
    
    def toggle_server_connection(self):
        """Menghubungkan atau memutuskan koneksi ke server"""
        if not self.server_connected:
            self.connect_to_server()
        else:
            self.disconnect_from_server()
    
    def connect_to_server(self):
        """Menghubungkan ke server robot"""
        try:
            self.log_event("Menghubungkan ke server...")
            
            # Coba koneksi ke server endpoint root
            response = requests.get(f"{self.server_host}/", timeout=5)
            if response.status_code == 200:
                self.log_event("Server merespons, mendaftarkan client...")
                
                # Register client
                connect_data = {"client_name": self.client_name}
                response = requests.post(f"{self.server_host}/connect", json=connect_data, timeout=5)
                
                if response.status_code == 200:
                    result = response.json()
                    self.client_id = result["client_id"]
                    self.server_connected = True
                    self.update_server_status()
                    
                    # Ambil status mode dari server
                    self.fetch_current_mode()
                    
                    # Mulai ping secara berkala
                    self.start_ping()
                    
                    # Aktifkan radio button mode
                    self.autonomous_radio.config(state='normal')
                    self.remote_radio.config(state='normal')
                    
                    self.log_event(f"Berhasil terhubung ke server. Client ID: {self.client_id}")
                else:
                    error_msg = f"Gagal mendaftar client: {response.status_code} - {response.text}"
                    self.log_event(error_msg)
                    raise Exception(error_msg)
            else:
                error_msg = f"Server tidak merespons dengan benar: {response.status_code}"
                self.log_event(error_msg)
                raise Exception(error_msg)
                
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Tidak dapat terhubung ke server: {str(e)}"
            self.log_event(error_msg)
            messagebox.showerror("Koneksi Gagal", f"Tidak dapat terhubung ke server di {self.server_host}. Pastikan server berjalan.")
        except Exception as e:
            error_msg = f"Gagal terhubung ke server: {str(e)}"
            self.log_event(error_msg)
            messagebox.showerror("Koneksi Gagal", f"Tidak dapat terhubung ke server: {str(e)}")
    
    def disconnect_from_server(self):
        """Memutuskan koneksi dari server"""
        self.server_connected = False
        self.stop_ping()
        self.update_server_status()
        
        # Non-aktifkan radio button mode
        self.autonomous_radio.config(state='disabled')
        self.remote_radio.config(state='disabled')
        
        self.client_id = None
        self.client_id_label.config(text="Client: -")
        self.mode_status_label.config(text="Mode server: -")
        
        self.log_event("Koneksi server diputus")
    
    def update_server_status(self):
        """Memperbarui tampilan status server"""
        if self.server_connected:
            self.server_status_label.config(text="Server: Terhubung", foreground="green")
            self.server_connect_button.config(text="Putus dari Server")
            if self.client_id:
                self.client_id_label.config(text=f"Client: {self.client_id[:8]}...")
        else:
            self.server_status_label.config(text="Server: Tidak Terhubung", foreground="red")
            self.server_connect_button.config(text="Sambungkan ke Server")
            self.client_id_label.config(text="Client: -")
    
    def fetch_current_mode(self):
        """Mengambil mode saat ini dari server"""
        try:
            response = requests.get(f"{self.server_host}/mode", timeout=5)
            if response.status_code == 200:
                result = response.json()
                server_mode = RobotMode(result["mode"])
                self.current_mode = server_mode
                self.mode_var.set(server_mode.value)
                self.mode_status_label.config(text=f"Mode server: {server_mode.value}")
                self.log_event(f"Mode dari server: {server_mode.value}")
            else:
                raise Exception(f"Gagal mendapatkan mode: {response.status_code}")
        except Exception as e:
            self.log_event(f"Gagal mengambil mode dari server: {str(e)}")
    
    def on_mode_change(self):
        """Handler ketika mode diubah"""
        if not self.server_connected:
            messagebox.showwarning("Tidak Terhubung", "Harap terhubung ke server terlebih dahulu!")
            # Kembalikan ke mode sebelumnya
            self.mode_var.set(self.current_mode.value)
            return
        
        new_mode = RobotMode(self.mode_var.get())
        
        # Kirim perubahan mode ke server
        self.send_mode_to_server(new_mode)
    
    def send_mode_to_server(self, mode: RobotMode):
        """Mengirim perubahan mode ke server"""
        try:
            mode_data = {
                "mode": mode.value,
                "client_id": self.client_id
            }
            
            response = requests.post(f"{self.server_host}/mode", json=mode_data, timeout=5)
            
            if response.status_code == 200:
                result = response.json()
                self.current_mode = mode
                self.mode_status_label.config(text=f"Mode server: {mode.value}")
                self.log_event(f"Mode berhasil diubah ke: {mode.value}")
                
                if mode == RobotMode.REMOTE:
                    self.log_event("Sekarang Anda dapat mengontrol robot dengan joystick!")
            else:
                error_detail = response.json().get('detail', 'Unknown error')
                raise Exception(f"Server error: {error_detail}")
                
        except Exception as e:
            self.log_event(f"Gagal mengirim mode ke server: {str(e)}")
            messagebox.showerror("Gagal", f"Tidak dapat mengubah mode: {str(e)}")
            # Kembalikan ke mode sebelumnya
            self.mode_var.set(self.current_mode.value)
    
    def start_ping(self):
        """Memulai ping berkala ke server"""
        self.ping_running = True
        self.ping_thread = threading.Thread(target=self.ping_loop)
        self.ping_thread.daemon = True
        self.ping_thread.start()
    
    def stop_ping(self):
        """Menghentikan ping berkala"""
        self.ping_running = False
    
    def ping_loop(self):
        """Loop untuk ping berkala ke server"""
        while self.ping_running and self.server_connected:
            try:
                ping_data = {"client_id": self.client_id}
                response = requests.post(f"{self.server_host}/ping", json=ping_data, timeout=5)
                
                if response.status_code == 200:
                    result = response.json()
                    # Update mode jika berubah di server
                    server_mode = RobotMode(result["current_mode"])
                    if server_mode != self.current_mode:
                        self.current_mode = server_mode
                        self.mode_var.set(server_mode.value)
                        self.mode_status_label.config(text=f"Mode server: {server_mode.value}")
                        self.log_event(f"Mode diperbarui dari server: {server_mode.value}")
                    
                    # Log ping berhasil (opsional, bisa di-comment)
                    # self.log_event("Ping ke server: OK", log_type="debug")
                else:
                    raise Exception(f"Ping gagal: {response.status_code}")
                    
            except Exception as e:
                self.log_event(f"Ping gagal: {str(e)}")
                # Jika ping gagal, putuskan koneksi
                self.server_connected = False
                self.update_server_status()
                self.log_event("Koneksi server terputus")
                break
            
            time.sleep(1)  # Ping setiap 1 detik
    
    def refresh_joystick(self):
        """Refresh koneksi joystick"""
        self.log_event("Mencari joystick...")
        
        # Reset status sebelumnya
        if self.joystick:
            try:
                self.joystick.quit()
            except:
                pass
            self.joystick = None
        
        # Reset nilai tampilan
        for label, axis in self.axes_labels:
            label.config(text="0.000")
        
        for label, button in self.button_labels:
            label.config(text="OFF", foreground="black")
        
        self.hat_label.config(text="(0, 0)")
        
        # Coba koneksi ulang
        self.connect_joystick()
    
    def connect_joystick(self):
        """Menghubungkan ke joystick yang tersedia"""
        try:
            # Reinit joystick system
            pygame.joystick.quit()
            pygame.joystick.init()
            
            self.joystick_count = pygame.joystick.get_count()
            if self.joystick_count > 0:
                self.joystick = pygame.joystick.Joystick(0)
                self.joystick.init()
                
                status_text = f"Joystick: {self.joystick.get_name()}"
                self.joystick_status_label.config(text=status_text, foreground="green")
                self._notify_listeners(JoystickEventType.CONNECTED, {"name": self.joystick.get_name()})
                self.log_event(f"Joystick terhubung: {self.joystick.get_name()}")
                
            else:
                self.joystick = None
                self.joystick_status_label.config(text="Joystick: Tidak terdeteksi", foreground="red")
                self._notify_listeners(JoystickEventType.DISCONNECTED, {})
                self.log_event("Tidak ada joystick terdeteksi")
                
        except Exception as e:
            self.joystick = None
            self.joystick_status_label.config(text=f"Joystick: Error", foreground="red")
            self.log_event(f"Error menghubungkan joystick: {str(e)}")
    
    def add_listener(self, event_type: JoystickEventType, callback: Callable):
        """Menambahkan listener untuk event joystick tertentu"""
        if event_type in self.listeners:
            self.listeners[event_type].append(callback)
    
    def _notify_listeners(self, event_type: JoystickEventType, data: Dict):
        """Memberitahu semua listener tentang event"""
        for callback in self.listeners[event_type]:
            try:
                callback(data)
            except Exception as e:
                self.log_event(f"Error dalam listener: {str(e)}")
    
    def log_event(self, message: str, log_type: str = "info"):
        """Menambahkan pesan ke log"""
        def update_log():
            timestamp = time.strftime('%H:%M:%S')
            if log_type == "debug":
                # Skip debug logs in normal operation
                return
            self.log_text.insert('end', f"{timestamp} - {message}\n")
            if self.auto_scroll:
                self.log_text.see('end')
        
        # Thread-safe update GUI
        if self.root and hasattr(self.root, 'winfo_exists') and self.root.winfo_exists():
            self.root.after(0, update_log)
    
    def clear_log(self):
        """Membersihkan log"""
        self.log_text.delete('1.0', 'end')
    
    def toggle_auto_scroll(self):
        """Mengaktifkan/menonaktifkan auto scroll"""
        self.auto_scroll = self.auto_scroll_var.get()
    
    def send_joystick_data(self, data_type: str, data: Dict):
        """Mengirim data joystick ke server (hanya dalam mode remote)"""
        if not self.server_connected or self.current_mode != RobotMode.REMOTE or not self.client_id:
            return
        
        try:
            # Siapkan data untuk dikirim
            joystick_data = {
                "client_id": self.client_id,
                "data_type": data_type
            }
            
            if data_type == "axis":
                joystick_data["axis"] = data['axis']
                joystick_data["value"] = data['value']
                joystick_data["axis_name"] = data['axis_name']
            elif data_type == "button":
                joystick_data["button"] = data['button']
                joystick_data["pressed"] = data['pressed']
                joystick_data["button_name"] = data['button_name']
            elif data_type == "hat":
                joystick_data["hat"] = data['hat']
                joystick_data["hat_value"] = list(data['value'])
            
            # Gunakan timeout pendek untuk joystick data
            response = requests.post(f"{self.server_host}/joystick", json=joystick_data, timeout=0.5)
            
            if response.status_code != 200:
                error_detail = response.json().get('detail', 'Unknown error')
                if "REMOTE mode" in error_detail:
                    # Server menolak karena bukan mode remote
                    pass
                    
        except requests.exceptions.Timeout:
            # Timeout adalah normal untuk data joystick yang sering
            pass
        except Exception as e:
            # Jangan log error untuk joystick data yang sering
            pass
    
    def update_joystick(self):
        """Thread untuk membaca data joystick secara kontinu"""
        while self.is_running:
            if self.joystick is None:
                time.sleep(1)
                continue
            
            try:
                pygame.event.pump()  # Proses event queue
                
                # Update axes
                for i in range(self.joystick.get_numaxes()):
                    axis_value = self.joystick.get_axis(i)
                    
                    # Update UI
                    for label, axis in self.axes_labels:
                        if axis.value == i:
                            label.config(text=f"{axis_value:6.3f}")
                    
                    # Cek perubahan dan notify listener
                    if i not in self.previous_axis_values or abs(self.previous_axis_values[i] - axis_value) > 0.01:
                        self.previous_axis_values[i] = axis_value
                        event_data = {
                            'axis': i,
                            'value': axis_value,
                            'axis_name': PS3Axis(i).name if i in [a.value for a in PS3Axis] else f"AXIS_{i}"
                        }
                        self._notify_listeners(JoystickEventType.AXIS, event_data)
                        self.send_joystick_data("axis", event_data)
                
                # Update buttons
                for i in range(self.joystick.get_numbuttons()):
                    button_state = self.joystick.get_button(i)
                    
                    # Update UI
                    for label, button in self.button_labels:
                        if button.value == i:
                            state_text = "ON" if button_state else "OFF"
                            color = "red" if button_state else "black"
                            label.config(text=state_text, foreground=color)
                    
                    # Cek perubahan dan notify listener
                    if i not in self.previous_button_values or self.previous_button_values[i] != button_state:
                        self.previous_button_values[i] = button_state
                        event_data = {
                            'button': i,
                            'pressed': bool(button_state),
                            'button_name': PS3Button(i).name if i in [b.value for b in PS3Button] else f"BUTTON_{i}"
                        }
                        self._notify_listeners(JoystickEventType.BUTTON, event_data)
                        self.send_joystick_data("button", event_data)
                
                # Update hat (D-Pad)
                for i in range(self.joystick.get_numhats()):
                    hat_value = self.joystick.get_hat(i)
                    
                    # Update UI
                    if i == 0:  # Biasanya hanya 1 hat (D-Pad)
                        self.hat_label.config(text=str(hat_value))
                    
                    # Cek perubahan dan notify listener
                    if i not in self.previous_hat_values or self.previous_hat_values[i] != hat_value:
                        self.previous_hat_values[i] = hat_value
                        event_data = {
                            'hat': i,
                            'value': hat_value
                        }
                        self._notify_listeners(JoystickEventType.HAT, event_data)
                        self.send_joystick_data("hat", event_data)
                
            except pygame.error as e:
                error_msg = f"Error membaca joystick: {str(e)}"
                self.log_event(error_msg)
                self.joystick_status_label.config(text=error_msg, foreground="red")
                self.joystick = None
                self._notify_listeners(JoystickEventType.DISCONNECTED, {})
            
            time.sleep(0.05)  # Update setiap 50ms
    
    def on_closing(self):
        """Handler saat window ditutup"""
        self.is_running = False
        self.stop_ping()
        pygame.quit()
        self.root.destroy()

def main():
    root = tk.Tk()
    root.geometry("800x600")
    
    app = PS3JoystickApp(root)
    
    # Contoh listener untuk logging
    def button_listener(data):
        if data['pressed']:
            app.log_event(f"Tombol {data['button_name']} DITEKAN")
    
    def axis_listener(data):
        if abs(data['value']) > 0.1:
            app.log_event(f"Axis {data['axis_name']} berubah: {data['value']:.3f}")
    
    # Daftarkan listener
    app.add_listener(JoystickEventType.AXIS, axis_listener)
    app.add_listener(JoystickEventType.BUTTON, button_listener)
    
    root.mainloop()

if __name__ == "__main__":
    main()