import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import requests
import json
import os
import getpass
from datetime import datetime
import threading
import time

# 配置信息
BASE_URL = "http://127.0.0.1:5000"
CONFIG_FILE = "client_config.json"
USER_HOME = os.path.expanduser("~")

class ModeBClient:
    def __init__(self, root):
        self.root = root
        self.root.title("FileHub B模式 客户端")
        self.root.geometry("450x600")
        
        self.session = requests.Session()
        self.username = ""
        self.device_id = ""
        self.is_logged_in = False
        
        self.load_config()
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
                # 登录不需要 device_id，登记设备在登录后
                resp = self.session.post(f"{BASE_URL}/auth/login", json={
                    "username": username,
                    "password": password
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
        # 弹窗输入设备ID
        device_id = simpledialog.askstring("设备登记", "请输入设备ID (例如: D01):", parent=self.root)
        if not device_id:
            messagebox.showwarning("提示", "必须输入设备ID才能继续")
            self.setup_login_ui()
            return
        
        self.device_id = device_id
        self.setup_main_ui()

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

        tk.Label(download_frame, text="下载张数:").grid(row=0, column=0, sticky="w")
        self.count_var = tk.IntVar(value=100)
        count_options = [50, 100, 200, 300, 400, 500]
        self.count_combo = ttk.Combobox(download_frame, textvariable=self.count_var, values=count_options, width=10)
        self.count_combo.grid(row=0, column=1, padx=5, pady=5)

        self.download_btn = tk.Button(download_frame, text="获取文件并下载", command=self.download_file, bg="#2196F3", fg="white")
        self.download_btn.grid(row=0, column=2, padx=5, pady=5)

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

        # 数据存储
        self.processing_batches = []
        
        # 启动心跳和状态更新
        self.update_pool_status()
        self.load_processing()

    def update_pool_status(self):
        if not self.is_logged_in: return
        
        def run():
            try:
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
        if not self.is_logged_in: return

        def run():
            try:
                resp = self.session.get(f"{BASE_URL}/api/mode-b/processing", timeout=5)
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
        else:
            self.complete_btn.config(state="disabled")

    def download_file(self):
        count = self.count_var.get()
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
                    
                    save_path = os.path.join(USER_HOME, filename)
                    with open(save_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    
                    self.root.after(0, lambda: messagebox.showinfo("成功", f"文件已保存至:\n{save_path}"))
                    self.load_processing()
                else:
                    self.root.after(0, lambda: messagebox.showerror("下载失败", data.get("error", "未知错误")))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"下载请求失败: {e}"))
            finally:
                self.root.after(0, lambda: self.download_btn.config(state="normal", text="获取文件并下载"))

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
                    "ticket_ids": ticket_ids
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
