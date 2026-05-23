# Vox Code

> 一个面向开发工作流的 AI CLI，带有桌宠 GUI、工具调用、记忆、RAG 和多运行模式。

Vox Code 试图把“能聊天的模型”变成“能在本地开发环境里协作的助手”。  
它既可以作为纯终端工具使用，也可以作为桌面编程搭子运行。

当前版本：`2.0.0`

## Highlights

- `vox-code`：终端交互式 AI CLI
- `vox-pet`：基于 `PySide6` 的桌宠 GUI
- 支持 `GLM`、`DeepSeek`、`Qwen API`、`Ollama`
- 支持 `/model` 动态切换模型
- 支持 `single / plan / team` 三种运行模式
- 内置工具调用、代码检索、Memory、RAG、HITL、安全策略和审计日志
- 配置与源码分离，支持 `.env`、环境变量和用户目录配置

## Why Vox Code

和普通的聊天壳不一样，Vox Code 更偏向“本地开发协作工具”：

- 不只关心对话，还关心项目上下文、命令执行和代码检索
- 不把模型绑定死在单一厂商，支持云端和本地模型混用
- 同时提供 CLI 和桌宠 GUI，两套交互风格可以共存
- 适合作为个人 AI Coding Assistant 的实验场和产品原型

## Quick Start

### Requirements

- Python `3.11+`

### 1. Install

CLI only:

```bash
pip install -e .
```

With GUI:

```bash
pip install -e ".[gui]"
```

### 2. Init Config

推荐先运行：

```bash
vox-code init
```

它会引导你填写：

- provider
- model
- base URL
- API key

也可以手动写 `.env` 或环境变量，示例见 [.env.example](.env.example)。

### 3. Start CLI

```bash
vox-code
```

### 4. Start Desktop Pet

```bash
vox-pet
```

也支持模块方式启动：

```bash
python -m voxcli
python -m voxcli.gui
```

## Supported Providers

当前正式支持的 provider：

| Provider | Mode | Default Model |
| --- | --- | --- |
| `glm` | Cloud API | `glm-5.1` |
| `deepseek` | Cloud API | `deepseek-chat` |
| `qwen` | Cloud API | `qwen-plus` |
| `ollama` | Local Model | `qwen2.5:7b` |

说明：

- `qwen` 支持 `QWEN_*` 变量名
- 同时兼容阿里云 `DASHSCOPE_*` 变量名
- `ollama` 适合本地模型和离线/低成本场景

## Configuration

### Config Priority

配置按下面优先级读取：

1. 环境变量
2. `.env`
3. `~/.vox-code/config.json`

默认配置目录：

- macOS / Linux: `~/.vox-code/config.json`
- Windows: `%USERPROFILE%\.vox-code\config.json`

也支持自定义目录：

- `VOX_CODE_HOME`
- `VOX_HOME`

### Example: GLM

```bash
export GLM_API_KEY="your_key"
export GLM_MODEL="glm-5.1"
export GLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4/chat/completions"
vox-code
```

### Example: DeepSeek

```bash
export DEEPSEEK_API_KEY="your_key"
export DEEPSEEK_MODEL="deepseek-chat"
export DEEPSEEK_BASE_URL="https://api.deepseek.com/chat/completions"
vox-code
```

### Example: Qwen

```bash
export QWEN_API_KEY="your_key"
export QWEN_MODEL="qwen-plus"
export QWEN_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
vox-code
```

兼容 DashScope 命名：

```bash
export DASHSCOPE_API_KEY="your_key"
export DASHSCOPE_MODEL="qwen-plus"
export DASHSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
vox-code
```

### Example: Ollama

```bash
export OLLAMA_MODEL="qwen2.5:7b"
export OLLAMA_BASE_URL="http://localhost:11434"
vox-code
```

## Common Commands

| Command | Description |
| --- | --- |
| `vox-code init` | 初始化模型配置 |
| `vox-code config-path` | 查看配置文件路径 |
| `/model <preset-id\|provider[:model]>` | 切换模型 |
| `/team` | 切换运行模式 |
| `/style <work\|pet>` | 切换展示风格 |
| `/memory` | 查看记忆状态 |
| `/policy` | 查看安全策略 |
| `/audit` | 查看最近审计日志 |

## Desktop GUI

`vox-pet` 会启动桌宠界面，适合偏轻量、陪伴式的交互方式。

GUI 当前支持：

- 跟随全局 CLI 配置
- 独立 GUI 模型配置
- OpenAI Compatible 网关
- Qwen API 标签显示

如果 `PySide6` 不可用，GUI 无法启动，但 CLI 仍可正常使用。

如果你要把 GUI 一起装上：

```bash
pip install "vox-code[gui]"
```

## Project Layout

```text
voxcli/
├── agent/       # Agent、Plan-and-Execute、多 Agent 协作
├── cli/         # CLI 入口与命令解析
├── config.py    # 配置读取与持久化
├── gui/         # 桌宠 GUI
├── hitl/        # 人工审批与交互控制
├── llm/         # 模型接入层
├── memory/      # 长短期记忆
├── rag/         # 索引、切块、检索、嵌入
├── runtime/     # 会话控制器
├── tool/        # 工具注册与调用
└── web/         # Web 搜索与抓取
```

## Development

常用开发命令：

```bash
vox-code
vox-pet
vox-code config-path
```

如果你想快速验证配置是否生效，推荐先跑：

```bash
vox-code init
```
