# CaseMind Windows 桌面客户端打包

提供两种方案，任选其一。**推荐方案 A（Electron）**，用户体验最佳。

---

## 方案 A: Electron + PyInstaller （推荐）

原理：
1. 用 **PyInstaller** 把后端打包成单个 `casemind-backend.exe`
2. 用 **Electron** 包装前端构建产物（`frontend/dist`），并在启动时 spawn 后端 exe
3. 最终用 **electron-builder** 生成 Windows 安装包 `.exe` / `.msi`

### A.1 后端打包为 exe

在项目根执行：

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean ^
  --name casemind-backend ^
  --onefile ^
  --add-data "prompts;prompts" ^
  --collect-all sentence_transformers ^
  --collect-all faiss ^
  --hidden-import uvicorn.loops.asyncio ^
  --hidden-import uvicorn.protocols.http.httptools_impl ^
  backend\main.py
```

产出：`dist\casemind-backend.exe`。首次启动仍会下载嵌入模型到用户目录，可用 `HF_HOME` 环境变量把缓存内置到安装目录。

### A.2 前端构建

```bash
cd frontend
npm install
npm run build
# 产出 frontend/dist
```

> 注意：Electron 场景下不能依赖 Vite 的 `/api` 代理，需要把 `src/api.js` 中的 `API_BASE`
> 改成绝对地址 `http://127.0.0.1:8888/api` 后再构建。

### A.3 Electron 包装

`desktop/` 目录已提供 `package.json` 和 `main.js`：

```bash
cd desktop
npm install
# 把后端 exe 和前端 dist 放到预期位置
#   desktop/bin/casemind-backend.exe   <- 从 dist 复制
#   desktop/web/                        <- 从 frontend/dist 复制
npm run dist
```

产出：`desktop/release/CaseMind-Setup-x.y.z.exe`（electron-builder 生成）。

---

## 方案 B: 纯 PyInstaller + 内嵌静态前端（轻量）

原理：前端构建产物直接由 FastAPI 通过 `StaticFiles` 托管，单 exe 即可运行。

### B.1 修改后端静态托管

在 `backend/main.py` 末尾追加（仅打包时启用，通过环境变量控制）：

```python
import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles

static_dir = Path(os.environ.get("CASEMIND_STATIC", "")) or (Path(__file__).resolve().parent.parent / "web")
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
```

### B.2 打包

```bash
cd frontend && npm run build && cd ..
xcopy /e /i frontend\dist web
pyinstaller --noconfirm --clean --name CaseMind --onefile ^
  --add-data "prompts;prompts" ^
  --add-data "web;web" ^
  --collect-all sentence_transformers ^
  --collect-all faiss ^
  backend\main.py
```

产出 `dist\CaseMind.exe`，双击启动，浏览器访问 `http://127.0.0.1:8888`。

---

## 目录

- `desktop/package.json` — Electron 应用清单（含 electron-builder 配置）
- `desktop/main.js` — Electron 主进程（启动后端子进程 + 加载前端）
- `desktop/preload.js` — 预加载脚本（空壳，便于后续扩展）

## 说明

- 首次启动会下载嵌入模型到 `%USERPROFILE%\.cache\huggingface`（约 100MB）。为实现离线安装，可将模型预置到安装目录，并在启动时设置 `HF_HOME` 环境变量指向它。
- 后端默认监听 `127.0.0.1:8888`，不对外暴露。
- API Key 存在浏览器 localStorage 中，不会写入后端持久化。
