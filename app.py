import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
from datetime import datetime, timedelta
import hashlib
import uuid
import os
import logging
from contextlib import contextmanager
from typing import Optional, Dict, List, Any

# --- LOGGING SETUP ---
logging.basicConfig(
    filename='hospital.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- SECURITY CONFIG ---
PBKDF2_ITERATIONS = 100000
SESSION_TIMEOUT = 1800  # 30 menit

# --- DATABASE SCHEMA VERSIONING ---
SCHEMA_VERSION = 2

# ==== IMPROVED DATABASE LAYER ====
class DatabaseManager:
    def __init__(self, db_name='hospital.db'):
        self.db_name = db_name
        self._init_db()
        self._migrate_db()

    @contextmanager
    def _get_connection(self):
        """Context manager untuk koneksi database yang aman"""
        conn = sqlite3.connect(self.db_name)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except sqlite3.Error as e:
            logging.error(f"Database error: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            c = conn.cursor()
            
            # Tabel metadata version
            c.execute('''CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY
                    )''')
            
            # Tabel Pengguna dengan session management
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        username TEXT UNIQUE,
                        password_hash TEXT,
                        salt TEXT,
                        role TEXT,
                        last_login DATETIME,
                        failed_attempts INTEGER DEFAULT 0,
                        locked_until DATETIME
                    )''')
            
            # Tabel Pasien dengan indexing
            c.execute('''CREATE TABLE IF NOT EXISTS patients (
                        id TEXT PRIMARY KEY,
                        nama TEXT,
                        nik TEXT UNIQUE CHECK(LENGTH(nik) == 16 AND nik GLOB '[0-9]*'),
                        umur INTEGER CHECK(umur BETWEEN 0 AND 120),
                        poli TEXT,
                        urgency TEXT CHECK(urgency IN ('UGD', 'Reguler')),
                        registration_time DATETIME
                    )''')
            
            # Tabel Antrian dengan indexing
            c.execute('''CREATE TABLE IF NOT EXISTS queues (
                        id TEXT PRIMARY KEY,
                        patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
                        queue_number TEXT UNIQUE,
                        status TEXT CHECK(status IN ('Menunggu', 'Diproses', 'Selesai')),
                        created_at DATETIME,
                        completed_at DATETIME
                    )''')
            
            # Index untuk performa
            c.execute('''CREATE INDEX IF NOT EXISTS idx_queues_status 
                      ON queues(status)''')
            c.execute('''CREATE INDEX IF NOT EXISTS idx_patients_urgency 
                      ON patients(urgency)''')
            
            conn.commit()

    def _migrate_db(self):
        """Database migration system"""
        with self._get_connection() as conn:
            c = conn.cursor()
            current_version = c.execute("SELECT version FROM schema_version").fetchone()
            current_version = current_version[0] if current_version else 0
            
            # Migrasi versi 1
            if current_version < 1:
                try:
                    c.execute('''ALTER TABLE users 
                              ADD COLUMN failed_attempts INTEGER DEFAULT 0''')
                    c.execute('''ALTER TABLE users 
                              ADD COLUMN locked_until DATETIME''')
                except sqlite3.OperationalError:
                    pass  # Kolom sudah ada
                
            # Migrasi versi 2
            if current_version < 2:
                try:
                    c.execute('''ALTER TABLE queues 
                              ADD COLUMN completed_at DATETIME''')
                except sqlite3.OperationalError:
                    pass  # Kolom sudah ada
                
            c.execute("INSERT OR REPLACE INTO schema_version VALUES (?)", 
                     (SCHEMA_VERSION,))
            conn.commit()

    # ==== SECURITY METHODS ====
    @staticmethod
    def hash_password(password: str, salt: bytes = None) -> tuple:
        """Generate secure password hash dengan PBKDF2"""
        salt = salt or os.urandom(32)
        key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            PBKDF2_ITERATIONS
        )
        return salt, key

    def create_admin(self):
        """Buat admin default dengan credential yang aman"""
        with self._get_connection() as conn:
            c = conn.cursor()
            if not c.execute("SELECT * FROM users WHERE username='admin'").fetchone():
                admin_id = str(uuid.uuid4())
                salt, key = self.hash_password("admin123")
                c.execute('''INSERT INTO users 
                          (id, username, password_hash, salt, role) 
                          VALUES (?,?,?,?,?)''',
                         (admin_id, 'admin', key, salt, 'admin'))
                conn.commit()

# ==== DATA MODELS ====
class UserSession:
    def __init__(self, user_data: dict):
        self.user_id = user_data['id']
        self.username = user_data['username']
        self.role = user_data['role']
        self.session_expiry = datetime.now() + timedelta(seconds=SESSION_TIMEOUT)
        self.token = uuid.uuid4().hex

# ==== IMPROVED UI COMPONENTS ====
class QueueCard(tk.Frame):
    def __init__(self, parent, queue_data: dict, on_process):
        super().__init__(parent, bg='#ffffff', bd=1, relief='groove')
        self.queue_id = queue_data['id']
        self._setup_ui(queue_data, on_process)
        
    def _setup_ui(self, data: dict, callback):
        color = '#e74c3c' if data['urgency'] == 'UGD' else '#3498db'
        status_color = '#2ecc71' if data['status'] == 'Diproses' else '#95a5a6'
        
        self.grid_columnconfigure(0, weight=4)
        self.grid_columnconfigure(1, weight=1)
        
        tk.Label(self, text=data['queue_number'], font=('Helvetica', 14, 'bold'),
                fg=color, bg='#ffffff').grid(row=0, column=0, sticky='w')
        
        tk.Label(self, text=data['nama'], font=('Helvetica', 12),
                bg='#ffffff').grid(row=1, column=0, sticky='w')
        
        tk.Label(self, text=f"{data['poli']} • {data['status']}", 
                font=('Helvetica', 10), fg=status_color,
                bg='#ffffff').grid(row=2, column=0, sticky='w')
        
        wait_time = datetime.now() - datetime.fromisoformat(data['created_at'])
        tk.Label(self, text=f"Menunggu: {wait_time.seconds//60}m", 
                font=('Helvetica', 9), fg='#7f8c8d',
                bg='#ffffff').grid(row=3, column=0, sticky='w')
        
        btn_state = 'normal' if data['status'] == 'Menunggu' else 'disabled'
        ttk.Button(self, text="Proses", command=lambda: callback(self.queue_id),
                  state=btn_state).grid(row=0, column=1, rowspan=4, padx=5)

# ==== MAIN APPLICATION IMPROVEMENTS ====
class HospitalQueueSystem(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sistem Antrian Rumah Sakit Modern")
        self.geometry("1280x720")
        self.minsize(1024, 600)
        
        self.db = DatabaseManager()
        self.db.create_admin()
        self.current_session: Optional[UserSession] = None
        self.queue_cache: Dict[str, dict] = {}
        
        self._setup_style()
        self.show_login()
        self.after(30000, self.auto_refresh)
    
    def _setup_style(self):
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self.style.configure('TFrame', background='#f5f6fa')
        self.style.configure('TButton', font=('Helvetica', 10), padding=6)
        self.style.map('TButton', 
                      foreground=[('active', 'white'), ('!active', 'white')],
                      background=[('active', '#3498db'), ('!active', '#2980b9')])
    
    def clear_window(self):
        for widget in self.winfo_children():
            widget.destroy()
    
    def validate_session(self):
        if not self.current_session or datetime.now() > self.current_session.session_expiry:
            self.current_session = None
            self.show_login()
            return False
        return True
    
    def auto_refresh(self):
        if self.validate_session():
            self.refresh_queues(force=False)
        self.after(30000, self.auto_refresh)
    
    # ==== IMPROVED LOGIN SYSTEM ====
    def show_login(self):
        self.clear_window()
        login_frame = ttk.Frame(self)
        login_frame.place(relx=0.5, rely=0.5, anchor='center')
        
        tk.Label(login_frame, text="LOGIN SISTEM", 
                font=('Helvetica', 18, 'bold')).grid(row=0, column=0, pady=20)
        
        tk.Label(login_frame, text="Username").grid(row=1, column=0, sticky='w')
        self.username_entry = ttk.Entry(login_frame)
        self.username_entry.grid(row=2, column=0, pady=5)
        
        tk.Label(login_frame, text="Password").grid(row=3, column=0, sticky='w')
        self.password_entry = ttk.Entry(login_frame, show="*")
        self.password_entry.grid(row=4, column=0, pady=5)
        
        ttk.Button(login_frame, text="Masuk", command=self.do_login).grid(row=5, column=0, pady=20)
    
    def do_login(self):
        username = self.username_entry.get()
        password = self.password_entry.get()
        
        with self.db._get_connection() as conn:
            c = conn.cursor()
            user = c.execute('''SELECT * FROM users 
                              WHERE username=?''', (username,)).fetchone()
            
            if not user:
                messagebox.showerror("Error", "User tidak ditemukan")
                return
            
            if user['locked_until'] and datetime.now() < datetime.fromisoformat(user['locked_until']):
                remaining = datetime.fromisoformat(user['locked_until']) - datetime.now()
                messagebox.showerror("Akun Terkunci", 
                    f"Akun terkunci selama {remaining.seconds//60} menit")
                return
            
            salt = user['salt']
            stored_hash = user['password_hash']
            new_hash = self.db.hash_password(password, salt)[1]
            
            if new_hash != stored_hash:
                failed_attempts = user['failed_attempts'] + 1
                if failed_attempts >= 3:
                    lock_time = datetime.now() + timedelta(minutes=15)
                    c.execute('''UPDATE users 
                               SET failed_attempts=?, locked_until=?
                               WHERE id=?''',
                             (failed_attempts, lock_time.isoformat(), user['id']))
                    conn.commit()
                    messagebox.showerror("Akun Terkunci", "Terlalu banyak percobaan gagal. Akun terkunci 15 menit")
                else:
                    c.execute('''UPDATE users 
                               SET failed_attempts=?
                               WHERE id=?''',
                             (failed_attempts, user['id']))
                    conn.commit()
                    messagebox.showerror("Error", f"Password salah. Percobaan tersisa: {3 - failed_attempts}")
                return
            
            # Reset failed attempts
            c.execute('''UPDATE users 
                       SET failed_attempts=0, locked_until=NULL, last_login=?
                       WHERE id=?''',
                     (datetime.now().isoformat(), user['id']))
            conn.commit()
            
            self.current_session = UserSession(user)
            self.show_main_app()
    
    def show_main_app(self):
        self.clear_window()
        
        # Header
        header = ttk.Frame(self)
        header.pack(fill='x', padx=20, pady=10)
        
        tk.Label(header, text="SISTEM ANTRIAN RUMAH SAKIT", 
                font=('Helvetica', 20, 'bold')).pack(side='left')
        
        self.time_label = tk.Label(header, font=('Helvetica', 12))
        self.time_label.pack(side='right')
        self.update_clock()
        
        # Main Content
        main_container = ttk.Frame(self)
        main_container.pack(fill='both', expand=True, padx=20, pady=10)
        
        # Panel Kiri - Registrasi Pasien
        left_panel = ttk.Frame(main_container)
        left_panel.pack(side='left', fill='y', padx=10)
        self.setup_registration_form(left_panel)
        
        # Panel Kanan - Antrian
        right_panel = ttk.Frame(main_container)
        right_panel.pack(side='right', fill='both', expand=True, padx=10)
        self.setup_queue_display(right_panel)
        
        ttk.Button(self, text="Proses Antrian Berikutnya",
                 command=self.process_next_queue).pack(pady=10)
    
    def update_clock(self):
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.time_label.config(text=now)
        self.after(1000, self.update_clock)
    
    def setup_registration_form(self, parent):
        form_frame = ttk.LabelFrame(parent, text="Registrasi Pasien Baru")
        form_frame.pack(fill='y', padx=10, pady=10)
        
        fields = [
            ('Nama Lengkap', 'nama'),
            ('NIK', 'nik'),
            ('Umur', 'umur'),
            ('Poli Tujuan', 'poli')
        ]
        
        self.reg_vars: Dict[str, tk.StringVar] = {}
        for idx, (label, field) in enumerate(fields):
            tk.Label(form_frame, text=label).grid(row=idx, column=0, sticky='w', pady=5)
            self.reg_vars[field] = tk.StringVar()
            ttk.Entry(form_frame, textvariable=self.reg_vars[field]).grid(
                row=idx, column=1, pady=5, ipadx=30)
        
        self.poli_var = tk.StringVar()
        poli_options = ['Umum', 'Kandungan', 'Anak', 'Bedah', 'Jantung', 'UGD']
        ttk.Combobox(form_frame, textvariable=self.poli_var, 
                    values=poli_options, state='readonly').grid(
                        row=4, column=1, pady=5, sticky='ew')
        
        self.ugd_var = tk.BooleanVar()
        ttk.Checkbutton(form_frame, text="Prioritas UGD", 
                       variable=self.ugd_var).grid(row=5, columnspan=2, pady=5)
        
        ttk.Button(form_frame, text="Daftarkan Pasien", 
                 command=self.register_patient).grid(
                     row=6, columnspan=2, pady=10, sticky='ew')
    
    def _parse_age(self) -> Optional[int]:
        try:
            return int(self.reg_vars['umur'].get())
        except ValueError:
            messagebox.showerror("Error", "Umur harus angka")
            return None
    
    def validate_patient(self, data: dict) -> bool:
        errors = []
        
        if len(data['nik']) != 16 or not data['nik'].isdigit():
            errors.append("NIK harus 16 digit angka")
            
        if not data['nama'].strip():
            errors.append("Nama harus diisi")
            
        if errors:
            messagebox.showerror("Validasi Gagal", "\n".join(errors))
            return False
        return True
    
    def register_patient(self):
        patient_data = {
            'nama': self.reg_vars['nama'].get().strip(),
            'nik': self.reg_vars['nik'].get(),
            'umur': self._parse_age(),
            'poli': self.poli_var.get(),
            'urgency': 'UGD' if self.ugd_var.get() else 'Reguler'
        }
        
        if None in patient_data.values() or not self.validate_patient(patient_data):
            return
        
        with self.db._get_connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                c = conn.cursor()
                
                patient_id = str(uuid.uuid4())
                c.execute('''INSERT INTO patients 
                          VALUES (?,?,?,?,?,?,?)''',
                         (patient_id, 
                          patient_data['nama'],
                          patient_data['nik'],
                          patient_data['umur'],
                          patient_data['poli'],
                          patient_data['urgency'],
                          datetime.now()))
                
                queue_number = self._generate_queue_number(conn, patient_data['urgency'])
                queue_id = str(uuid.uuid4())
                
                c.execute('''INSERT INTO queues 
                          VALUES (?,?,?,?,?,?)''',
                         (queue_id, 
                          patient_id, 
                          queue_number, 
                          'Menunggu', 
                          datetime.now(), 
                          None))
                
                conn.commit()
                self.refresh_queues()
                messagebox.showinfo("Sukses", f"Nomor Antrian: {queue_number}")
                
            except sqlite3.IntegrityError as e:
                conn.rollback()
                messagebox.showerror("Error", "NIK sudah terdaftar" if "nik" in str(e) else "Duplikasi data")
                logging.error(f"Registration error: {e}")
            except Exception as e:
                conn.rollback()
                messagebox.showerror("Error", f"Terjadi kesalahan sistem: {str(e)}")
                logging.critical(f"Critical error: {e}")
    
    def _generate_queue_number(self, conn: sqlite3.Connection, urgency: str) -> str:
        c = conn.cursor()
        jenis = 'UGD' if urgency == 'UGD' else 'REG'
        poli_code = self.poli_var.get()[:3].upper()
        
        c.execute('''SELECT queue_number FROM queues 
                  WHERE queue_number LIKE ? 
                  ORDER BY created_at DESC 
                  LIMIT 1''',
                (f"{jenis}-{poli_code}%",))
        
        last = c.fetchone()
        sequence = int(last[0][-4:]) + 1 if last else 1
        return f"{jenis}-{poli_code}{sequence:04d}"
    
    def setup_queue_display(self, parent):
        container = ttk.Frame(parent)
        container.pack(fill='both', expand=True)
        
        # Antrian UGD
        ugd_frame = ttk.LabelFrame(container, text="Prioritas UGD")
        ugd_frame.pack(side='left', fill='both', expand=True, padx=5)
        
        self.ugd_canvas = tk.Canvas(ugd_frame, bg='#ffffff')
        scrollbar = ttk.Scrollbar(ugd_frame, orient='vertical', command=self.ugd_canvas.yview)
        self.ugd_canvas.configure(yscrollcommand=scrollbar.set)
        
        self.ugd_content = ttk.Frame(self.ugd_canvas)
        self.ugd_canvas.create_window((0,0), window=self.ugd_content, anchor='nw')
        
        scrollbar.pack(side='right', fill='y')
        self.ugd_canvas.pack(side='left', fill='both', expand=True)
        
        # Antrian Reguler
        regular_frame = ttk.LabelFrame(container, text="Antrian Reguler")
        regular_frame.pack(side='right', fill='both', expand=True, padx=5)
        
        self.regular_canvas = tk.Canvas(regular_frame, bg='#ffffff')
        scrollbar_reg = ttk.Scrollbar(regular_frame, orient='vertical', 
                                    command=self.regular_canvas.yview)
        self.regular_canvas.configure(yscrollcommand=scrollbar_reg.set)
        
        self.regular_content = ttk.Frame(self.regular_canvas)
        self.regular_canvas.create_window((0,0), window=self.regular_content, anchor='nw')
        
        scrollbar_reg.pack(side='right', fill='y')
        self.regular_canvas.pack(side='left', fill='both', expand=True)
        
        self.refresh_queues()
    
    def refresh_queues(self, force=True):
        new_queues = self._fetch_queues()
        
        if not force and new_queues == self.queue_cache:
            return
        
        for widget in self.ugd_content.winfo_children():
            widget.destroy()
        for widget in self.regular_content.winfo_children():
            widget.destroy()
        
        for q_id, q_data in new_queues.items():
            parent = self.ugd_content if q_data['urgency'] == 'UGD' else self.regular_content
            QueueCard(parent, q_data, self.process_queue).pack(fill='x', pady=2)
        
        self.ugd_canvas.configure(scrollregion=self.ugd_canvas.bbox("all"))
        self.regular_canvas.configure(scrollregion=self.regular_canvas.bbox("all"))
        self.queue_cache = new_queues
    
    def _fetch_queues(self) -> Dict[str, dict]:
        with self.db._get_connection() as conn:
            c = conn.cursor()
            queues = c.execute('''
                SELECT 
                    q.id,
                    q.queue_number,
                    p.nama,
                    p.poli,
                    q.status,
                    q.created_at,
                    p.urgency
                FROM queues q
                JOIN patients p ON q.patient_id = p.id
                WHERE q.status != 'Selesai'
                ORDER BY 
                    CASE WHEN p.urgency = 'UGD' THEN 0 ELSE 1 END,
                    q.created_at
            ''').fetchall()
            return {q['id']: dict(q) for q in queues}
    
    def process_queue(self, queue_id: str):
        if messagebox.askyesno("Konfirmasi", "Proses antrian ini?"):
            with self.db._get_connection() as conn:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    c = conn.cursor()
                    c.execute('''
                        UPDATE queues 
                        SET status = 'Diproses', 
                            completed_at = ?
                        WHERE id = ? 
                        AND status = 'Menunggu'
                    ''', (datetime.now(), queue_id))
                    
                    if c.rowcount == 0:
                        messagebox.showwarning("Peringatan", "Antrian sudah diproses")
                        return
                    
                    logging.info(f"Queue {queue_id} diproses oleh {self.current_session.username}")
                    conn.commit()
                    self.refresh_queues()
                    
                except sqlite3.Error as e:
                    conn.rollback()
                    logging.error(f"Gagal memproses antrian: {e}")
                    messagebox.showerror("Error", "Gagal memproses antrian")
    
    def process_next_queue(self):
        with self.db._get_connection() as conn:
            c = conn.cursor()
            next_queue = c.execute('''
                SELECT q.id 
                FROM queues q
                JOIN patients p ON q.patient_id = p.id
                WHERE q.status = 'Menunggu'
                ORDER BY 
                    CASE WHEN p.urgency = 'UGD' THEN 0 ELSE 1 END,
                    q.created_at
                LIMIT 1
            ''').fetchone()
            
            if next_queue:
                self.process_queue(next_queue[0])
            else:
                messagebox.showinfo("Info", "Tidak ada antrian yang menunggu")

if __name__ == "__main__":
    app = HospitalQueueSystem()
    app.mainloop()