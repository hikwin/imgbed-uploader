import sys
import os
import warnings
warnings.filterwarnings("ignore")
import time
import json
import mimetypes
import threading
import traceback
import sqlite3
import hashlib
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

try:
    import windnd
except ImportError:
    windnd = None

# ----------------- STREAM REDIRECTION FOR EXE SAFETY -----------------
class SafeStream:
    def __init__(self, original):
        self.original = original
    def write(self, data):
        if self.original:
            try:
                self.original.write(data)
            except Exception:
                pass
    def flush(self):
        if self.original and hasattr(self.original, 'flush'):
            try:
                self.original.flush()
            except Exception:
                pass

sys.stdout = SafeStream(sys.stdout)
sys.stderr = SafeStream(sys.stderr)

# ----------------- PATH & CONFIG RESOLUTION -----------------
if getattr(sys, 'frozen', False):
    EXE_DIR = os.path.dirname(sys.executable)
else:
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(EXE_DIR, "uploader_config.json")
LOG_PATH = os.path.join(EXE_DIR, "uploader.log")
DB_PATH = os.path.join(EXE_DIR, "uploader.db")
BACKUP_DIR = os.path.join(EXE_DIR, "images_backup")

DEFAULT_TELEGRAPH_DOMAINS = [
    "https://telegram-image.pages.dev",
    "https://telegra.ph",
    "https://telegraph.dog",
    "https://pic.tele.pg"
]

def load_config():
    """Load configuration from local JSON file."""
    config = {
        "default_provider": "x0.at",
        "telegraph_domain": "https://telegram-image.pages.dev",
        "imgbb_api_key": ""
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                config.update(loaded)
        except Exception:
            pass
    return config

def save_config(config):
    """Save configuration to local JSON file."""
    if "history" in config:
        config.pop("history", None)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

def write_log(message):
    """Write diagnostic messages to a persistent log file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {message}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(formatted)
    except Exception:
        pass

# ----------------- DATABASE & HELPER MODULES -----------------
class DbManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    size TEXT NOT NULL,
                    url TEXT NOT NULL,
                    md5 TEXT NOT NULL
                )
            ''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_md5_provider ON uploads (md5, provider)')
            conn.commit()
            conn.close()
        except Exception as e:
            write_log(f"数据库初始化失败: {str(e)}")

    def add_record(self, filename, filepath, provider, size, url, md5, custom_time=None):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            record_time = custom_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute('''
                INSERT INTO uploads (time, filename, filepath, provider, size, url, md5)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (record_time, filename, filepath, provider, size, url, md5))
            conn.commit()
            conn.close()
        except Exception as e:
            write_log(f"数据库写入记录失败: {str(e)}")

    def get_url_by_md5(self, md5, provider):
        if not md5:
            return None
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT url FROM uploads WHERE md5 = ? AND provider = ? ORDER BY id DESC LIMIT 1
            ''', (md5, provider))
            row = c.fetchone()
            conn.close()
            return row[0] if row else None
        except Exception as e:
            write_log(f"数据库查询 MD5 失败: {str(e)}")
            return None

    def get_history(self, limit=100, offset=0):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT id, time, provider, filename, size, url, filepath, md5
                FROM uploads ORDER BY id DESC LIMIT ? OFFSET ?
            ''', (limit, offset))
            rows = c.fetchall()
            conn.close()
            history = []
            for r in rows:
                history.append({
                    "id": r[0],
                    "time": r[1],
                    "provider": r[2],
                    "filename": r[3],
                    "size": r[4],
                    "url": r[5],
                    "filepath": r[6],
                    "md5": r[7]
                })
            return history
        except Exception as e:
            write_log(f"数据库读取历史失败: {str(e)}")
            return []

    def delete_record(self, record_id):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('DELETE FROM uploads WHERE id = ?', (record_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            write_log(f"数据库删除记录失败: {str(e)}")

    def clear_all(self):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('DELETE FROM uploads')
            conn.commit()
            conn.close()
        except Exception as e:
            write_log(f"数据库清空失败: {str(e)}")

def calculate_md5(file_path):
    if not os.path.isfile(file_path):
        return ""
    try:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        write_log(f"MD5 计算失败 ({os.path.basename(file_path)}): {str(e)}")
        return ""

def backup_image_file(file_path, provider):
    """Backup uploaded file into local images_backup/<provider>/ directory."""
    if not os.path.isfile(file_path):
        return None
    try:
        provider_backup_dir = os.path.join(BACKUP_DIR, provider)
        os.makedirs(provider_backup_dir, exist_ok=True)
        
        filename = os.path.basename(file_path)
        dest_path = os.path.join(provider_backup_dir, filename)
        
        # Avoid overwriting different files with the same name
        if os.path.exists(dest_path):
            src_md5 = calculate_md5(file_path)
            dest_md5 = calculate_md5(dest_path)
            if src_md5 == dest_md5:
                return dest_path # Already backed up, same content
            else:
                # Different content, generate unique filename
                base, ext = os.path.splitext(filename)
                counter = 1
                while True:
                    new_filename = f"{base}_{counter}{ext}"
                    dest_path = os.path.join(provider_backup_dir, new_filename)
                    if not os.path.exists(dest_path):
                        break
                    counter += 1
                    
        shutil.copy2(file_path, dest_path)
        write_log(f"本地备份成功: {file_path} -> {dest_path}")
        return dest_path
    except Exception as e:
        write_log(f"本地备份失败 ({os.path.basename(file_path)}): {str(e)}")
        return None

def migrate_json_history_to_db(config, db_mgr):
    if "history" in config and isinstance(config["history"], list) and len(config["history"]) > 0:
        write_log(f"开始迁移 JSON 历史记录到 SQLite, 共 {len(config['history'])} 条...")
        # Process in reverse to maintain chronological order in SQLite
        for item in reversed(config["history"]):
            filepath = item.get("filepath", "")
            filename = item.get("filename", "")
            provider = item.get("provider", "")
            size = item.get("size", "")
            url = item.get("url", "")
            time_str = item.get("time", "")
            
            md5 = ""
            if filepath and os.path.isfile(filepath):
                md5 = calculate_md5(filepath)
                
            db_mgr.add_record(
                filename=filename,
                filepath=filepath,
                provider=provider,
                size=size,
                url=url,
                md5=md5,
                custom_time=time_str
            )
        # Clear JSON history
        config["history"] = []
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            write_log("JSON 历史记录迁移完成，已清空原 JSON 中的 history 字段。")
        except Exception as e:
            write_log(f"保存迁移后的配置文件失败: {str(e)}")

def get_url_migration_map(db_path, src, dst):
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        # Query mappings based on matching MD5
        c.execute('''
            SELECT DISTINCT u1.url, u2.url
            FROM uploads u1
            JOIN uploads u2 ON u1.md5 = u2.md5
            WHERE u1.provider = ? AND u2.provider = ? AND u1.md5 != ''
        ''', (src, dst))
        rows = c.fetchall()
        
        mapping = {}
        for old_url, new_url in rows:
            if old_url and new_url and old_url != new_url:
                mapping[old_url] = new_url
                
        # Fallback: matching filename if MD5 was empty
        c.execute('''
            SELECT DISTINCT u1.url, u2.url
            FROM uploads u1
            JOIN uploads u2 ON u1.filename = u2.filename
            WHERE u1.provider = ? AND u2.provider = ? AND u1.md5 = '' AND u2.md5 = ''
        ''', (src, dst))
        rows_fn = c.fetchall()
        for old_url, new_url in rows_fn:
            if old_url and new_url and old_url != new_url and old_url not in mapping:
                mapping[old_url] = new_url
                
        conn.close()
        return mapping
    except Exception as e:
        write_log(f"构建 URL 映射失败: {str(e)}")
        return {}

# ----------------- UPLOAD IMPLEMENTATION -----------------
def perform_upload(file_path, provider, config):
    """
    Perform HTTPS multipart upload for a single file.
    Raises Exception if upload fails or violates size constraints.
    """
    import requests
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)
    mime_type, _ = mimetypes.guess_type(file_path)
    mime_type = mime_type or "image/png"

    if provider == "telegraph":
        if file_size > 5 * 1024 * 1024:
            raise Exception("Telegraph 图床单张图片大小限制为 5MB")
        
        domain = config.get("telegraph_domain", "https://telegra.ph").rstrip('/')
        url = "https://telegra.ph/upload"
        
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f, mime_type)}
            response = requests.post(url, files=files, timeout=30)
            
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and len(data) > 0 and "src" in data[0]:
            return f"{domain}{data[0]['src']}"
        raise Exception(f"Telegraph 返回格式错误: {data}")

    elif provider == "catbox":
        if file_size > 200 * 1024 * 1024:
            raise Exception("Catbox 图床单文件大小限制为 200MB")
            
        url = "https://catbox.moe/user/api.php"
        with open(file_path, "rb") as f:
            files = {"fileToUpload": (file_name, f)}
            data = {"reqtype": "fileupload"}
            response = requests.post(url, files=files, data=data, timeout=60)
            
        response.raise_for_status()
        res_text = response.text.strip()
        if res_text.startswith("http://") or res_text.startswith("https://"):
            return res_text
        raise Exception(f"Catbox 上传失败: {res_text}")

    elif provider == "x0.at":
        if file_size > 19 * 1024 * 1024:
            raise Exception("x0.at 单文件大小限制为 19MB")
            
        url = "https://x0.at/"
        with open(file_path, "rb") as f:
            files = {"file": f}
            response = requests.post(url, files=files, timeout=45)
            
        response.raise_for_status()
        res_text = response.text.strip()
        if res_text.startswith("http://") or res_text.startswith("https://"):
            return res_text
        raise Exception(f"x0.at 上传失败: {res_text}")

    elif provider == "imgbb":
        api_key = config.get("imgbb_api_key", "").strip()
        if not api_key:
            raise Exception("ImgBB 图床未配置 API Key，请先在设置中填写")
            
        url = "https://api.imgbb.com/1/upload"
        with open(file_path, "rb") as f:
            files = {"image": f}
            data = {"key": api_key}
            response = requests.post(url, files=files, data=data, timeout=45)
            
        response.raise_for_status()
        res_json = response.json()
        if res_json.get("success") and "data" in res_json and "url" in res_json["data"]:
            return res_json["data"]["url"]
        error_msg = res_json.get("error", {}).get("message", "未知错误")
        raise Exception(f"ImgBB 上传失败: {error_msg}")
    elif provider == "sm.ms":
        token = config.get("smms_token", "").strip()
        if not token:
            raise Exception("SM.MS 图床未配置 Secret Token，请先在设置中填写")
            
        url = "https://smms.app/api/v2/upload"
        headers = {"Authorization": token}
        with open(file_path, "rb") as f:
            files = {"smfile": (file_name, f)}
            response = requests.post(url, headers=headers, files=files, timeout=45)
            
        response.raise_for_status()
        res_json = response.json()
        if res_json.get("success"):
            return res_json["data"]["url"]
        elif res_json.get("code") == "image_repeated":
            return res_json.get("images")
            
        error_msg = res_json.get("message", "未知错误")
        raise Exception(f"SM.MS 上传失败: {error_msg}")

    elif provider == "imgse":
        api_key = config.get("imgse_api_key", "").strip()
        if not api_key:
            raise Exception("Imgse 图床未配置 API Key，请先在设置中填写")
            
        url = "https://imgse.com/api/1/upload"
        params = {"key": api_key}
        with open(file_path, "rb") as f:
            files = {"source": (file_name, f)}
            response = requests.post(url, params=params, files=files, timeout=45)
            
        response.raise_for_status()
        res_json = response.json()
        if isinstance(res_json, dict) and "image" in res_json and "url" in res_json["image"]:
            return res_json["image"]["url"]
            
        error_msg = "上传失败"
        if isinstance(res_json, dict) and "error" in res_json and "message" in res_json["error"]:
            error_msg = res_json["error"]["message"]
        raise Exception(f"Imgse 上传失败: {error_msg}")

    else:
        raise ValueError(f"未知的图床提供商: {provider}")

# ----------------- CLI MODE -----------------
def run_cli(file_paths):
    """
    Run in Command Line Interface mode.
    Outputs results on stdout, logging errors to stderr and uploader.log.
    """
    config = load_config()
    db_mgr = DbManager(DB_PATH)
    migrate_json_history_to_db(config, db_mgr)
    
    provider = config.get("default_provider", "x0.at")
    
    write_log(f"CLI 启动: 上传文件列表 {file_paths}，使用图床: {provider}")
    
    results = []
    has_errors = False
    
    for path in file_paths:
        try:
            md5_val = calculate_md5(path)
            cached_url = db_mgr.get_url_by_md5(md5_val, provider)
            
            if cached_url:
                url = cached_url
                write_log(f"CLI [秒传成功]: {path} -> {url}")
            else:
                url = perform_upload(path, provider, config)
                write_log(f"成功上传: {path} -> {url}")
                
            db_mgr.add_record(
                filename=os.path.basename(path),
                filepath=os.path.abspath(path),
                provider=provider,
                size=f"{os.path.getsize(path) / 1024:.1f} KB",
                url=url,
                md5=md5_val
            )
            
            backup_image_file(path, provider)
            results.append(url)
        except Exception as e:
            has_errors = True
            err_msg = f"上传失败 ({os.path.basename(path)}): {str(e)}"
            sys.stderr.write(err_msg + "\n")
            write_log(err_msg)
            results.append(f"Upload-Failed-For-{os.path.basename(path)}")
            
    # Print outputs to stdout as Typora expects
    print("\nUpload Success:")
    for url in results:
        print(url)
        
    if has_errors:
        sys.exit(1)
    else:
        sys.exit(0)

# ----------------- MULTILINGUAL TRANSLATION SYSTEM -----------------
LANG_DICTS = {
    "zh": {
        "title": "i图床 - 匿名图床上传工具",
        "subtitle": "Typora 适配版 • 免注册免登录",
        "paste_btn": "📋 粘贴并上传 (剪贴板图片)",
        "drag_text": "点击选择或拖拽图片到此处上传",
        "drag_sub": "支持 PNG, JPG, JPEG, GIF, WEBP",
        "settings_title": "⚙️ 图床参数设置",
        "default_provider": "默认上传图床:",
        "migration_btn": "🔄 图床迁移与链接替换",
        "save_btn": "💾 保存配置",
        "test_btn": "⚡ 测试连接",
        "success_link": "🔗 上传成功链接:",
        "copy_btn": "复制链接",
        "history_title": "📜 上传历史记录",
        "clear_btn": "清空记录",
        "console_title": "🖥️ 运行状态日志",
        "col_time": "时间",
        "col_provider": "图床",
        "col_filename": "文件名",
        "col_size": "大小",
        "lbl_tg_proxy": "Telegraph 反代域名 (含协议):",
        "tg_custom_proxy": "自定义反代 / 推荐节点 ↓",
        "lbl_imgbb_key": "ImgBB API Key (密钥):",
        "lbl_smms_token": "SM.MS Secret Token (密钥):",
        "lbl_imgse_key": "Imgse API Key (密钥):",
        "lbl_no_config": "提示: 该图床不需要任何额外配置",
        
        # Log and Dialog Messages
        "log_ready": "系统就绪。",
        "log_cfg_path": "配置文件路径: {}",
        "log_uploading_wait": "正在上传中，请稍候...",
        "log_unsupported_format": "文件格式不受支持 (仅限图片): {}",
        "log_ignore_non_file": "忽略非文件路径: {}",
        "log_drag_detected": "拖拽检测到 {} 个图片文件，已开始上传。",
        "dialog_select_title": "选择上传的图片",
        "filetype_images": "图片文件",
        "filetype_all": "所有文件",
        "log_checking_clipboard": "检索剪贴板 ...",
        "msg_no_clipboard_img": "未在剪贴板中检测到图片文件或截图数据！",
        "msg_clipboard_empty": "剪贴板为空",
        "log_clipboard_unsupported": "剪贴板中的文件不支持 (仅支持 png/jpg/jpeg/gif/webp 格式图片)。",
        "log_clipboard_screenshot": "从剪贴板截获屏幕截图，存为临时文件: {}",
        "log_clipboard_unknown": "未知的剪贴板数据格式。",
        "log_clipboard_error": "读取剪贴板异常: {}",
        "log_waiting_upload": "等待上传 [{}]: {} ...",
        "log_instant_success": "[秒传成功]: {} -> {}",
        "log_upload_success": "上传成功: {} -> {}",
        "log_backup_success": "本地备份成功: {} -> {}",
        "log_backup_failed": "本地备份失败 ({}): {}",
        "log_upload_error": "上传异常 [{}]: {}",
        "toast_upload_copy_success": "上传并复制成功",
        "dialog_upload_failed_title": "上传失败",
        "dialog_upload_failed_msg": "上传过程中出现错误:\n{}",
        "dialog_param_error_title": "参数错误",
        "dialog_tg_error_msg": "Telegraph 反代域名必须以 http:// 或 https:// 开头",
        "log_save_success": "配置保存成功。",
        "toast_save_success": "配置已保存",
        "log_start_test": "开始测试连接 {} ...",
        "log_test_failed_no_url": "测试失败: 未找到有效的目标 URL。",
        "log_test_success": "连接成功! 响应时长: {} ms, 状态码: {}",
        "log_test_failed": "连接失败: {}",
        "toast_copied": "已复制",
        "toast_copied_raw": "已复制原始 URL",
        "toast_copied_markdown": "已复制 Markdown",
        "toast_copied_html": "已复制 HTML",
        "log_copy_failed": "复制失败: {}",
        "log_browser_open": "在浏览器中打开: {}",
        "log_browser_error": "打开浏览器失败: {}",
        "log_delete_history": "从历史记录删除: {}",
        "dialog_confirm_title": "确认",
        "dialog_clear_confirm_msg": "确定要清空所有上传历史记录吗？这不会影响已上传的图片文件。",
        "log_history_cleared": "历史记录已清空。",
        "menu_open_browser": "🔗 浏览器打开链接",
        "menu_delete_history": "❌ 从历史记录中删除",
        "menu_copy_raw": "📋 复制 原始链接 (Raw URL)",
        "menu_copy_markdown": "📝 复制 Markdown 格式图片",
        "menu_copy_html": "🌐 复制 HTML Image 标签",
        "menu_copy_selected": "复制选中 (Copy Selected)",
        "menu_copy_all": "复制全部 (Copy All)",
        "menu_select_all": "全选 (Select All)",
        "log_loaded_more": "已加载更多历史记录 (共展示 {} 条)。",
        
        # Migration Dialog
        "migration_dialog_title": "图床迁移与链接替换工具",
        "migration_title": "🔄 图床批量迁移与链接自动替换",
        "migration_desc": "用途：当旧图床失效时，将本地备份图片重新上传至新图床，并一键替换本地文档中的旧链接。",
        "step1_title": " 步骤 1: 批量重传图片 ",
        "step1_src": "源图床:",
        "step1_dst": "目标新图床:",
        "step1_warn": "⚠️ 强提醒：仅在原图床网站确认倒闭或无法访问时才使用批量重传，否则可能产生数据不一致等风险。本工具仅为辅助，不承担由此产生的任何间接责任。",
        "step1_btn": "🚀 开始批量重传图片",
        "step2_title": " 步骤 2: 批量替换本地文档链接 ",
        "step2_dir": "本地文档目录:",
        "step2_btn_browse": "浏览...",
        "step2_btn_replace": "🔗 开始查找并替换链接",
        "migration_console_title": "📋 迁移替换控制台输出",
        "msg_migrate_risk_confirm": "【安全强提醒】\n请务必确认原图床提供商已经彻底倒闭或无法访问！如果原图床正常，盲目批量迁移会导致链接替换混乱且无法撤销。\n\n本工具仅用于协助数据自救，本程序作者不承担由此操作产生的任何法律或间接损失责任。\n\n您确定要继续吗？",
        "dialog_select_dir_title": "选择文档所在的文件夹",
        "no_uploaded_image": "暂无上传图片",
        "mig_start": "开始迁移: 从 {} 到 {} ...",
        "mig_err_backup_dir": "错误: 未找到源图床的本地备份文件夹 '{}'，请确认是否有备份文件。",
        "mig_err_no_images": "错误: 备份文件夹 '{}' 中没有发现任何图片文件。",
        "mig_found_files": "共发现 {} 个图片文件需要迁移。",
        "mig_no_old_record": "[{}/{}] 提示: 在数据库中未找到 '{}' 属于 {} 的旧上传记录，仍会迁移但将无法自动替换旧链接。",
        "mig_exist_skip": "[{}/{}] {} -> 已在 {} 存在 (秒传): {}",
        "mig_uploading": "[{}/{}] 正在上传 {} 到 {} ...",
        "mig_success": "[{}/{}] 上传成功: {}",
        "mig_failed": "[{}/{}] 迁移失败 {}: {}",
        "mig_complete": "迁移完成! 成功: {} (其中秒传 {}), 失败: {}",
        "mig_err_select_dir": "请先选择一个有效的文档目录！",
        "mig_build_map": "构建 URL 映射表 ({} -> {}) ...",
        "mig_err_no_map": "错误: 未找到任何已迁移 of URL 映射关系！",
        "mig_check_confirm": "请确认：",
        "mig_check_step1": "1. 是否已经完成了 步骤1 的批量重传。",
        "mig_check_db": "2. 数据库中是否有相同图片同时上传过 {} 和 {}。",
        "mig_loaded_pairs": "成功加载 {} 个 URL 映射对:",
        "mig_start_scan": "开始扫描目录 '{}' ...",
        "mig_warn_decode": "警告: 无法读取文件 (编码未知): {}",
        "mig_modified_file": "修改文件: {}",
        "mig_backup_created": "  备份为: {}",
        "mig_replaced_count": "  替换链接数: {} 个",
        "mig_err_write": "错误: 写入文件失败 {}: {}",
        "mig_replace_complete": "替换处理完成! 共扫描 {} 个文件，成功修改并备份 {} 个文件。"
    },
    "en": {
        "title": "Anonymous Image Uploader",
        "subtitle": "Typora Adapter • No registration required",
        "paste_btn": "📋 Paste & Upload (Clipboard)",
        "drag_text": "Click to select or drag images here to upload",
        "drag_sub": "Supports PNG, JPG, JPEG, GIF, WEBP",
        "settings_title": "⚙️ Image Provider Settings",
        "default_provider": "Default Provider:",
        "migration_btn": "🔄 Migrate & Replace Links",
        "save_btn": "💾 Save Settings",
        "test_btn": "⚡ Test Connection",
        "success_link": "🔗 Upload Success Link:",
        "copy_btn": "Copy Link",
        "history_title": "📜 Upload History",
        "clear_btn": "Clear History",
        "console_title": "🖥️ Running Status Log",
        "col_time": "Time",
        "col_provider": "Provider",
        "col_filename": "Filename",
        "col_size": "Size",
        "lbl_tg_proxy": "Telegraph Proxy Domain (with protocol):",
        "tg_custom_proxy": "Custom Proxy / Recommended Nodes ↓",
        "lbl_imgbb_key": "ImgBB API Key (Secret Key):",
        "lbl_smms_token": "SM.MS Secret Token (Secret Key):",
        "lbl_imgse_key": "Imgse API Key (Secret Key):",
        "lbl_no_config": "Hint: No extra configuration needed for this provider",
        
        # Log and Dialog Messages
        "log_ready": "System ready.",
        "log_cfg_path": "Config file path: {}",
        "log_uploading_wait": "Uploading in progress, please wait...",
        "log_unsupported_format": "File format not supported (images only): {}",
        "log_ignore_non_file": "Ignore non-file path: {}",
        "log_drag_detected": "Drag detected {} image files, starting upload.",
        "dialog_select_title": "Select Image to Upload",
        "filetype_images": "Image Files",
        "filetype_all": "All Files",
        "log_checking_clipboard": "Checking clipboard...",
        "msg_no_clipboard_img": "No image files or screenshot data detected in clipboard!",
        "msg_clipboard_empty": "Clipboard is empty",
        "log_clipboard_unsupported": "File format in clipboard not supported (supports png/jpg/jpeg/gif/webp only).",
        "log_clipboard_screenshot": "Captured screenshot from clipboard, saved as temp: {}",
        "log_clipboard_unknown": "Unknown clipboard data format.",
        "log_clipboard_error": "Error reading clipboard: {}",
        "log_waiting_upload": "Waiting to upload [{}]: {} ...",
        "log_instant_success": "[Instant Success]: {} -> {}",
        "log_upload_success": "Uploaded successfully: {} -> {}",
        "log_backup_success": "Local backup success: {} -> {}",
        "log_backup_failed": "Local backup failed ({}): {}",
        "log_upload_error": "Upload exception [{}]: {}",
        "toast_upload_copy_success": "Uploaded and link copied",
        "dialog_upload_failed_title": "Upload Failed",
        "dialog_upload_failed_msg": "An error occurred during upload:\n{}",
        "dialog_param_error_title": "Parameter Error",
        "dialog_tg_error_msg": "Telegraph proxy domain must start with http:// or https://",
        "log_save_success": "Configuration saved successfully.",
        "toast_save_success": "Configuration saved",
        "log_start_test": "Starting connection test for {} ...",
        "log_test_failed_no_url": "Test failed: No valid target URL found.",
        "log_test_success": "Connection success! Latency: {} ms, Status code: {}",
        "log_test_failed": "Connection failed: {}",
        "toast_copied": "Copied",
        "toast_copied_raw": "Copied raw URL",
        "toast_copied_markdown": "Copied Markdown format",
        "toast_copied_html": "Copied HTML format",
        "log_copy_failed": "Copy failed: {}",
        "log_browser_open": "Open in browser: {}",
        "log_browser_error": "Failed to open browser: {}",
        "log_delete_history": "Deleted from history: {}",
        "dialog_confirm_title": "Confirm",
        "dialog_clear_confirm_msg": "Are you sure you want to clear all upload history? This will not affect uploaded image files.",
        "log_history_cleared": "History cleared.",
        "menu_open_browser": "🔗 Open Link in Browser",
        "menu_delete_history": "❌ Delete from History",
        "menu_copy_raw": "📋 Copy Raw Link (URL)",
        "menu_copy_markdown": "📝 Copy Markdown Format",
        "menu_copy_html": "🌐 Copy HTML Image Tag",
        "menu_copy_selected": "Copy Selected",
        "menu_copy_all": "Copy All",
        "menu_select_all": "Select All",
        "log_loaded_more": "Loaded more history (showing {} records total).",
        
        # Migration Dialog
        "migration_dialog_title": "Migration & Replacement Tool",
        "migration_title": "🔄 Provider Batch Migration & Link Auto-Replacement",
        "migration_desc": "Use: Re-upload backed up images to a new provider when the old one fails, and automatically replace old links in your documents.",
        "step1_title": " Step 1: Batch Re-upload Images ",
        "step1_src": "Source Provider:",
        "step1_dst": "Target Provider:",
        "step1_warn": "⚠️ WARNING: Use batch re-upload ONLY when the source provider is confirmed dead or unreachable. Otherwise, there is a risk of data inconsistency. This tool is provided as-is without any warranties or liability.",
        "step1_btn": "🚀 Start Batch Re-upload",
        "step2_title": " Step 2: Replace Links in Local Documents ",
        "step2_dir": "Local Doc Directory:",
        "step2_btn_browse": "Browse...",
        "step2_btn_replace": "🔗 Start Link Replacement",
        "migration_console_title": "📋 Migration Console Output",
        "msg_migrate_risk_confirm": "[CRITICAL WARNING]\nPlease make sure the source provider is dead or completely unreachable! If the original provider is running, migrating blindly will cause messed up URLs and cannot be undone.\n\nThis tool is provided for data self-rescue purposes only, and the author does not assume any legal or indirect liability for this operation.\n\nAre you sure you want to continue?",
        "dialog_select_dir_title": "Select Documents Folder",
        "no_uploaded_image": "No uploaded images yet",
        "mig_start": "Start migration: from {} to {} ...",
        "mig_err_backup_dir": "Error: Local backup folder '{}' for source provider not found.",
        "mig_err_no_images": "Error: No image files found in backup folder '{}'.",
        "mig_found_files": "Found {} image files to migrate.",
        "mig_no_old_record": "[{}/{}] Note: Old upload record not found for '{}' under {}, migration will proceed but link replacement is impossible.",
        "mig_exist_skip": "[{}/{}] {} -> already exists in {} (instant success): {}",
        "mig_uploading": "[{}/{}] Uploading {} to {} ...",
        "mig_success": "[{}/{}] Upload success: {}",
        "mig_failed": "[{}/{}] Migration failed {}: {}",
        "mig_complete": "Migration complete! Success: {} (instant {}), Failed: {}",
        "mig_err_select_dir": "Please select a valid document directory first!",
        "mig_build_map": "Building URL mapping table ({} -> {}) ...",
        "mig_err_no_map": "Error: No migrated URL mapping relationship found!",
        "mig_check_confirm": "Please confirm:",
        "mig_check_step1": "1. Has Step 1 batch re-upload completed?",
        "mig_check_db": "2. Do identical images exist in database for both {} and {}?",
        "mig_loaded_pairs": "Successfully loaded {} URL mapping pairs:",
        "mig_start_scan": "Starting to scan directory '{}' ...",
        "mig_warn_decode": "Warning: Cannot read file (unknown encoding): {}",
        "mig_modified_file": "Modified file: {}",
        "mig_backup_created": "  Backup created as: {}",
        "mig_replaced_count": "  Replaced link count: {}",
        "mig_err_write": "Error: Failed to write file {}: {}",
        "mig_replace_complete": "Replacement complete! Scanned {} files, successfully modified and backed up {} files."
    }
}

MAP_FORMAT_TO_ID = {
    "原始直链": "raw",
    "Raw URL": "raw",
    "Markdown 格式": "markdown",
    "Markdown Format": "markdown",
    "HTML Image 标签": "html",
    "HTML Image Tag": "html"
}

MAP_ID_TO_ZH = {
    "raw": "原始直链",
    "markdown": "Markdown 格式",
    "html": "HTML Image 标签"
}

def detect_default_language():
    """Detect default language based on config or system locale."""
    config = load_config()
    if "language" in config and config["language"] in ("zh", "en"):
        return config["language"]
        
    # Check Windows user default UI language LANGID using ctypes
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        # 0x0804: zh-CN (Mainland), 0x0404: zh-TW (Taiwan), 0x0c04: zh-HK (Hong Kong), 0x1404: zh-MO (Macau)
        # Exclude Singapore (0x1004) or other regions to comply with "港澳台跟中国大陆显示简体中文，其它地区默认显示英文"
        if lang_id in (0x0804, 0x0404, 0x0c04, 0x1404):
            return 'zh'
    except Exception:
        pass

    # Check locale/language
    try:
        import locale
        loc = locale.getdefaultlocale()[0] # e.g. 'zh_CN', 'zh_TW', 'zh_HK', 'zh_MO'
        if loc:
            loc = loc.lower()
            if loc.startswith('zh') and any(x in loc for x in ('cn', 'tw', 'hk', 'mo')):
                return 'zh'
    except Exception:
        pass
        
    return 'en'

# ----------------- GUI MODE -----------------
class UploaderApp:
    def __init__(self, root):
        self.root = root
        self.config = load_config()
        self.db_mgr = DbManager(DB_PATH)
        
        # Initialize default language
        default_lang = detect_default_language()
        self.lang_var = tk.StringVar(value="简体中文" if default_lang == "zh" else "English")
        
        # Modern Dark Color Palette
        self.colors = {
            "bg": "#1e1e2e",
            "card": "#252538",
            "border": "#313244",
            "text": "#cdd6f4",
            "text_muted": "#a6adc8",
            "accent": "#89b4fa",       # Blue accent
            "accent_hover": "#b4befe", # Lighter blue
            "success": "#a6e3a1",      # Green
            "warning": "#f9e2af",      # Yellow
            "danger": "#f38ba8",       # Red
            "input_bg": "#181825"
        }
        
        # Configure Root window
        self.root.title("i图床 - 匿名图床上传工具")
        self.root.geometry("820x650")
        self.root.resizable(True, True)
        self.root.configure(bg=self.colors["bg"])
        
        # Last upload cache
        self.last_uploaded_url = None
        self.last_uploaded_filename = None
            
        self.setup_styles()
        self.build_ui()
        self.update_ui_languages()
        
        # Defer database load, migration and history refresh to let Tkinter render the window first
        self.root.after(10, self.deferred_init)

    def trans(self, key, *args):
        lang = self.lang_var.get()
        lang_key = "zh" if "中文" in lang else "en"
        text = LANG_DICTS[lang_key].get(key, key)
        if args:
            try:
                return text.format(*args)
            except Exception:
                pass
        return text

    def on_language_change(self, event):
        self.update_ui_languages()

    def update_ui_languages(self):
        lang = self.lang_var.get()
        lang_key = "zh" if "中文" in lang else "en"
        
        # Save to config
        self.config["language"] = lang_key
        save_config(self.config)
        
        # Apply translations
        d = LANG_DICTS[lang_key]
        
        self.root.title(d["title"])
        self.title_lbl.config(text=d["title"])
        self.subtitle_lbl.config(text=d["subtitle"])
        self.btn_paste.config(text=d["paste_btn"])
        self.lbl_drag_text.config(text=d["drag_text"])
        self.lbl_drag_sub.config(text=d["drag_sub"])
        self.lbl_cfg_title.config(text=d["settings_title"])
        self.lbl_prov.config(text=d["default_provider"])
        self.btn_migration.config(text=d["migration_btn"])
        self.btn_save.config(text=d["save_btn"])
        self.btn_test.config(text=d["test_btn"])
        
        self.lbl_link.config(text=d["success_link"])
        self.btn_copy_link.config(text=d["copy_btn"])
        self.lbl_hist.config(text=d["history_title"])
        self.btn_clear.config(text=d["clear_btn"])
        self.lbl_cons.config(text=d["console_title"])
        
        # Treeview Headings
        self.tree.heading("time", text=d["col_time"])
        self.tree.heading("provider", text=d["col_provider"])
        self.tree.heading("filename", text=d["col_filename"])
        self.tree.heading("size", text=d["col_size"])
        
        # Format combobox values
        current_fmt = self.link_format_var.get()
        old_val_zh = ["原始直链", "Markdown 格式", "HTML Image 标签"]
        old_val_en = ["Raw URL", "Markdown Format", "HTML Image Tag"]
        
        new_values = old_val_zh if lang_key == "zh" else old_val_en
        self.link_format_combo.config(values=new_values)
        
        if current_fmt in old_val_zh and lang_key == "en":
            idx = old_val_zh.index(current_fmt)
            self.link_format_var.set(old_val_en[idx])
        elif current_fmt in old_val_en and lang_key == "zh":
            idx = old_val_en.index(current_fmt)
            self.link_format_var.set(old_val_zh[idx])
            
        self.update_context_fields()
        self.update_link_display()


    def deferred_init(self):
        migrate_json_history_to_db(self.config, self.db_mgr)
        
        history = self.db_mgr.get_history(limit=1)
        if history:
            self.last_uploaded_url = history[0].get("url")
            self.last_uploaded_filename = history[0].get("filename")
            
        self.refresh_history()
        
        if self.last_uploaded_url:
            self.update_link_display()
            
        self.log(self.trans("log_ready"))
        self.log(self.trans("log_cfg_path", CONFIG_PATH))

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        style.configure(".", background=self.colors["bg"], foreground=self.colors["text"])
        style.configure("Treeview", 
                        background=self.colors["card"], 
                        foreground=self.colors["text"],
                        fieldbackground=self.colors["card"], 
                        bordercolor=self.colors["border"],
                        rowheight=25)
        style.map("Treeview", background=[("selected", self.colors["accent"])], foreground=[("selected", "#11111b")])
        style.configure("Treeview.Heading", 
                        background=self.colors["border"], 
                        foreground=self.colors["text"],
                        bordercolor=self.colors["border"])
        style.map("Treeview.Heading",
                  background=[("active", self.colors["border"]), ("pressed", self.colors["card"])],
                  foreground=[("active", self.colors["accent"]), ("pressed", self.colors["text"])])

                        
        # Scrollbar styling
        style.configure("Vertical.TScrollbar", troughcolor=self.colors["bg"], background=self.colors["border"])

        # Combobox styling for dark theme readability
        style.configure("TCombobox", 
                        fieldbackground=self.colors["input_bg"], 
                        background=self.colors["border"],
                        foreground=self.colors["text"],
                        bordercolor=self.colors["border"],
                        arrowcolor=self.colors["text"])
        style.map("TCombobox", 
                  fieldbackground=[("readonly", self.colors["input_bg"])],
                  foreground=[("readonly", self.colors["text"])],
                  background=[("readonly", self.colors["border"])])
                  
        # Configure the dropdown listbox popup styling globally
        self.root.option_add("*TCombobox*Listbox.background", self.colors["card"])
        self.root.option_add("*TCombobox*Listbox.foreground", self.colors["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.colors["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#11111b")
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 9))

    def update_context_fields(self):
        """Show inputs depending on the selected provider."""
        provider = self.prov_var.get()
        
        # Clean current layout in context frame
        self.lbl_context.pack_forget()
        self.context_entry.pack_forget()
        self.tg_shortcut_combo.pack_forget()
        self.context_entry.config(show="")
        
        if provider == "telegraph":
            self.lbl_context.config(text=self.trans("lbl_tg_proxy"))
            self.lbl_context.pack(anchor=tk.W, pady=(0, 2))
            
            # Pack entry and domain selector
            self.tg_shortcut_combo.pack(fill=tk.X, pady=(0, 4))
            self.context_entry.pack(fill=tk.X, ipady=3)
            
            # Load stored domain
            saved_domain = self.config.get("telegraph_domain", "https://telegram-image.pages.dev")
            self.context_entry_var.set(saved_domain)
            
            # Set default shortcut if matched
            if saved_domain in DEFAULT_TELEGRAPH_DOMAINS:
                self.tg_shortcut_combo.set(saved_domain)
            else:
                self.tg_shortcut_combo.set(self.trans("tg_custom_proxy"))

        elif provider == "imgbb":
            self.lbl_context.config(text=self.trans("lbl_imgbb_key"))
            self.lbl_context.pack(anchor=tk.W, pady=(0, 2))
            self.context_entry.pack(fill=tk.X, ipady=3)
            
            # Mask API Key input for privacy
            self.context_entry.config(show="*")
            self.context_entry_var.set(self.config.get("imgbb_api_key", ""))

        elif provider == "sm.ms":
            self.lbl_context.config(text=self.trans("lbl_smms_token"))
            self.lbl_context.pack(anchor=tk.W, pady=(0, 2))
            self.context_entry.pack(fill=tk.X, ipady=3)
            self.context_entry.config(show="*")
            self.context_entry_var.set(self.config.get("smms_token", ""))

        elif provider == "imgse":
            self.lbl_context.config(text=self.trans("lbl_imgse_key"))
            self.lbl_context.pack(anchor=tk.W, pady=(0, 2))
            self.context_entry.pack(fill=tk.X, ipady=3)
            self.context_entry.config(show="*")
            self.context_entry_var.set(self.config.get("imgse_api_key", ""))
            
        else:
            # Catbox or 0x0.st don't require credentials
            self.lbl_context.config(text=self.trans("lbl_no_config"))
            self.lbl_context.pack(anchor=tk.W, pady=(5, 5))

    def on_provider_change(self, event):
        self.update_context_fields()

    def on_telegraph_shortcut_selected(self, event):
        val = self.tg_shortcut_combo.get()
        if val in DEFAULT_TELEGRAPH_DOMAINS:
            self.context_entry_var.set(val)

    # ---------------- RIGHT PANEL: HISTORY CARD ----------------
    def build_ui_right(self, parent):
        # We split the right side into: 1. Link Display Card, 2. History Table, 3. Log Console
        
        # Link card (Top of Right Panel)
        link_card = tk.Frame(parent, bg=self.colors["card"], bd=0,
                             highlightbackground=self.colors["border"], highlightthickness=1)
        link_card.pack(fill=tk.X, pady=(0, 10))
        
        link_inner = tk.Frame(link_card, bg=self.colors["card"], padx=12, pady=10)
        link_inner.pack(fill=tk.X)
        
        self.lbl_link = tk.Label(link_inner, text="🔗 上传成功链接:", font=("Segoe UI", 9, "bold"),
                            bg=self.colors["card"], fg=self.colors["accent"])
        self.lbl_link.grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        # Link formats combobox
        saved_fmt_id = self.config.get("link_format", "raw")
        initial_fmt = MAP_ID_TO_ZH.get(saved_fmt_id, "原始直链")
        self.link_format_var = tk.StringVar(value=initial_fmt)
        self.link_format_combo = ttk.Combobox(link_inner, textvariable=self.link_format_var,
                                              values=["原始直链", "Markdown 格式", "HTML Image 标签"],
                                              state="readonly", font=("Segoe UI", 9), width=18)
        self.link_format_combo.grid(row=0, column=1, sticky=tk.E, padx=5, pady=(0, 5))
        self.link_format_combo.bind("<<ComboboxSelected>>", self.on_link_format_change)
        
        # Target link display entry (ReadOnly)
        self.link_display_var = tk.StringVar(value="暂无上传图片")
        self.link_display_entry = tk.Entry(link_inner, textvariable=self.link_display_var,
                                           bg=self.colors["input_bg"], fg=self.colors["text"],
                                           readonlybackground=self.colors["input_bg"],
                                           insertbackground=self.colors["text"], bd=0,
                                           font=("Consolas", 10), state="readonly")
        self.link_display_entry.grid(row=1, column=0, columnspan=2, sticky=tk.EW, padx=(0, 85), ipady=3)
        self.setup_link_entry_menu(self.link_display_entry)
        
        # Copy button
        self.btn_copy_link = tk.Button(link_inner, text="复制链接",
                                       bg=self.colors["accent"], fg="#11111b",
                                       activebackground=self.colors["accent_hover"], activeforeground="#11111b",
                                       bd=0, relief="flat", padx=10, pady=3,
                                       font=("Segoe UI", 9, "bold"), cursor="hand2",
                                       command=self.copy_link_display)
        self.btn_copy_link.grid(row=1, column=1, sticky=tk.E, ipady=1)
        
        # Column weight configuration for grid
        link_inner.columnconfigure(0, weight=1)
        link_inner.columnconfigure(1, weight=0)

        # History table card
        history_card = tk.Frame(parent, bg=self.colors["card"], bd=0,
                                highlightbackground=self.colors["border"], highlightthickness=1)
        history_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        hist_inner = tk.Frame(history_card, bg=self.colors["card"], padx=12, pady=10)
        hist_inner.pack(fill=tk.BOTH, expand=True)
        
        hist_header = tk.Frame(hist_inner, bg=self.colors["card"])
        hist_header.pack(fill=tk.X, pady=(0, 5))
        
        self.lbl_hist = tk.Label(hist_header, text="📜 上传历史记录", 
                            font=("Segoe UI", 11, "bold"), 
                            bg=self.colors["card"], fg=self.colors["accent"])
        self.lbl_hist.pack(side=tk.LEFT)
        
        self.btn_clear = tk.Button(hist_header, text="清空记录", 
                              bg=self.colors["danger"], fg="#11111b",
                              activebackground=self.colors["danger"], activeforeground="#11111b",
                              bd=0, relief="flat", padx=8, pady=2, 
                              font=("Segoe UI", 8, "bold"), cursor="hand2",
                              command=self.clear_history)
        self.btn_clear.pack(side=tk.RIGHT)
        
        # History table
        columns = ("time", "provider", "filename", "size")
        self.tree = ttk.Treeview(hist_inner, columns=columns, show="headings", height=8)
        self.tree.heading("time", text="时间")
        self.tree.heading("provider", text="图床")
        self.tree.heading("filename", text="文件名")
        self.tree.heading("size", text="大小")
        
        self.tree.column("time", width=120, anchor=tk.CENTER)
        self.tree.column("provider", width=80, anchor=tk.CENTER)
        self.tree.column("filename", width=160, anchor=tk.W)
        self.tree.column("size", width=80, anchor=tk.CENTER)
        
        # Vertical scrollbar
        scroll = ttk.Scrollbar(hist_inner, orient=tk.VERTICAL, command=self.tree.yview)
        
        def on_scroll(first, last):
            scroll.set(first, last)
            try:
                if float(last) > 0.92 and getattr(self, 'has_more', False) and not getattr(self, 'is_loading_more', False):
                    self.load_more_history()
            except Exception:
                pass
                
        self.tree.configure(yscrollcommand=on_scroll)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind events for copying and right click menu
        self.tree.bind("<Double-1>", self.on_history_double_click)
        self.tree.bind("<Button-3>", self.show_history_context_menu)
        self.tree.bind("<<TreeviewSelect>>", self.on_history_select)
        
        # Console Log card
        console_card = tk.Frame(parent, bg=self.colors["card"], bd=0,
                                highlightbackground=self.colors["border"], highlightthickness=1, height=150)
        console_card.pack_propagate(False)
        console_card.pack(fill=tk.X, side=tk.BOTTOM)
        
        console_inner = tk.Frame(console_card, bg=self.colors["card"], padx=12, pady=10)
        console_inner.pack(fill=tk.BOTH, expand=True)
        
        self.lbl_cons = tk.Label(console_inner, text="🖥️ 运行状态日志", 
                            font=("Segoe UI", 9, "bold"), 
                            bg=self.colors["card"], fg=self.colors["text_muted"])
        self.lbl_cons.pack(anchor=tk.W, pady=(0, 2))
        
        self.console = tk.Text(console_inner, bg=self.colors["input_bg"], fg=self.colors["text"],
                               bd=0, font=("Consolas", 9), state="disabled", wrap=tk.WORD)
        self.console.pack(fill=tk.BOTH, expand=True)

    def build_ui(self):
        # Root layout definition
        main_frame = tk.Frame(self.root, bg=self.colors["bg"], padx=15, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # ---------------- HEADER ----------------
        header_frame = tk.Frame(main_frame, bg=self.colors["bg"])
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.title_lbl = tk.Label(header_frame, text="i图床 - 匿名图床上传工具", 
                                  font=("Segoe UI", 14, "bold"), 
                                  bg=self.colors["bg"], fg=self.colors["text"])
        self.title_lbl.pack(side=tk.LEFT)
        
        self.subtitle_lbl = tk.Label(header_frame, text="Typora 适配版 • 免注册免登录", 
                                     font=("Segoe UI", 9), 
                                     bg=self.colors["bg"], fg=self.colors["text_muted"])
        self.subtitle_lbl.pack(side=tk.LEFT, padx=10, pady=(5, 0))
        
        # Language Selector Combobox
        self.lang_combo = ttk.Combobox(header_frame, textvariable=self.lang_var,
                                       values=["简体中文", "English"],
                                       state="readonly", font=("Segoe UI", 9), width=10)
        self.lang_combo.pack(side=tk.RIGHT, pady=(5, 0))
        self.lang_combo.bind("<<ComboboxSelected>>", self.on_language_change)
        
        # Split layout
        split_frame = tk.Frame(main_frame, bg=self.colors["bg"])
        split_frame.pack(fill=tk.BOTH, expand=True)
        
        left_panel = tk.Frame(split_frame, bg=self.colors["bg"], width=320)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 10))
        left_panel.pack_propagate(False)
        
        right_panel = tk.Frame(split_frame, bg=self.colors["bg"])
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ---------------- LEFT PANEL: UPLOAD CARD ----------------
        upload_card = tk.Frame(left_panel, bg=self.colors["card"], bd=0,
                               highlightbackground=self.colors["border"], highlightthickness=1)
        upload_card.pack(fill=tk.X, pady=(0, 10))
        
        upload_inner = tk.Frame(upload_card, bg=self.colors["card"], padx=15, pady=15)
        upload_inner.pack(fill=tk.X)
        
        self.btn_paste = tk.Button(upload_inner, text="📋 粘贴并上传 (剪贴板图片)", 
                                   bg=self.colors["accent"], fg="#11111b",
                                   activebackground=self.colors["accent_hover"], activeforeground="#11111b",
                                   bd=0, relief="flat", padx=10, pady=8, 
                                   font=("Segoe UI", 10, "bold"), cursor="hand2",
                                   command=self.paste_and_upload)
        self.btn_paste.pack(fill=tk.X)
        self.btn_paste.bind("<Enter>", lambda e: e.widget.config(bg=self.colors["accent_hover"]))
        self.btn_paste.bind("<Leave>", lambda e: e.widget.config(bg=self.colors["accent"]))
        
        # 拖拽上传区域 (Drag & Drop Zone)
        self.drag_zone = tk.Frame(upload_inner, bg=self.colors["input_bg"], bd=0,
                                  highlightbackground=self.colors["border"], highlightthickness=1,
                                  cursor="hand2")
        self.drag_zone.pack(fill=tk.X, pady=(10, 0), ipady=12)
        
        self.lbl_drag_icon = tk.Label(self.drag_zone, text="📥", font=("Segoe UI", 20),
                                      bg=self.colors["input_bg"], fg=self.colors["accent"])
        self.lbl_drag_icon.pack(pady=(4, 0))
        
        self.lbl_drag_text = tk.Label(self.drag_zone, text="点击选择或拖拽图片到此处上传", font=("Segoe UI", 9, "bold"),
                                      bg=self.colors["input_bg"], fg=self.colors["text"])
        self.lbl_drag_text.pack()
        
        self.lbl_drag_sub = tk.Label(self.drag_zone, text="支持 PNG, JPG, JPEG, GIF, WEBP", font=("Segoe UI", 8),
                                     bg=self.colors["input_bg"], fg=self.colors["text_muted"])
        self.lbl_drag_sub.pack(pady=(0, 4))
        
        # 悬停与点击交互
        def on_drag_enter(e):
            self.drag_zone.config(highlightbackground=self.colors["accent"], bg=self.colors["card"])
            self.lbl_drag_icon.config(bg=self.colors["card"])
            self.lbl_drag_text.config(bg=self.colors["card"])
            self.lbl_drag_sub.config(bg=self.colors["card"])
            
        def on_drag_leave(e):
            self.drag_zone.config(highlightbackground=self.colors["border"], bg=self.colors["input_bg"])
            self.lbl_drag_icon.config(bg=self.colors["input_bg"])
            self.lbl_drag_text.config(bg=self.colors["input_bg"])
            self.lbl_drag_sub.config(bg=self.colors["input_bg"])
            
        self.drag_zone.bind("<Enter>", on_drag_enter)
        self.drag_zone.bind("<Leave>", on_drag_leave)
        
        # 绑定点击事件，点击即可选择图片上传
        for w in (self.drag_zone, self.lbl_drag_icon, self.lbl_drag_text, self.lbl_drag_sub):
            w.bind("<Button-1>", lambda e: self.select_and_upload())
            w.bind("<Enter>", on_drag_enter)
            w.bind("<Leave>", on_drag_leave)
            
        # 挂载 windnd 消息钩子
        if windnd:
            try:
                self.drag_zone.update_idletasks()
                windnd.hook_dropfiles(self.drag_zone, func=self.on_file_drop, force_unicode=True)
            except Exception as e:
                write_log(f"注册拖动上传失败: {str(e)}")

        # ---------------- LEFT PANEL: CONFIG CARD ----------------
        config_card = tk.Frame(left_panel, bg=self.colors["card"], bd=0,
                               highlightbackground=self.colors["border"], highlightthickness=1)
        config_card.pack(fill=tk.BOTH, expand=True)
        
        config_inner = tk.Frame(config_card, bg=self.colors["card"], padx=15, pady=15)
        config_inner.pack(fill=tk.BOTH, expand=True)
        
        self.lbl_cfg_title = tk.Label(config_inner, text="⚙️ 图床参数设置", 
                                      font=("Segoe UI", 11, "bold"), 
                                      bg=self.colors["card"], fg=self.colors["accent"])
        self.lbl_cfg_title.pack(anchor=tk.W, pady=(0, 10))
        
        self.lbl_prov = tk.Label(config_inner, text="默认上传图床:", font=("Segoe UI", 9), 
                                 bg=self.colors["card"], fg=self.colors["text_muted"])
        self.lbl_prov.pack(anchor=tk.W, pady=(5, 2))
        
        self.prov_var = tk.StringVar(value=self.config.get("default_provider", "x0.at"))
        self.prov_combo = ttk.Combobox(config_inner, textvariable=self.prov_var, 
                                       values=["x0.at", "telegraph", "catbox", "imgbb", "sm.ms", "imgse"],
                                       state="readonly", font=("Segoe UI", 9))
        self.prov_combo.pack(fill=tk.X, pady=(0, 10))
        self.prov_combo.bind("<<ComboboxSelected>>", self.on_provider_change)
        
        self.context_frame = tk.Frame(config_inner, bg=self.colors["card"])
        self.context_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.lbl_context = tk.Label(self.context_frame, text="", font=("Segoe UI", 9), 
                                    bg=self.colors["card"], fg=self.colors["text_muted"])
        self.lbl_context.pack(anchor=tk.W, pady=(0, 2))
        
        self.context_entry_var = tk.StringVar()
        self.context_entry = tk.Entry(self.context_frame, textvariable=self.context_entry_var,
                                      bg=self.colors["input_bg"], fg=self.colors["text"],
                                      insertbackground=self.colors["text"], bd=0, 
                                      highlightthickness=1, highlightbackground=self.colors["border"], 
                                      highlightcolor=self.colors["accent"], font=("Segoe UI", 9))
        self.context_entry.pack(fill=tk.X, ipady=3)
        
        self.tg_shortcut_combo = ttk.Combobox(self.context_frame, values=DEFAULT_TELEGRAPH_DOMAINS,
                                             state="readonly", font=("Segoe UI", 9))
        self.tg_shortcut_combo.bind("<<ComboboxSelected>>", self.on_telegraph_shortcut_selected)
        
        self.btn_migration = tk.Button(config_inner, text="🔄 图床迁移与链接替换", 
                                       bg=self.colors["border"], fg=self.colors["text"],
                                       activebackground=self.colors["accent"], activeforeground="#11111b",
                                       bd=0, relief="flat", padx=10, pady=6, 
                                       font=("Segoe UI", 9, "bold"), cursor="hand2",
                                       command=self.open_migration_dialog)
        self.btn_migration.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
        self.btn_migration.bind("<Enter>", lambda e: e.widget.config(bg=self.colors["accent"], fg="#11111b"))
        self.btn_migration.bind("<Leave>", lambda e: e.widget.config(bg=self.colors["border"], fg=self.colors["text"]))

        btn_action_frame = tk.Frame(config_inner, bg=self.colors["card"])
        btn_action_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
        
        self.btn_save = tk.Button(btn_action_frame, text="💾 保存配置", 
                                  bg=self.colors["border"], fg=self.colors["text"],
                                  bd=0, relief="flat", padx=10, pady=6, 
                                  font=("Segoe UI", 9, "bold"), cursor="hand2",
                                  command=self.save_settings)
        self.btn_save.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.btn_test = tk.Button(btn_action_frame, text="⚡ 测试连接", 
                                  bg=self.colors["border"], fg=self.colors["text"],
                                  bd=0, relief="flat", padx=10, pady=6, 
                                  font=("Segoe UI", 9), cursor="hand2",
                                  command=self.test_connection)
        self.btn_test.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        self.update_context_fields()

        # ---------------- RIGHT PANEL: HISTORY CARD ----------------
        self.build_ui_right(right_panel)

    def log(self, message):
        """Append a message to the GUI status console."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}\n"
        
        def append():
            try:
                if self.console and self.console.winfo_exists():
                    self.console.config(state="normal")
                    self.console.insert(tk.END, formatted)
                    self.console.see(tk.END)
                    self.console.config(state="disabled")
            except Exception:
                pass
        self.root.after(0, append)

    def on_link_format_change(self, event):
        self.update_link_display()
        fmt = self.link_format_var.get()
        fmt_id = MAP_FORMAT_TO_ID.get(fmt, "raw")
        self.config["link_format"] = fmt_id
        save_config(self.config)

    def on_history_select(self, event):
        item = self.get_selected_history_item()
        if item:
            self.last_uploaded_url = item.get("url", "")
            self.last_uploaded_filename = item.get("filename", "")
            self.update_link_display()

    def update_link_display(self):
        if not self.last_uploaded_url:
            self.link_display_entry.config(state="normal")
            self.link_display_var.set(self.trans("no_uploaded_image"))
            self.link_display_entry.config(state="readonly")
            return
            
        fmt = self.link_format_var.get()
        url = self.last_uploaded_url
        name = self.last_uploaded_filename or "image"
        
        formatted = url
        if fmt in ("Markdown 格式", "Markdown Format"):
            formatted = f"![{name}]({url})"
        elif fmt in ("HTML Image 标签", "HTML Image Tag"):
            formatted = f'<img src="{url}" alt="{name}" />'
            
        self.link_display_entry.config(state="normal")
        self.link_display_var.set(formatted)
        self.link_display_entry.config(state="readonly")

    def copy_link_display(self):
        val = self.link_display_var.get().strip()
        if val and val != self.trans("no_uploaded_image"):
            self.copy_to_clipboard(val, self.trans("toast_copied"))

    def setup_link_entry_menu(self, widget):
        widget.config(
            bg=self.colors["input_bg"],
            fg=self.colors["text"],
            readonlybackground=self.colors["input_bg"],
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["border"]
        )
        def on_focus(event):
            widget.select_range(0, tk.END)
            widget.icursor(tk.END)
        widget.bind("<FocusIn>", on_focus)
        
        def do_copy():
            try:
                val = widget.get().strip()
                if val and val != self.trans("no_uploaded_image"):
                    self.copy_to_clipboard(val, self.trans("toast_copied"))
            except Exception:
                pass
                
        def on_double_click(event):
            widget.select_range(0, tk.END)
            do_copy()
            return "break"
        widget.bind("<Double-Button-1>", on_double_click)

        def show_context_menu(event):
            menu = tk.Menu(widget, tearoff=0, bg=self.colors["card"], fg=self.colors["text"],
                           activebackground=self.colors["accent"], activeforeground="#11111b", bd=1, relief="solid")
            menu.add_command(label="复制选中 (Copy Selected)", command=lambda: widget.event_generate("<<Copy>>"))
            menu.add_command(label="复制全部 (Copy All)", command=do_copy)
            menu.add_command(label="全选 (Select All)", command=lambda: widget.select_range(0, tk.END))
            menu.post(event.x_root, event.y_root)
            return "break"
            
        widget.bind("<Button-3>", show_context_menu)

    def refresh_history(self):
        """Re-render the treeview rows from SQLite database uploads."""
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        self.history_items = []
        self.loaded_offset = 0
        self.has_more = True
        self.is_loading_more = False
        
        history = self.db_mgr.get_history(limit=100, offset=0)
        self.history_items = history
        if len(history) < 100:
            self.has_more = False
            
        for idx, item in enumerate(history):
            self.tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    item.get("time", ""),
                    item.get("provider", ""),
                    item.get("filename", ""),
                    item.get("size", "")
                )
            )

    def load_more_history(self):
        """Load the next batch of history records from SQLite database."""
        if getattr(self, "is_loading_more", False) or not getattr(self, "has_more", False):
            return
            
        self.is_loading_more = True
        self.loaded_offset += 100
        
        def worker():
            try:
                history = self.db_mgr.get_history(limit=100, offset=self.loaded_offset)
                if not history or len(history) < 100:
                    self.has_more = False
                
                def render():
                    start_idx = len(self.history_items)
                    self.history_items.extend(history)
                    for idx, item in enumerate(history):
                        self.tree.insert(
                            "",
                            tk.END,
                            iid=str(start_idx + idx),
                            values=(
                                item.get("time", ""),
                                item.get("provider", ""),
                                item.get("filename", ""),
                                item.get("size", "")
                            )
                        )
                    self.is_loading_more = False
                    self.log(self.trans("log_loaded_more", len(self.history_items)))
                self.root.after(0, render)
            except Exception as e:
                self.is_loading_more = False
                write_log(f"加载更多历史发生异常: {str(e)}")
                
        threading.Thread(target=worker, daemon=True).start()

    def save_settings(self):
        """Persist current settings form variables to configuration file."""
        provider = self.prov_var.get()
        entry_val = self.context_entry_var.get().strip()
        
        self.config["default_provider"] = provider
        if provider == "telegraph":
            if not entry_val.startswith("http://") and not entry_val.startswith("https://"):
                messagebox.showerror(self.trans("dialog_param_error_title"), self.trans("dialog_tg_error_msg"))
                return
            self.config["telegraph_domain"] = entry_val
        elif provider == "imgbb":
            self.config["imgbb_api_key"] = entry_val
        elif provider == "sm.ms":
            self.config["smms_token"] = entry_val
        elif provider == "imgse":
            self.config["imgse_api_key"] = entry_val
            
        save_config(self.config)
        self.log(self.trans("log_save_success"))
        self.show_toast(self.trans("toast_save_success"))

    def test_connection(self):
        """Ping the selected provider's domain in a thread to check internet latency."""
        import requests
        provider = self.prov_var.get()
        self.log(self.trans("log_start_test", provider))
        
        def worker():
            try:
                target_url = ""
                if provider == "telegraph":
                    target_url = self.context_entry_var.get().strip()
                elif provider == "catbox":
                    target_url = "https://catbox.moe"
                elif provider == "x0.at":
                    target_url = "https://x0.at/"
                elif provider == "imgbb":
                    target_url = "https://api.imgbb.com"
                elif provider == "sm.ms":
                    target_url = "https://smms.app"
                elif provider == "imgse":
                    target_url = "https://imgse.com"
                    
                if not target_url:
                    self.log(self.trans("log_test_failed_no_url"))
                    return
                    
                start_time = time.time()
                # Disable SSL verification issues warnings in logging if needed, standard requests head
                r = requests.head(target_url, timeout=10)
                elapsed = int((time.time() - start_time) * 1000)
                self.log(self.trans("log_test_success", elapsed, r.status_code))
            except Exception as e:
                self.log(self.trans("log_test_failed", str(e)))
                
        threading.Thread(target=worker, daemon=True).start()

    # ---------------- COPY & UTILITY FUNCTIONS ----------------
    def show_toast(self, text):
        """Display a transient visual toast message near the cursor or window center."""
        toast = tk.Label(
            self.root,
            text=text,
            font=("Segoe UI", 9, "bold"),
            bg=self.colors["success"],
            fg="#11111b",
            padx=12,
            pady=6,
            bd=0,
            relief="flat"
        )
        toast.place(relx=0.5, rely=0.1, anchor=tk.CENTER)
        
        def destroy():
            try:
                if toast.winfo_exists():
                    toast.destroy()
            except Exception:
                pass
        self.root.after(1500, destroy)

    def get_selected_history_item(self):
        """Fetch the history list dictionary element corresponding to tree selection."""
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            idx = int(selection[0])
            if hasattr(self, "history_items") and 0 <= idx < len(self.history_items):
                return self.history_items[idx]
        except Exception:
            pass
        return None

    def copy_to_clipboard(self, text, success_label="已复制"):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.log(f"{success_label}: {text}")
            self.show_toast(success_label)
        except Exception as e:
            self.log(f"复制失败: {str(e)}")

    def on_history_double_click(self, event):
        """Default double-click behavior: Copy raw URL."""
        item = self.get_selected_history_item()
        if item and "url" in item:
            self.copy_to_clipboard(item["url"], self.trans("toast_copied_raw"))

    def show_history_context_menu(self, event):
        """Trigger pop-up menu with action triggers for selected item."""
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
            
        self.tree.selection_set(iid)
        item = self.get_selected_history_item()
        if not item:
            return
            
        url = item.get("url", "")
        name = item.get("filename", "")
        
        menu = tk.Menu(self.root, tearoff=0, 
                       bg=self.colors["card"], fg=self.colors["text"],
                       activebackground=self.colors["accent"], activeforeground="#11111b", bd=1, relief="solid")
                       
        menu.add_command(label=self.trans("menu_copy_raw"), 
                         command=lambda: self.copy_to_clipboard(url, self.trans("toast_copied_raw")))
        menu.add_command(label=self.trans("menu_copy_markdown"), 
                         command=lambda: self.copy_to_clipboard(f"![{name}]({url})", self.trans("toast_copied_markdown")))
        menu.add_command(label=self.trans("menu_copy_html"), 
                         command=lambda: self.copy_to_clipboard(f'<img src="{url}" alt="{name}" />', self.trans("toast_copied_html")))
        menu.add_separator()
        menu.add_command(label=self.trans("menu_open_browser"), 
                         command=lambda: self.open_in_browser(url))
        menu.add_command(label=self.trans("menu_delete_history"), 
                         command=lambda: self.delete_history_item(int(iid)))
                         
        menu.post(event.x_root, event.y_root)

    def open_in_browser(self, url):
        import webbrowser
        try:
            webbrowser.open(url)
            self.log(self.trans("log_browser_open", url))
        except Exception as e:
            self.log(self.trans("log_browser_error", str(e)))

    def delete_history_item(self, idx):
        if hasattr(self, "history_items") and 0 <= idx < len(self.history_items):
            item = self.history_items[idx]
            self.db_mgr.delete_record(item["id"])
            self.refresh_history()
            self.log(self.trans("log_delete_history", item.get('filename')))

    def clear_history(self):
        if messagebox.askyesno(self.trans("dialog_confirm_title"), self.trans("dialog_clear_confirm_msg")):
            self.db_mgr.clear_all()
            self.refresh_history()
            self.log(self.trans("log_history_cleared"))

    # ---------------- UPLOAD TRIGGERS ----------------
    def on_file_drop(self, files):
        """Callback for windnd file drops."""
        if getattr(self, "is_uploading", False):
            self.log(self.trans("log_uploading_wait"))
            return
        if not files:
            return
            
        valid_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
        uploaded_count = 0
        
        for f in files:
            file_path = f
            if isinstance(file_path, bytes):
                for encoding in ('utf-8', 'gbk', 'utf-16'):
                    try:
                        file_path = file_path.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
            
            if isinstance(file_path, bytes):
                file_path = file_path.decode('utf-8', errors='ignore')
                
            file_path = os.path.abspath(file_path)
            
            if os.path.isfile(file_path):
                if file_path.lower().endswith(valid_extensions):
                    self.start_upload_thread(file_path)
                    uploaded_count += 1
                else:
                    self.log(self.trans("log_unsupported_format", os.path.basename(file_path)))
            else:
                self.log(self.trans("log_ignore_non_file", file_path))
                
        if uploaded_count > 0:
            self.log(self.trans("log_drag_detected", uploaded_count))

    def select_and_upload(self):
        """Open file picker, and launch threaded uploads."""
        if getattr(self, "is_uploading", False):
            self.log(self.trans("log_uploading_wait"))
            return
        files = filedialog.askopenfilenames(
            title="选择上传的图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.gif *.webp"), ("所有文件", "*.*")]
        )
        if not files:
            return
            
        for f in files:
            self.start_upload_thread(f)

    def paste_and_upload(self):
        """Query system clipboard, extract file or raw screenshot, and upload."""
        if getattr(self, "is_uploading", False):
            self.log(self.trans("log_uploading_wait"))
            return
        self.log(self.trans("log_checking_clipboard"))
        try:
            from PIL import ImageGrab
            img_data = ImageGrab.grabclipboard()
            if img_data is None:
                self.log(self.trans("msg_no_clipboard_img"))
                messagebox.showwarning(self.trans("msg_clipboard_empty"), self.trans("msg_no_clipboard_img"))
                return
                
            # Case 1: Clipboard contains copied file paths
            if isinstance(img_data, list):
                valid_files = []
                for item in img_data:
                    if os.path.isfile(item):
                        mime, _ = mimetypes.guess_type(item)
                        if mime and mime.startswith("image/"):
                            valid_files.append(item)
                            
                if not valid_files:
                    self.log(self.trans("log_clipboard_unsupported"))
                    return
                    
                for f in valid_files:
                    self.start_upload_thread(f)
                    
            # Case 2: Clipboard contains a raw screenshot memory object
            elif hasattr(img_data, "save"):
                # Save screenshot to a temporary file
                temp_dir = os.path.join(EXE_DIR, "temp")
                os.makedirs(temp_dir, exist_ok=True)
                
                temp_filename = f"clipboard_{int(time.time() * 1000)}.png"
                temp_path = os.path.join(temp_dir, temp_filename)
                
                img_data.save(temp_path, "PNG")
                self.log(self.trans("log_clipboard_screenshot", temp_filename))
                self.start_upload_thread(temp_path, is_temp=True)
            else:
                self.log(self.trans("log_clipboard_unknown"))
        except Exception as e:
            self.log(self.trans("log_clipboard_error", str(e)))
            traceback.print_exc()

    def start_upload_thread(self, file_path, is_temp=False):
        """Asynchronously execute upload requests to keep UI responsive."""
        provider = self.prov_var.get()
        self.log(self.trans("log_waiting_upload", provider, os.path.basename(file_path)))
        
        # Disable buttons temporarily during uploads to prevent multiple simultaneous click spam
        self.is_uploading = True
        self.btn_paste.config(state="disabled")
        
        def worker():
            try:
                # Retrieve fresh copy of config in thread
                fresh_config = load_config()
                
                # Compute MD5
                md5_val = calculate_md5(file_path)
                
                # Check DB for instant upload
                cached_url = self.db_mgr.get_url_by_md5(md5_val, provider)
                
                if cached_url:
                    url = cached_url
                    self.log(self.trans("log_instant_success", os.path.basename(file_path), url))
                else:
                    url = perform_upload(file_path, provider, fresh_config)
                    self.log(self.trans("log_upload_success", os.path.basename(file_path), url))
                
                # Add/Update record in DB
                self.db_mgr.add_record(
                    filename=os.path.basename(file_path),
                    filepath=os.path.abspath(file_path),
                    provider=provider,
                    size=f"{os.path.getsize(file_path) / 1024:.1f} KB",
                    url=url,
                    md5=md5_val
                )
                
                # Save/backup image file locally
                backup_image_file(file_path, provider)
                
                # Redraw Treeview and alert user via UI thread
                self.root.after(0, self.on_upload_success, url, os.path.basename(file_path))
                
                # If it's a temporary clipboard capture file, attempt cleanup
                if is_temp:
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
            except Exception as e:
                self.log(self.trans("log_upload_error", os.path.basename(file_path), str(e)))
                self.root.after(0, self.on_upload_error, str(e))
                
        threading.Thread(target=worker, daemon=True).start()

    def on_upload_success(self, url, filename):
        self.is_uploading = False
        self.btn_paste.config(state="normal")
        self.last_uploaded_url = url
        self.last_uploaded_filename = filename
        self.update_link_display()
        
        # Copy to clipboard in user's selected format automatically
        fmt = self.link_format_var.get()
        formatted = url
        if fmt in ("Markdown 格式", "Markdown Format"):
            formatted = f"![{filename}]({url})"
        elif fmt in ("HTML Image 标签", "HTML Image Tag"):
            formatted = f'<img src="{url}" alt="{filename}" />'
            
        self.root.clipboard_clear()
        self.root.clipboard_append(formatted)
        
        self.refresh_history()
        self.show_toast(self.trans("toast_upload_copy_success"))
        
    def on_upload_error(self, err_details):
        self.is_uploading = False
        self.btn_paste.config(state="normal")
        messagebox.showerror(self.trans("dialog_upload_failed_title"), self.trans("dialog_upload_failed_msg", err_details))

    def open_migration_dialog(self):
        # Create Toplevel window
        dialog = tk.Toplevel(self.root)
        dialog.title(self.trans("migration_dialog_title"))
        dialog.geometry("680x560")
        dialog.resizable(True, True)
        dialog.configure(bg=self.colors["bg"])
        
        # Make modal-like
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Title Label
        title_lbl = tk.Label(dialog, text=self.trans("migration_title"), 
                             font=("Segoe UI", 12, "bold"), 
                             bg=self.colors["bg"], fg=self.colors["accent"])
        title_lbl.pack(anchor=tk.W, padx=15, pady=(15, 5))
        
        desc_lbl = tk.Label(dialog, text=self.trans("migration_desc"), 
                             font=("Segoe UI", 9), justify=tk.LEFT,
                             bg=self.colors["bg"], fg=self.colors["text_muted"])
        desc_lbl.pack(anchor=tk.W, padx=15, pady=(0, 15))
        
        # Main container
        container = tk.Frame(dialog, bg=self.colors["bg"])
        container.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))
        
        # --- CARD 1: BATCH RE-UPLOAD ---
        card1 = tk.LabelFrame(container, text=self.trans("step1_title"), font=("Segoe UI", 9, "bold"),
                              bg=self.colors["card"], fg=self.colors["text"], bd=1, relief="solid")
        card1.pack(fill=tk.X, pady=(0, 10), ipady=5)
        
        sel_frame = tk.Frame(card1, bg=self.colors["card"])
        sel_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(sel_frame, text=self.trans("step1_src"), bg=self.colors["card"], fg=self.colors["text_muted"]).grid(row=0, column=0, sticky=tk.W)
        src_prov_var = tk.StringVar(value="x0.at")
        src_prov_combo = ttk.Combobox(sel_frame, textvariable=src_prov_var, values=["x0.at", "telegraph", "catbox", "imgbb", "sm.ms", "imgse"], state="readonly", width=12)
        src_prov_combo.grid(row=0, column=1, padx=(5, 15))
        
        tk.Label(sel_frame, text=self.trans("step1_dst"), bg=self.colors["card"], fg=self.colors["text_muted"]).grid(row=0, column=2, sticky=tk.W)
        dst_prov_var = tk.StringVar(value="catbox")
        dst_prov_combo = ttk.Combobox(sel_frame, textvariable=dst_prov_var, values=["x0.at", "telegraph", "catbox", "imgbb", "sm.ms", "imgse"], state="readonly", width=12)
        dst_prov_combo.grid(row=0, column=3, padx=5)
        
        btn_start_migrate = tk.Button(sel_frame, text=self.trans("step1_btn"), 
                                      bg=self.colors["accent"], fg="#11111b",
                                      activebackground=self.colors["accent_hover"], activeforeground="#11111b",
                                      bd=0, relief="flat", padx=15, pady=3,
                                      font=("Segoe UI", 9, "bold"), cursor="hand2")
        btn_start_migrate.grid(row=0, column=4, padx=(20, 0))
        
        warn_lbl = tk.Label(card1, text=self.trans("step1_warn"), font=("Segoe UI", 8),
                            bg=self.colors["card"], fg=self.colors["danger"],
                            wraplength=640, justify=tk.LEFT)
        warn_lbl.pack(fill=tk.X, padx=10, pady=(0, 5), anchor=tk.W)
        
        # --- CARD 2: REPLACE LINKS ---
        card2 = tk.LabelFrame(container, text=self.trans("step2_title"), font=("Segoe UI", 9, "bold"),
                              bg=self.colors["card"], fg=self.colors["text"], bd=1, relief="solid")
        card2.pack(fill=tk.X, pady=(0, 10), ipady=5)
        
        dir_frame = tk.Frame(card2, bg=self.colors["card"])
        dir_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(dir_frame, text=self.trans("step2_dir"), bg=self.colors["card"], fg=self.colors["text_muted"]).grid(row=0, column=0, sticky=tk.W)
        doc_dir_var = tk.StringVar()
        doc_dir_entry = tk.Entry(dir_frame, textvariable=doc_dir_var, bg=self.colors["input_bg"], fg=self.colors["text"], bd=0, highlightthickness=1, highlightbackground=self.colors["border"])
        doc_dir_entry.grid(row=0, column=1, padx=5, sticky=tk.EW)
        
        def browse_folder():
            folder = filedialog.askdirectory(title=self.trans("dialog_select_dir_title"))
            if folder:
                doc_dir_var.set(folder)
                
        btn_browse = tk.Button(dir_frame, text=self.trans("step2_btn_browse"), bg=self.colors["border"], fg=self.colors["text"], bd=0, relief="flat", padx=10, command=browse_folder, cursor="hand2")
        btn_browse.grid(row=0, column=2, padx=5)
        
        btn_start_replace = tk.Button(dir_frame, text=self.trans("step2_btn_replace"), 
                                      bg=self.colors["accent"], fg="#11111b",
                                      activebackground=self.colors["accent_hover"], activeforeground="#11111b",
                                      bd=0, relief="flat", padx=15, pady=3,
                                      font=("Segoe UI", 9, "bold"), cursor="hand2")
        btn_start_replace.grid(row=0, column=3, padx=5)
        
        dir_frame.columnconfigure(1, weight=1)
        
        # --- CONSOLE CARD IN DIALOG ---
        console_card = tk.LabelFrame(container, text=self.trans("migration_console_title"), font=("Segoe UI", 9, "bold"),
                                     bg=self.colors["card"], fg=self.colors["text"], bd=1, relief="solid")
        console_card.pack(fill=tk.BOTH, expand=True)
        
        diag_console = tk.Text(console_card, bg=self.colors["input_bg"], fg=self.colors["text"],
                               bd=0, font=("Consolas", 9), wrap=tk.WORD)
        diag_console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        def diag_log(msg):
            timestamp = datetime.now().strftime("%H:%M:%S")
            formatted = f"[{timestamp}] {msg}\n"
            def append():
                try:
                    if diag_console.winfo_exists():
                        diag_console.insert(tk.END, formatted)
                        diag_console.see(tk.END)
                except Exception:
                    pass
            dialog.after(0, append)
            
        diag_log(self.trans("migration_desc"))
        
        def run_migration_worker():
            src = src_prov_var.get()
            dst = dst_prov_var.get()
            if src == dst:
                messagebox.showerror(self.trans("dialog_param_error_title"), "Source and target providers cannot be the same!" if "English" in self.lang_var.get() else "源图床和目标图床不能相同！")
                return
                
            if not messagebox.askyesno(self.trans("dialog_confirm_title"), self.trans("msg_migrate_risk_confirm")):
                return
                
            btn_start_migrate.config(state="disabled")
            btn_start_replace.config(state="disabled")
            
            diag_log(self.trans("mig_start", src, dst))
            
            src_dir = os.path.join(BACKUP_DIR, src)
            if not os.path.isdir(src_dir):
                diag_log(self.trans("mig_err_backup_dir", src_dir))
                btn_start_migrate.config(state="normal")
                btn_start_replace.config(state="normal")
                return
                
            files = [f for f in os.listdir(src_dir) if os.path.isfile(os.path.join(src_dir, f))]
            if not files:
                diag_log(self.trans("mig_err_no_images", src_dir))
                btn_start_migrate.config(state="normal")
                btn_start_replace.config(state="normal")
                return
                
            diag_log(self.trans("mig_found_files", len(files)))
            
            fresh_config = load_config()
            success_count = 0
            skip_count = 0
            fail_count = 0
            
            for idx, fname in enumerate(files):
                fpath = os.path.join(src_dir, fname)
                try:
                    md5_val = calculate_md5(fpath)
                    
                    # 1. Look up the old URL in database (either by MD5 or by filename)
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute('''
                        SELECT url FROM uploads 
                        WHERE (md5 = ? OR filename = ?) AND provider = ? 
                        ORDER BY id DESC LIMIT 1
                    ''', (md5_val, fname, src))
                    row = c.fetchone()
                    conn.close()
                    
                    old_url = row[0] if row else None
                    if not old_url:
                        diag_log(self.trans("mig_no_old_record", idx+1, len(files), fname, src))
                    
                    # 2. Check if already uploaded to dst
                    cached_dst_url = self.db_mgr.get_url_by_md5(md5_val, dst)
                    if cached_dst_url:
                        new_url = cached_dst_url
                        diag_log(self.trans("mig_exist_skip", idx+1, len(files), fname, dst, new_url))
                        self.db_mgr.add_record(
                            filename=fname,
                            filepath=os.path.abspath(fpath),
                            provider=dst,
                            size=f"{os.path.getsize(fpath) / 1024:.1f} KB",
                            url=new_url,
                            md5=md5_val
                        )
                        backup_image_file(fpath, dst)
                        skip_count += 1
                        success_count += 1
                        continue
                    
                    # 3. Perform upload to dst
                    diag_log(self.trans("mig_uploading", idx+1, len(files), fname, dst))
                    new_url = perform_upload(fpath, dst, fresh_config)
                    diag_log(self.trans("mig_success", idx+1, len(files), new_url))
                    
                    # Record to db
                    self.db_mgr.add_record(
                        filename=fname,
                        filepath=os.path.abspath(fpath),
                        provider=dst,
                        size=f"{os.path.getsize(fpath) / 1024:.1f} KB",
                        url=new_url,
                        md5=md5_val
                    )
                    
                    # Also back it up locally to dst backup folder
                    backup_image_file(fpath, dst)
                    success_count += 1
                    
                except Exception as ex:
                    fail_count += 1
                    diag_log(self.trans("mig_failed", idx+1, len(files), fname, str(ex)))
            
            diag_log(self.trans("mig_complete", success_count, skip_count, fail_count))
            
            self.root.after(0, self.refresh_history)
            btn_start_migrate.config(state="normal")
            btn_start_replace.config(state="normal")
            
        def run_replace_worker():
            folder = doc_dir_var.get().strip()
            if not folder or not os.path.isdir(folder):
                messagebox.showerror(self.trans("dialog_confirm_title"), self.trans("mig_err_select_dir"))
                return
                
            src = src_prov_var.get()
            dst = dst_prov_var.get()
            
            btn_start_migrate.config(state="disabled")
            btn_start_replace.config(state="disabled")
            
            diag_log(self.trans("mig_build_map", src, dst))
            mapping = get_url_migration_map(DB_PATH, src, dst)
            
            if not mapping:
                diag_log(self.trans("mig_err_no_map"))
                diag_log(self.trans("mig_check_confirm"))
                diag_log(self.trans("mig_check_step1"))
                diag_log(self.trans("mig_check_db", src, dst))
                btn_start_migrate.config(state="normal")
                btn_start_replace.config(state="normal")
                return
                
            diag_log(self.trans("mig_loaded_pairs", len(mapping)))
            for old_url, new_url in mapping.items():
                diag_log(f"  {old_url} -> {new_url}")
                
            diag_log(self.trans("mig_start_scan", folder))
            
            total_files = 0
            modified_files = 0
            
            for root_dir, _, files in os.walk(folder):
                for file in files:
                    if file.lower().endswith(('.md', '.txt')):
                        if file.lower().endswith('.bak'):
                            continue
                            
                        file_path = os.path.join(root_dir, file)
                        total_files += 1
                        
                        content = None
                        encoding_used = 'utf-8'
                        for enc in ['utf-8', 'gbk', 'utf-16', 'latin-1']:
                            try:
                                with open(file_path, 'r', encoding=enc) as f:
                                    content = f.read()
                                encoding_used = enc
                                break
                            except UnicodeDecodeError:
                                continue
                                
                        if content is None:
                            diag_log(self.trans("mig_warn_decode", file))
                            continue
                            
                        replaced_urls = []
                        new_content = content
                        for old_url, new_url in mapping.items():
                            if old_url in new_content:
                                new_content = new_content.replace(old_url, new_url)
                                replaced_urls.append(old_url)
                                
                        if replaced_urls:
                            try:
                                bak_path = file_path + ".bak"
                                shutil.copy2(file_path, bak_path)
                                
                                with open(file_path, 'w', encoding=encoding_used) as f:
                                    f.write(new_content)
                                    
                                modified_files += 1
                                diag_log(self.trans("mig_modified_file", os.path.relpath(file_path, folder)))
                                diag_log(self.trans("mig_backup_created", os.path.basename(bak_path)))
                                diag_log(self.trans("mig_replaced_count", len(replaced_urls)))
                            except Exception as write_ex:
                                diag_log(self.trans("mig_err_write", file, str(write_ex)))
                                
            diag_log(self.trans("mig_replace_complete", total_files, modified_files))
            btn_start_migrate.config(state="normal")
            btn_start_replace.config(state="normal")
            
        btn_start_migrate.config(command=lambda: threading.Thread(target=run_migration_worker, daemon=True).start())
        btn_start_replace.config(command=lambda: threading.Thread(target=run_replace_worker, daemon=True).start())

# ----------------- MAIN EXECUTION ENTRY -----------------
if __name__ == "__main__":
    # Remove script arguments from sys.argv (sys.argv[0] is the command name/script path)
    args = sys.argv[1:]
    
    if len(args) > 0:
        # CLI Mode (Typora Custom Command upload trigger)
        # Typora passes absolute paths as arguments
        run_cli(args)
    else:
        # GUI Mode (Interactive user app)
        root = tk.Tk()
        root.withdraw() # Hide window to avoid blank white flash during widget creation
        app = UploaderApp(root)
        root.update_idletasks()
        root.deiconify() # Show fully constructed window
        root.mainloop()
