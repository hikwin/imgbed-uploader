# i图床 - 匿名图床上传工具 (支持 GUI 与 Typora CLI 集成) / Anonymous Image Uploader (GUI & Typora CLI)

[中文说明](#中文说明) | [English Documentation](#english-documentation)

---

## 中文说明

这是一个免注册、免登录的轻量级匿名图床上传工具。同时支持 **图形用户界面 (GUI)** 与 **命令行界面 (CLI)**，专门适配了 Markdown 编辑器 **Typora** 的自定义图像上传服务规范。

### 核心特性

1. **多图床支持**：
   - **x0.at** (推荐/匿名)：单文件限制 19MB，全球速度极快，匿名且永久/长期存储。
   - **Catbox.moe** (匿名)：单文件限制 200MB，非常稳定的国际文件托管平台，只要不违规可永久保留。
   - **SM.MS (smms.app)** (国内高速/推荐)：支持配置您免费注册获取的 Secret Token。SM.MS 专门针对中国大陆地区部署了高速 CDN 加速节点，访问及上传体验极为优越。
   - **Imgse (路过图床)** (国内高速/推荐)：支持配置您免费获取的 API Key。作为国内最老牌稳定的图床服务商之一，提供高可用的国内网络访问与上传通道。
   - **ImgBB (可选配置)**：在设置界面输入您个人的免费 API Key 后，可直接上传到 ImgBB。
   - **Telegraph (telegra.ph)**：单文件限制 5MB。提供反代域名设置，方便用户选择不同的 Telegraph 国内镜像节点。*(注：目前官方接口因防滥用限制了匿名直接上传)*。

2. **剪贴板一键粘贴上传 (GUI)**：
   - 支持从系统剪贴板中检测新截取的图片（如使用 Win+Shift+S 截图后）或复制的图片文件，点击 GUI 的 **粘贴并上传** 即可一键完成上传并复制 URL，非常适合日常写作配图。

3. **本地 SQLite 数据库历史记录 (GUI)**：
   - 历史记录全面采用本地轻量 SQLite 数据库 `uploader.db` 管理，支持存储海量记录而不卡顿。
   - 首次启动程序时，将自动将原 `uploader_config.json` 中的旧历史记录导入 `uploader.db` 并清除 JSON 配置中的 `history` 字段。
   - 右键任意历史条目可快捷复制为：**原始链接 (Raw URL)**、**Markdown 格式图片标记 `![alt](url)`**、**HTML 格式图片标签 `<img src="url" />`**。

4. **MD5 校验与“秒传”机制 (Seconds-upload)**：
   - 上传图片前会自动计算文件的 MD5 校验和。
   - 校验当前选中的图床（Active Provider）下是否已存在该 MD5 的上传记录，若有则直接从本地数据库调出公网 URL 瞬间返回（即“秒传”），无需发出重复的网络上传请求。

5. **本地图片自动备份归档**：
   - 程序会在同级目录下创建 `images_backup` 文件夹。
   - 所有成功上传或秒传（若本地已删）的图片，都会按传输图床保存在对应的子文件夹中（如：`images_backup/x0.at/`），用于容灾备份。

6. **图床批量迁移与本地链接一键替换工具 (GUI)**：
   - **步骤 1：批量重传** — 当某个图床倒闭或失效时，在迁移界面中选择“源图床”与“目标图床”，点击“开始重传”，程序会自动将本地备份目录中的所有源图床图片重新上传至目标图床，并在数据库中建立 “旧链接 <-> 新链接” 关联。
   - **步骤 2：链接替换** — 指定一个包含 Markdown 或文本文件的目录，程序将递归搜索该目录下的所有 `.md` 和 `.txt` 文件，自动完成已迁移链接的一键替换。同时，为保障安全，会在同级目录下自动为被修改的文件生成 `.bak` 备份文件。

7. **无缝集成 Typora (CLI)**：
   - 命令行接受一个或多个本地 file 路径参数，静默上传并返回 Typora 规范的 stdout 输出。

---

### 如何运行 GUI 界面

您可以通过以下两种方式双击/运行 GUI 界面：
- **可执行文件方式**：双击运行打包好的 `dist/uploader.exe`。
- **Python 脚本方式**：在终端运行 `python uploader.py`。

---

### 如何在 Typora 中配置自动上传

1. 打开 Typora，点击菜单栏的 **文件 > 偏好设置** (或快捷键 `Ctrl + ,`)。
2. 在左侧栏选择 **图像**。
3. 将 **插入图片时...** 设置为：*上传图片*（或勾选 *对本地位置的图片应用上述规则*）。
4. 将 **上传服务** 选择为：**Custom Command (自定义命令)**。
5. 在 **命令 (Command)** 输入框中，填写已打包的可执行文件的绝对路径。例如：
   ```powershell
   "C:/Users/24057/tarer/toc/dist/uploader.exe"
   ```
   *(或者，如果您不想使用打包好的 exe，也可以填写 python 脚本路径，例如：`python "C:/Users/24057/tarer/toc/uploader.py"`)*
6. 点击旁边的 **Test Uploader (测试 Uploader)** 按钮。如果提示 **"验证成功"** 且 Typora 能显示测试图片的上传外链，说明配置已完美成功！

---

### 如何重新编译/打包 `.exe`

如果您修改了代码，可以使用以下步骤重新打包成单文件可执行程序：

1. 确保安装了 `requests`、`pillow` 和 `pyinstaller`：
   ```powershell
   pip install requests pillow pyinstaller
   ```
2. 在项目根目录下执行以下打包命令：
   ```powershell
   python -m PyInstaller --clean uploader.spec
   ```
3. 打包完成后，新生成的 `uploader.exe` 将存放在 `./dist` 目录中。

---

### 配置文件、数据库与日志

- **配置文件** (`uploader_config.json`)：自动创建在同级目录下，用于保存您设置的默认图床、Telegraph 反代域名和 ImgBB API Key。
- **本地数据库** (`uploader.db`)：用于以 SQLite 结构存储您的所有图片上传历史、MD5 索引以支撑秒传及重传迁移。
- **备份目录** (`images_backup/`)：保存各个图床上传成功的图片副本。
- **日志文件** (`uploader.log`)：记录上传/秒传详细步骤和报错详情，方便排查 Typora 自定义上传时的异常。

---
---

## English Documentation

This is a lightweight, registration-free anonymous image uploader. It supports both **Graphical User Interface (GUI)** and **Command Line Interface (CLI)**, and is specifically designed to fit the custom image upload service specification of the Markdown editor **Typora**.

### Core Features

1. **Multi-Provider Support**:
   - **x0.at** (Recommended/Anonymous): Single file limit 19MB. Extremely fast globally, anonymous, and provides permanent/long-term storage.
   - **Catbox.moe** (Anonymous): Single file limit 200MB. A highly stable international file hosting platform that retains files permanently as long as they comply with guidelines.
   - **SM.MS (smms.app)** (High-speed in China/Recommended): Supports configuring your free Secret Token. SM.MS has deployed high-speed CDN acceleration nodes in Mainland China, offering excellent upload and access speed.
   - **Imgse (路过图床)** (High-speed in China/Recommended): Supports configuring your free API Key. One of the oldest and most stable image hosting services in China, providing high-availability local network access and upload channels.
   - **ImgBB (Optional configuration)**: Enter your personal free API Key in the settings interface to upload directly to ImgBB.
   - **Telegraph (telegra.ph)**: Single file limit 5MB. Provides custom proxy/mirror domain settings so users can choose different domestic Telegraph mirror nodes. *(Note: The official API currently restricts direct anonymous uploads to prevent abuse)*.

2. **One-Click Paste & Upload (GUI)**:
   - Automatically detects newly captured screenshots (e.g. captured via Win+Shift+S) or copied image files from the system clipboard. Click **Paste & Upload** in the GUI to upload and copy the URL in one click—perfect for writing Markdown articles.

3. **Local SQLite Database Upload History (GUI)**:
   - Upload history is fully managed via a lightweight local SQLite database `uploader.db`, which can handle millions of records without lagging.
   - Upon first startup, the program automatically imports legacy history from `uploader_config.json` into `uploader.db` and clears the `history` field from the JSON configuration.
   - Right-click any history entry to copy as: **Raw URL**, **Markdown format image tag `![alt](url)`**, or **HTML image tag `<img src="url" />`**.

4. **MD5 Checksum & Instant Upload (Seconds-Upload)**:
   - Computes the MD5 checksum of the file before uploading.
   - Checks if the file has already been uploaded under the currently active provider. If a record exists, it retrieves the URL from the local database instantly (seconds-upload), skipping duplicate network requests.

5. **Automatic Local Image Backups**:
   - Creates an `images_backup` folder in the same directory as the executable.
   - Backs up all successfully uploaded or instantly returned files into subfolders named after their provider (e.g., `images_backup/x0.at/`) for disaster recovery.

6. **Provider Migration & Link Auto-Replacement Tool (GUI)**:
   - **Step 1: Batch Re-upload** — If an image provider shuts down or becomes unreachable, select the "Source Provider" and "Target Provider" in the migration dialog, click "Start Re-upload", and the program will automatically re-upload all backed-up images to the target provider and link them in the database.
   - **Step 2: Link Replacement** — Specify a folder containing documents. The program recursively scans all `.md` and `.txt` files to replace legacy links. For security, it creates a `.bak` backup file in the same directory before editing the file.

7. **Seamless Typora Integration (CLI)**:
   - The command-line mode accepts one or more local file paths, silently uploads them, and prints standard output complying with Typora's custom upload service specification.

---

### Running the GUI App

You can launch the GUI interface in two ways:
- **Executable**: Double-click the compiled `dist/uploader.exe`.
- **Python Script**: Run `python uploader.py` in your terminal.

---

### Configuring Typora Auto-Upload

1. Open Typora and click **File > Preferences** (or use shortcut `Ctrl + ,`).
2. Select **Image** in the left sidebar.
3. Set **When Insert Image...** to: *Upload Image* (or check *Apply above rules to local images*).
4. Set **Image Uploader** to: **Custom Command**.
5. In the **Command** input box, enter the absolute path of the compiled executable, for example:
   ```powershell
   "C:/Users/24057/tarer/toc/dist/uploader.exe"
   ```
   *(Alternatively, if you prefer python scripts: `python "C:/Users/24057/tarer/toc/uploader.py"`)*
6. Click the **Test Uploader** button next to it. If it says **"Validation Successful"** and Typora displays the upload URLs, the configuration is complete!

---

### Compiling & Packaging `.exe`

If you modify the source code, you can package it into a standalone executable using:

1. Install dependencies:
   ```powershell
   pip install requests pillow pyinstaller
   ```
2. Run the packaging command in the project root:
   ```powershell
   python -m PyInstaller --clean uploader.spec
   ```
3. Once completed, the standalone `uploader.exe` will be located in the `./dist` folder.

---

### Configurations, Database & Logs

- **Configuration File** (`uploader_config.json`): Created automatically in the same directory to store your active provider, custom Telegraph domains, and API Keys.
- **Local Database** (`uploader.db`): Stores image upload records and MD5 indexes to support instant uploads and migration mapping.
- **Backup Directory** (`images_backup/`): Contains local backups of successfully uploaded images categorized by provider.
- **Log File** (`uploader.log`): Logs detailed upload steps and exceptions, useful for troubleshooting Typora custom command upload errors.
