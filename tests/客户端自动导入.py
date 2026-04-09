import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import requests
import json
import os
import re
import secrets
import string
import shutil
import ctypes
from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys
import pyautogui
import pyperclip
import getpass
from datetime import datetime
import threading
import time

# 配置信息
BASE_URL = "http://127.0.0.1:5000"
CONFIG_FILE = "client_config.json"
USER_HOME = os.path.expanduser("~")
DOWNLOAD_ROOT = os.path.join(USER_HOME, "FileHubDownloads")
APPDATA_ROOT = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or USER_HOME
BACKUP_ROOT = os.path.join(APPDATA_ROOT, "FHCache", "rstore")

LOTTERY_MAP = {
    "胜平负": {"name": "北单让球胜平负", "right": 2, "down": 0},
    "比分":   {"name": "北单比分",       "right": 3, "down": 0},
    "总进球": {"name": "北单总进球数",   "right": 1, "down": 1},
    "半全场": {"name": "北单半全场胜平负", "right": 2, "down": 1},
    "上下盘": {"name": "北单上下盘单双", "right": 3, "down": 1},
    "胜负":   {"name": "北单胜负过关",   "right": 1, "down": 2},
}

class ImportAutomation:
    def __init__(self):
        self.app = None
        self.main_window = None
        self.dialog_window = None

    def _target_window(self):
        return self.dialog_window or self.main_window

    def attach_import_dialog(self, timeout: float = 5.0) -> bool:
        try:
            start = time.time()
            while time.time() - start < timeout:
                dialog = Desktop(backend='uia').window(title_re="彩种选择.*")
                if dialog.exists():
                    self.dialog_window = dialog
                    return True
                time.sleep(0.2)
            return False
        except Exception:
            return False

    def start_app(self) -> bool:
        try:
            self.app = Application(backend='uia').connect(title_re=".*北京专用.*")
            self.main_window = self.app.window(title_re=".*北京专用.*")
            if self.main_window.exists():
                return True
            return False
        except Exception:
            return False

    def click_import_button(self) -> bool:
        try:
            btn = None
            try:
                btn = self.main_window.child_window(
                    class_name="ThunderRT6CommandButton",
                    title="导入"
                )
                if btn.exists():
                    pass
            except:
                pass
            if btn is None or not btn.exists():
                buttons = self.main_window.descendants(class_name="ThunderRT6CommandButton")
                if len(buttons) > 15:
                    btn = buttons[15]
                else:
                    return False
            if btn is None:
                return False
            btn.click()
            time.sleep(1)
            return True
        except Exception:
            return False

    def click_import_file_button(self) -> bool:
        try:
            if not self.attach_import_dialog():
                return False
            target = self._target_window()
            btn = None
            try:
                btn = target.child_window(
                    class_name="ThunderRT6CommandButton",
                    title="导入文件"
                )
                if btn.exists():
                    pass
            except:
                pass
            if btn is None or not btn.exists():
                buttons = target.descendants(class_name="ThunderRT6CommandButton")
                for b in buttons:
                    try:
                        text = b.window_text()
                        if "导入" in text and "文件" in text:
                            btn = b
                            break
                    except:
                        pass
            if btn is None:
                return False
            btn.click()
            time.sleep(1)
            return True
        except Exception:
            return False

    def select_file(self, file_path: str) -> bool:
        try:
            start = time.time()
            dialog = None
            while time.time() - start < 5:
                try:
                    dialog = Desktop(backend='uia').window(title="打开")
                    if dialog.exists():
                        break
                except:
                    pass
                time.sleep(0.2)
            if dialog is None or not dialog.exists():
                return False
            dir_path = os.path.dirname(file_path)
            file_name = os.path.basename(file_path)
            send_keys("^l")
            time.sleep(0.2)
            pyperclip.copy(dir_path)
            send_keys("^v")
            time.sleep(0.2)
            pyautogui.press('enter')
            time.sleep(0.8)
            edits = dialog.descendants(class_name="Edit")
            file_input = None
            if len(edits) > 18:
                file_input = edits[18]
            elif len(edits) > 0:
                file_input = edits[-2] if len(edits) > 1 else edits[0]
            if file_input is None:
                return False
            try:
                file_input.set_focus()
            except:
                pass
            time.sleep(0.2)
            pyperclip.copy(file_name)
            send_keys("^v")
            time.sleep(0.3)
            pyautogui.press('enter')
            time.sleep(0.8)
            self.dialog_window = None
            return True
        except Exception:
            return False

    def extract_lottery_type_from_filename(self, filename: str) -> str:
        base = os.path.splitext(filename)[0]
        parts = base.split('_')
        if parts:
            t = parts[0]
            for keyword in LOTTERY_MAP.keys():
                if keyword == t:
                    return keyword
        for keyword in LOTTERY_MAP.keys():
            if keyword in filename:
                return keyword
        return None

    def select_lottery_type(self, filename: str) -> bool:
        try:
            if not self.dialog_window:
                if not self.attach_import_dialog():
                    return False
            lottery_keyword = self.extract_lottery_type_from_filename(filename)
            if not lottery_keyword:
                return False
            lottery_info = LOTTERY_MAP[lottery_keyword]
            for _ in range(lottery_info["down"]):
                pyautogui.press('down')
                time.sleep(0.15)
            for _ in range(lottery_info["right"]):
                pyautogui.press('right')
                time.sleep(0.15)
            time.sleep(0.3)
            return True
        except Exception:
            return False

    def extract_multiple_from_filename(self, filename: str) -> str:
        match = re.search(r'(\d+)\s*倍', filename)
        if not match:
            match = re.search(r'(\d+)倍投', filename)
        if match:
            multiple = match.group(1).zfill(2)
            return multiple
        return "02"

    def input_multiple(self, multiple: str) -> bool:
        try:
            if not self.dialog_window:
                if not self.attach_import_dialog():
                    return False
            target = self._target_window()
            textboxes = target.descendants(class_name="ThunderRT6TextBox")
            if len(textboxes) == 0:
                return False
            if len(textboxes) > 1:
                textbox = textboxes[1]
            else:
                textbox = textboxes[0]
            try:
                textbox.set_focus()
            except:
                pass
            time.sleep(0.3)
            pyautogui.press('right')
            time.sleep(0.1)
            pyautogui.press('right')
            time.sleep(0.1)
            pyautogui.press('backspace')
            time.sleep(0.1)
            pyautogui.press('backspace')
            time.sleep(0.1)
            send_keys(multiple)
            time.sleep(0.3)
            return True
        except Exception:
            return False

    def click_confirm_button(self) -> bool:
        try:
            if not self.dialog_window:
                if not self.attach_import_dialog():
                    return False
            target = self._target_window()
            btn = None
            try:
                btn = target.child_window(
                    class_name="ThunderRT6CommandButton",
                    title="确定"
                )
                if btn.exists():
                    pass
            except:
                pass
            if btn is None or not btn.exists():
                buttons = target.descendants(class_name="ThunderRT6CommandButton")
                for b in buttons:
                    try:
                        text = b.window_text()
                        if text == "确定":
                            btn = b
                            break
                    except:
                        pass
            if btn is None:
                return False
            btn.click()
            time.sleep(1)
            self.dialog_window = None
            return True
        except Exception:
            return False

    def run_import(self, file_path: str) -> bool:
        filename = os.path.basename(file_path)
        if not self.click_import_button():
            return False
        if not self.select_lottery_type(filename):
            return False
        if not self.click_import_file_button():
            return False
        if not self.select_file(file_path):
            return False
        multiple = self.extract_multiple_from_filename(filename)
        if not self.input_multiple(multiple):
            return False
        if not self.click_confirm_button():
            return False
        return True

class ModeBClient:
    def __init__(self, root):
        self.root = root
        self.root.title("FileHub B模式 客户端")
        self.root.geometry("600x600")

        self.session = requests.Session()
        self.username = ""
        self.device_id = ""
        self.is_logged_in = False
        self.is_downloading = False
        self.last_downloaded_path = ""
        self.backup_index = {}
        self.backup_dir = BACKUP_ROOT
        self.mode_b_options = [50, 100, 200, 300, 400, 500]  # 默认值，登录后会从服务器获取

        self.load_config()
        self.setup_login_ui()

        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        """关闭软件时触发退出登录"""
        if self.is_logged_in:
            # 弹窗确认（可选，根据用户习惯，这里直接尝试后台登出并关闭）
            # 如果想强制直接关，可以去掉提示
            try:
                # 同步请求，确保在窗口关闭前发出
                self.session.post(f"{BASE_URL}/auth/logout", timeout=2)
            except:
                pass
        self.root.destroy()

    def logout(self):
        if messagebox.askyesno("登出", "确定要登出并清除所有保存的信息吗？"):
            # 清除所有敏感信息
            self.config = {"username": "", "password": "", "remember": False, "auto_login": False, "device_id": ""}
            self.save_config("", "", False, False)

            # 清除服务器 session
            try:
                self.session.post(f"{BASE_URL}/auth/logout", timeout=2)
            except:
                pass

            self.is_logged_in = False
            self.setup_login_ui()

    def load_config(self):
        self.config = {"username": "", "password": "", "remember": False, "auto_login": False}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    self.config.update(json.load(f))
            except:
                pass

    def save_config(self, username="", password="", remember=False, auto_login=False):
        self.config["username"] = username
        self.config["password"] = password if remember else ""
        self.config["remember"] = remember
        self.config["auto_login"] = auto_login
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f)

    def setup_login_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        frame = tk.Frame(self.root, padx=20, pady=20)
        frame.pack(expand=True, fill="both")

        tk.Label(frame, text="FileHub B模式登录", font=("微软雅黑", 16, "bold")).pack(pady=10)

        tk.Label(frame, text="用户名:").pack(anchor="w")
        self.user_entry = tk.Entry(frame, width=30)
        self.user_entry.insert(0, self.config["username"])
        self.user_entry.pack(pady=5)

        tk.Label(frame, text="密码:").pack(anchor="w")
        self.pass_entry = tk.Entry(frame, show="*", width=30)
        if self.config["remember"]:
            self.pass_entry.insert(0, self.config["password"])
        self.pass_entry.pack(pady=5)

        self.remember_var = tk.BooleanVar(value=self.config["remember"])
        tk.Checkbutton(frame, text="记住密码", variable=self.remember_var).pack(anchor="w")

        self.auto_var = tk.BooleanVar(value=self.config["auto_login"])
        tk.Checkbutton(frame, text="自动登录", variable=self.auto_var).pack(anchor="w")

        self.login_btn = tk.Button(frame, text="登录", command=self.login, width=20, bg="#4CAF50", fg="white")
        self.login_btn.pack(pady=20)

        if self.config["auto_login"] and self.config["username"] and self.config["password"]:
            self.root.after(500, self.login)

    def login(self):
        username = self.user_entry.get().strip()
        password = self.pass_entry.get()
        
        if not username or not password:
            messagebox.showerror("错误", "请输入用户名和密码")
            return

        self.login_btn.config(state="disabled", text="登录中...")
        
        def do_login():
            try:
                # 尝试从配置加载 device_id 以便登录时同步清理旧 session
                device_id = self.config.get("device_id", "")
                
                resp = self.session.post(f"{BASE_URL}/auth/login", json={
                    "username": username,
                    "password": password,
                    "device_id": device_id
                }, timeout=10)
                
                data = resp.json()
                if data.get("success"):
                    self.username = username
                    self.save_config(username, password, self.remember_var.get(), self.auto_var.get())
                    self.root.after(0, self.on_login_success)
                else:
                    self.root.after(0, lambda: messagebox.showerror("登录失败", data.get("error", "未知错误")))
                    self.root.after(0, lambda: self.login_btn.config(state="normal", text="登录"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"网络连接失败: {e}"))
                self.root.after(0, lambda: self.login_btn.config(state="normal", text="登录"))

        threading.Thread(target=do_login, daemon=True).start()

    def on_login_success(self):
        self.is_logged_in = True

        # 获取服务器配置（包括 mode_b_options）
        self.fetch_server_config()

        # 如果配置中已有设备ID，直接使用
        if self.config.get("device_id"):
            self.device_id = self.config["device_id"]
            self.setup_main_ui()
            return

        # 弹窗输入设备ID
        device_id = simpledialog.askstring("设备登记", "请输入设备ID (例如: D01):", parent=self.root)
        if not device_id:
            messagebox.showwarning("提示", "必须输入设备ID才能继续")
            self.setup_login_ui()
            return

        self.device_id = device_id
        # 保存设备ID到配置
        self.config["device_id"] = device_id
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f)

        self.setup_main_ui()

    def fetch_server_config(self):
        """从服务器获取配置（包括 mode_b_options）"""
        try:
            resp = self.session.get(f"{BASE_URL}/api/user/daily-stats", timeout=5)
            data = resp.json()
            if data.get("success") and data.get("mode_b_options"):
                self.mode_b_options = data["mode_b_options"]
                print(f"[信息] 已从服务器获取下载张数选项: {self.mode_b_options}")
        except Exception as e:
            print(f"[警告] 获取服务器配置失败，使用默认值: {e}")

    def setup_main_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        self.root.title(f"FileHub B模式 - {self.username} ({self.device_id})")
        
        main_frame = tk.Frame(self.root, padx=10, pady=10)
        main_frame.pack(expand=True, fill="both")

        # 状态栏
        status_frame = tk.LabelFrame(main_frame, text="票池状态", padx=5, pady=5)
        status_frame.pack(fill="x", pady=5)
        
        self.pool_label = tk.Label(status_frame, text="正在获取票池状态...", fg="gray")
        self.pool_label.pack(anchor="w")

        # 下载区域
        download_frame = tk.LabelFrame(main_frame, text="下载操作", padx=5, pady=5)
        download_frame.pack(fill="x", pady=5)
        download_frame.columnconfigure(2, weight=1)

        tk.Label(download_frame, text="下载张数:").grid(row=0, column=0, sticky="w")
        # 使用从服务器获取的选项，如果第一个选项存在则作为默认值，否则使用100
        default_count = self.mode_b_options[0] if self.mode_b_options else 100
        self.count_var = tk.IntVar(value=default_count)
        self.count_combo = ttk.Combobox(download_frame, textvariable=self.count_var, values=self.mode_b_options, width=10)
        self.count_combo.grid(row=0, column=1, padx=5, pady=5)

        self.download_btn = tk.Button(download_frame, text="获取文件并下载", command=self.download_file, bg="#2196F3", fg="white")
        self.download_btn.grid(row=0, column=2, padx=5, pady=5, sticky="ew")
        self.import_btn = tk.Button(download_frame, text="导入当前文件", command=self.import_current_file, bg="#FF9800", fg="white", state="disabled")
        self.import_btn.grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        # 处理中列表
        list_frame = tk.LabelFrame(main_frame, text="处理中清单", padx=5, pady=5)
        list_frame.pack(expand=True, fill="both", pady=5)

        self.tree = ttk.Treeview(list_frame, columns=("filename", "count", "status"), show="headings")
        self.tree.heading("filename", text="文件名")
        self.tree.heading("count", text="张数")
        self.tree.heading("status", text="状态")
        self.tree.column("filename", width=250)
        self.tree.column("count", width=50)
        self.tree.column("status", width=80)
        self.tree.pack(side="left", expand=True, fill="both")

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        btn_frame = tk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=5)

        self.complete_btn = tk.Button(btn_frame, text="标记为已完成", command=self.mark_completed, bg="#4CAF50", fg="white", state="disabled")
        self.complete_btn.pack(side="right", padx=5)

        self.refresh_btn = tk.Button(btn_frame, text="刷新列表", command=self.load_processing)
        self.refresh_btn.pack(side="left", padx=5)

        tk.Button(btn_frame, text="切换账号/清除设备ID", command=self.logout, fg="red").pack(side="left", padx=20)

        # 数据存储
        self.processing_batches = []
        
        # 启动心跳和状态更新
        self.update_pool_status()
        self.load_processing()

    def update_pool_status(self):
        if not self.is_logged_in: return
        
        def run():
            try:
                # 发送心跳保持 session 在线，以便管理后台统计设备速度
                try:
                    resp_heartbeat = self.session.post(f"{BASE_URL}/auth/heartbeat", timeout=5)
                    if resp_heartbeat.status_code != 200:
                        print(f"[警告] 心跳失败: HTTP {resp_heartbeat.status_code}")
                except Exception as e:
                    print(f"[警告] 心跳请求异常: {e}")

                resp = self.session.get(f"{BASE_URL}/api/mode-b/pool-status", timeout=5)
                data = resp.json()
                if data.get("success"):
                    total = data.get("total_pending", 0)
                    self.root.after(0, lambda: self.pool_label.config(text=f"当前票池剩余: {total} 张", fg="black"))
            except:
                self.root.after(0, lambda: self.pool_label.config(text="票池状态获取失败", fg="red"))
            
            # 每10秒刷新一次
            if self.is_logged_in:
                self.root.after(10000, self.update_pool_status)

        threading.Thread(target=run, daemon=True).start()

    def load_processing(self):
        if not self.is_logged_in or not self.device_id: return

        def run():
            try:
                # 传入当前设备ID，只查询本设备的票
                # 使用 quote 确保 device_id 安全
                from urllib.parse import quote
                safe_device_id = quote(self.device_id)
                resp = self.session.get(f"{BASE_URL}/api/mode-b/processing?device_id={safe_device_id}", timeout=5)
                data = resp.json()
                if data.get("success"):
                    self.processing_batches = data.get("batches", [])
                    self.root.after(0, self.refresh_tree)
            except:
                pass

        threading.Thread(target=run, daemon=True).start()

    def refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        for batch in self.processing_batches:
            self.tree.insert("", "end", values=(batch["filename"], batch["count"], "处理中"))
        
        if self.processing_batches:
            self.complete_btn.config(state="normal")
            if not self.is_downloading:
                self.download_btn.config(state="disabled")
        else:
            self.complete_btn.config(state="disabled")
            if not self.is_downloading:
                self.download_btn.config(state="normal")

    def download_file(self):
        if self.processing_batches:
            messagebox.showwarning("提示", "当前有文件在处理中，不能下载第二个文件")
            return
        count = self.count_var.get()
        self.is_downloading = True
        self.download_btn.config(state="disabled", text="正在下载...")

        def run():
            try:
                resp = self.session.post(f"{BASE_URL}/api/mode-b/download", json={
                    "count": count,
                    "device_id": self.device_id,
                    "device_name": self.device_id
                }, timeout=15)
                
                data = resp.json()
                if data.get("success"):
                    # 保存文件到个人文件夹
                    file_info = data["files"][0]
                    filename = file_info["filename"]
                    content = file_info["content"]
                    
                    os.makedirs(DOWNLOAD_ROOT, exist_ok=True)
                    alphabet = string.ascii_lowercase + string.digits
                    while True:
                        folder_name = "".join(secrets.choice(alphabet) for _ in range(8))
                        folder_path = os.path.join(DOWNLOAD_ROOT, folder_name)
                        try:
                            os.makedirs(folder_path, exist_ok=False)
                            break
                        except FileExistsError:
                            continue

                    save_path = os.path.join(folder_path, filename)
                    with open(save_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    
                    self.root.after(0, lambda: messagebox.showinfo("成功", "下载完成"))
                    self.last_downloaded_path = save_path
                    self.root.after(0, lambda: self.import_btn.config(state="normal"))
                    self.load_processing()
                else:
                    self.root.after(0, lambda: messagebox.showerror("下载失败", data.get("error", "未知错误")))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"下载请求失败: {e}"))
            finally:
                self.is_downloading = False
                self.root.after(0, lambda: self.download_btn.config(state="normal", text="获取文件并下载"))

        threading.Thread(target=run, daemon=True).start()

    def _schedule_delete_file(self, file_path: str):
        if not file_path or not isinstance(file_path, str):
            return
        if not file_path.lower().endswith(".txt"):
            return
        def archive_later():
            try:
                os.makedirs(self.backup_dir, exist_ok=True)
                try:
                    ctypes.windll.kernel32.SetFileAttributesW(self.backup_dir, 0x2)
                except:
                    pass
                if os.path.exists(file_path):
                    base = os.path.basename(file_path)
                    target = os.path.join(self.backup_dir, base)
                    if os.path.exists(target):
                        name, ext = os.path.splitext(base)
                        i = 1
                        while True:
                            candidate = os.path.join(self.backup_dir, f"{name}.bak{i}{ext}")
                            if not os.path.exists(candidate):
                                target = candidate
                                break
                            i += 1
                    shutil.move(file_path, target)
                    self.backup_index[file_path] = target
            except:
                pass
        self.root.after(1000, archive_later)

    def import_current_file(self):
        if not self.last_downloaded_path:
            messagebox.showwarning("提示", "请先下载文件")
            return
        if not os.path.exists(self.last_downloaded_path):
            backup_path = self.backup_index.get(self.last_downloaded_path) or os.path.join(self.backup_dir, os.path.basename(self.last_downloaded_path))
            try:
                if os.path.exists(backup_path):
                    os.makedirs(os.path.dirname(self.last_downloaded_path), exist_ok=True)
                    shutil.copy2(backup_path, self.last_downloaded_path)
                else:
                    messagebox.showwarning("提示", "找不到备份文件，无法再次导入")
                    return
            except Exception as e:
                messagebox.showerror("错误", f"恢复备份失败: {e}")
                return
        self.import_btn.config(state="disabled", text="正在导入...")
        def run():
            try:
                automation = ImportAutomation()
                if not automation.start_app():
                    self.root.after(0, lambda: messagebox.showerror("错误", "未找到目标窗口"))
                else:
                    success = automation.run_import(self.last_downloaded_path)
                    if success:
                        self._schedule_delete_file(self.last_downloaded_path)
                        self.root.after(0, lambda: messagebox.showinfo("成功", "导入完成"))
                    else:
                        self.root.after(0, lambda: messagebox.showerror("错误", "导入失败"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"执行导入失败: {e}"))
            finally:
                self.root.after(0, lambda: self.import_btn.config(state="normal", text="导入当前文件"))
        threading.Thread(target=run, daemon=True).start()

    def mark_completed(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先在列表中选择一个处理中的批次")
            return
        
        # 获取选中行的索引
        item = selected[0]
        index = self.tree.index(item)
        if index >= len(self.processing_batches):
            return
            
        batch = self.processing_batches[index]
        ticket_ids = batch["ticket_ids"]

        if not messagebox.askyesno("确认", f"确认将该批次标记为已完成？\n文件名: {batch['filename']}"):
            return

        self.complete_btn.config(state="disabled", text="正在提交...")

        def run():
            try:
                resp = self.session.post(f"{BASE_URL}/api/mode-b/confirm", json={
                    "ticket_ids": ticket_ids,
                    "device_id": self.device_id,
                }, timeout=10)
                
                data = resp.json()
                if data.get("success"):
                    self.root.after(0, lambda: messagebox.showinfo("成功", "已标记为完成"))
                    self.load_processing()
                else:
                    self.root.after(0, lambda: messagebox.showerror("错误", data.get("error", "操作失败")))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"请求失败: {e}"))
            finally:
                self.root.after(0, lambda: self.complete_btn.config(state="normal", text="标记为已完成"))

        threading.Thread(target=run, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = ModeBClient(root)
    root.mainloop()
