# Codex Internal API Proxy

把 Codex CLI / Desktop 的 **OpenAI Responses API** 请求转成公司内网 LLM 网关的 **OpenAI Chat Completions API** 请求。

- 单文件 Python,~350 行,FastAPI + httpx
- 支持流式 (SSE) + 非流式
- **正确处理工具调用** (流式累积、多轮、并行)
- 支持图像输入、token 用量、健康检查
- 计划任务 / NSSM 服务 自启均可

---

## 架构

```
Codex CLI / Desktop
    |
    | POST /v1/responses  (Responses API 形态)
    v
本地代理 127.0.0.1:8000
    |
    | POST /chat/completions  (Chat Completions API 形态)
    v
公司内网 LLM 网关
```

---

## 部署步骤

### 1. Python (3.10+)

下载 https://www.python.org/downloads/ ,安装时勾选 "Add Python to PATH"。验证:

```powershell
python --version
```

### 2. 安装依赖

```powershell
cd C:\Users\A\codex-proxy
pip install -r requirements.txt
```

**离线场景** (公司机不能访问 PyPI): 在能上网的机器上:

```powershell
pip download -r requirements.txt -d wheels
```

把整个 `codex-proxy` 目录 (含 `wheels/`) 拷到公司机,然后:

```powershell
pip install --no-index --find-links=wheels -r requirements.txt
```

### 3. 改配置

```powershell
copy .env.example .env
notepad .env
```

改这三项:

```ini
UPSTREAM_BASE_URL=https://your-internal-llm.corp.local/v1
UPSTREAM_API_KEY=你的内网 API Key
UPSTREAM_MODEL=内网模型实际名字
```

### 4. 启动

| 场景 | 命令 |
|---|---|
| 前台 (看日志) | `start.bat` |
| 后台 (无窗口) | `start_background.bat` |
| 查看状态 | `powershell -File status.ps1` |
| 停止 | `powershell -File stop.ps1` |

### 5. 验证代理本身能工作

```powershell
pip install httpx      # 测试也需要
python test_proxy.py
```

期望看到:
- `OK streaming chat`
- `OK tool calling works`

如果第二条 **FAIL**,就是你之前踩的坑 — 看下面的调试部分。

---

## 配置 Codex

### 5.1 `~/.codex/config.toml`

参考 `codex_config.toml.template`,把 `internal-model-name` 替换成你 `.env` 里的 `UPSTREAM_MODEL`。

### 5.2 `~/.codex/models.json`

合并 `codex_models.json.template` 的内容进去,把模型名替换成实际值。

### 5.3 启动 Codex 测试

```powershell
codex
```

---

## 高级

### 开机自启 (推荐)

```powershell
powershell -ExecutionPolicy Bypass -File .\install_schtask.ps1
```

注销重登后代理自启。删除:

```powershell
Unregister-ScheduledTask -TaskName CodexInternalProxy
```

### NSSM 做成 Windows 服务

1. 下载 https://nssm.cc/download ,把 `nssm.exe` 加到 PATH
2. `install_service.bat`

### 调试

`.env`:

```ini
LOG_LEVEL=DEBUG
REQUEST_LOG=./requests.log
DEBUG_DUMP=true
```

重启代理,`requests.log` 会有完整请求体,`proxy.log` 会有每个请求的转换日志。

### 自定义鉴权

如果上游不是 Bearer Token:

```ini
AUTH_HEADER=Basic dXNlcjpwYXNzd29yZA==
```

或者加额外 header:

```ini
EXTRA_HEADERS=X-Corp-User=alice;X-Trace-ID=foo
```

---

## 故障 1: 工具调用没反应 ("只能聊天")

跑 `python test_proxy.py` 验证。如果 `tool calling` 测试 FAIL:

1. 设 `DEBUG_DUMP=true`,重启,重跑测试
2. 打开 `requests.log` 看 Codex 发出去的 `tools` 数组,确认:
   - 顶层字段是 `name` / `description` / `parameters` (Responses 形态) — 我的代理会负责转 Chat 形态
   - `parameters` 是合法 JSON Schema
3. 打开 `proxy.log`,搜 `[req_id] ->`,找这次请求,确认 `tools=N` 不为 0
4. 看上游返回: 在 `proxy.log` 里看是不是有 `tool_calls` 流回来

---

## 故障 2: 上游 400

`.env` 设 `LOG_LEVEL=DEBUG` 后重跑。看 `proxy.log` 里的请求体,重点确认:

- `reasoning_effort` 字段已剥掉 (代理自动处理)
- `tools[].parameters` 是合法 JSON Schema
- `messages` 顺序是 user / assistant / tool 交替

---

## 故障 3: 代理起不来

- **8000 端口占用**: `.env` 改 `LISTEN_PORT=8001`
- **依赖没装全**: 重跑 `pip install -r requirements.txt`
- **.env 不存在**: `copy .env.example .env`

---

## 文件清单

```
C:\Users\A\codex-proxy\
  codex_proxy.py          主代理
  requirements.txt        Python 依赖
  .env.example            配置模板
  start.bat               前台启动
  start_background.bat    后台启动
  stop.ps1                停止
  status.ps1              状态 + 健康检查
  test_proxy.py           自动化测试
  install_schtask.ps1     计划任务自启
  install_service.bat     NSSM 服务安装
  uninstall_service.bat   卸载服务
  codex_config.toml.template    Codex config 参考
  codex_models.json.template    Codex models 参考
```# openai
