# Vox Code

Vox Code 是一个面向本地开发工作流的 AI 助手，提供交互式命令行和 PySide6 桌宠界面。它可以连接云端模型或本机 Ollama，并在当前项目目录中调用文件、命令、代码检索和网页工具。

## 功能

- **多种模型**：CLI 支持 GLM、DeepSeek、Qwen 和 Ollama；可在会话中切换模型。
- **多种工作模式**：单 Agent、Plan-and-Execute，以及由多个 Agent 协作的 team 模式。
- **项目工具**：读取和写入项目文件、列出目录、运行命令、创建项目结构。
- **代码检索**：索引当前项目并搜索相关代码；也可使用网页搜索和网页内容抓取工具。
- **记忆与审批**：短期和长期记忆、工具操作审批、安全策略和审计记录。
- **桌宠 GUI**：通过 `vox-pet` 启动桌面界面；支持聊天、图片附件、模型设置和内置桌宠外观。

## 环境要求

- Python 3.11 或更高版本
- 使用云端模型时，需要相应服务的 API Key 和网络连接
- 使用 Ollama 时，需要在本机安装并运行 Ollama

## 安装

在项目根目录创建并启用虚拟环境，然后安装完整依赖（包含 GUI 和开发辅助依赖）：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

也可以按需安装：

```bash
python -m pip install -e .          # CLI
python -m pip install -e ".[gui]"  # CLI 和桌宠 GUI
```

## 配置模型

推荐运行初始化向导：

```bash
vox-code init
```

按提示选择提供商并填写模型名称、Base URL 和 API Key。Ollama 不需要 API Key。配置保存在用户目录的 `~/.vox-code/config.json`（Windows 下为 `%USERPROFILE%\.vox-code\config.json`）。

也可以复制 `.env.example` 为 `.env`，填入对应提供商的信息。`.env` 会从当前工作目录或用户主目录读取；实际环境变量优先于 `.env`，`.env` 中的值优先于配置文件。

| 提供商 | 环境变量 | 默认模型 |
| --- | --- | --- |
| GLM | `GLM_API_KEY`、`GLM_MODEL`、`GLM_BASE_URL` | `glm-5.1` |
| DeepSeek | `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL` | `deepseek-chat` |
| Qwen | `QWEN_API_KEY`、`QWEN_MODEL`、`QWEN_BASE_URL` | `qwen-plus` |
| Ollama | `OLLAMA_MODEL`、`OLLAMA_BASE_URL` | `qwen2.5:7b` |

Qwen 也接受 `DASHSCOPE_API_KEY`、`DASHSCOPE_MODEL` 和 `DASHSCOPE_BASE_URL`。默认 Base URL 已内置，只有使用自定义兼容服务时才需要单独指定。

默认提供商可通过 `VOX_CODE_DEFAULT_PROVIDER` 设置。`VOX_CODE_HOME`（兼容 `VOX_HOME`）可修改配置目录；`VOX_CODE_MEMORY_DIR` 可修改长期记忆目录。更多变量示例见 [.env.example](.env.example)。

## 使用步骤

### 启动 CLI

在希望 Vox Code 访问的项目目录中打开终端，然后运行：

```bash
vox-code
```

首次使用时，先运行 `vox-code init` 配置模型，再运行 `vox-code`。进入交互界面后，直接输入问题；输入 `/help` 查看命令，输入 `/exit` 退出。CLI 会把启动时所在的目录作为当前项目目录。

### Windows：启动桌宠 UI

在 PowerShell 中进入仓库项目根目录（包含 `pyproject.toml` 的目录），启用虚拟环境并启动桌宠：

```powershell
Set-Location "C:\path\to\vox-cli-main"
.\.venv\Scripts\Activate.ps1
vox-pet
```

如果不想激活虚拟环境，可以直接运行安装在虚拟环境里的启动器：

```powershell
.\.venv\Scripts\vox-pet.exe
```

首次启动时，桌宠会出现在桌面上，并在通知区域创建图标。将鼠标移到桌宠上可显示快捷工具栏；右键桌宠或通知区域图标可以打开菜单。若桌宠被移出屏幕，可在菜单中选择“重置桌宠位置”；选择“退出”可关闭程序。

macOS / Linux 在激活虚拟环境后运行：

```bash
vox-pet
```

也可以用模块方式启动 CLI 或 GUI：

```bash
python -m voxcli
python -m voxcli.gui
```

### 配置桌宠使用的模型

桌宠默认跟随 CLI 的全局模型配置。可以先在终端运行 `vox-code init`，选择提供商并填写模型信息，然后启动桌宠。

如果希望桌宠使用独立于 CLI 的模型：

1. 启动 `vox-pet`，右键桌宠并选择“模型设置”。
2. 在“模型来源”中选择“独立配置”。
3. 对 GLM、DeepSeek 等 OpenAI 兼容服务，选择“OpenAI Compatible”，填写服务地址、API Key 和模型名。例如 DeepSeek 可填写：

   | 字段 | 示例 |
   | --- | --- |
   | Base URL | `https://api.deepseek.com/chat/completions` |
   | API Key | 你在服务商处创建的密钥 |
   | Model | `deepseek-chat` |

   Base URL 可以填写完整的 `/chat/completions` 地址，也可以填写根地址或 `/v1` 地址；程序会补全请求路径。
4. 点击“测试连接”。连接成功后点击“保存并应用”。

独立 GUI 配置保存在用户配置目录的 `gui-model.json`，不会写入项目目录，也不会更改 CLI 模型。要改回共享配置，在“模型设置”中选择“跟随全局”并保存。API Key 会作为该配置的一部分保存在本机，请勿把配置文件提交到版本库或分享给他人。

### 在 UI 中聊天

1. 点击桌宠或从菜单中选择“打开聊天”。
2. 在输入框中输入内容，按 Enter 或点击发送按钮提交。
3. 上传图片时点击输入框旁的“+”按钮选择 PNG、JPG、JPEG 或 WebP 图片；也可以把图片拖进聊天窗口。发送前可以移除附件或调整附件顺序。
4. 等待桌宠生成回复。图片理解取决于所选模型和服务是否支持视觉输入。

从菜单打开“快捷命令”可以使用内置的帮助、模式切换、展示风格、记忆状态和清空对话等快捷操作。右键菜单还可打开“宠物管理”和“性格设置”，切换桌宠、皮肤、语言、运行模式和回答风格。

桌宠界面的模型设置和 CLI 配置相互独立；切换 GUI 模型不会改变 CLI 正在使用的模型。网络模型需要可用的 API Key 和网络连接，本地 Ollama 需要服务正在运行。

## CLI 命令

在 `vox-code` 交互会话中输入：

| 命令 | 用途 |
| --- | --- |
| `/help` | 显示可用命令 |
| `/model <预设或提供商[:模型]>` | 切换模型，例如 `/model deepseek:deepseek-chat` |
| `/team` | 在 single、plan 和 team 模式间切换 |
| `/plan` | 查看 Plan-and-Execute 模式说明 |
| `/style work\|pet` | 切换回答展示风格 |
| `/hitl auto\|always\|never` | 设置工具操作的人工审批策略 |
| `/policy`、`/audit` | 查看安全策略和最近的审计记录 |
| `/index`、`/search <关键词>` | 索引当前项目并搜索代码 |
| `/memory`、`/save [--global]` | 查看记忆状态，或保存长期记忆 |
| `/context`、`/clear` | 查看上下文统计，或清空当前对话 |
| `/export [文件名]` | 将当前对话导出为 Markdown |
| `/init`、`/exit` | 初始化模型配置，或退出会话 |

CLI 启动后会以启动时所在目录作为项目目录。文件工具将路径限制在该目录内；写文件、执行命令和创建项目等操作默认需要审批。`auto` 仅对这些操作请求审批，`always` 对所有工具调用请求审批，`never` 跳过人工确认，但安全策略仍会生效。工具执行和拒绝记录可通过 `/audit` 查看。

## 项目结构

```text
voxcli/
├── agent/       # Agent、任务规划与多 Agent 协作
├── cli/         # 命令行入口与交互命令
├── gui/         # PySide6 桌宠界面
├── hitl/        # 工具调用审批
├── llm/         # 模型客户端与提供商适配
├── memory/      # 短期和长期记忆
├── plan/        # 执行计划与任务状态
├── policy/      # 路径、命令和审计策略
├── rag/         # 代码索引、检索与嵌入
├── tool/        # 文件、命令、代码和网页工具
└── web/         # 搜索提供商、网页抓取与正文提取
```

## 开发

项目依赖和可选 GUI 依赖定义在 [pyproject.toml](pyproject.toml)；`requirements.txt` 提供包含 GUI 及辅助工具的便捷安装入口。运行 CLI 时请在希望作为工作目录的项目中启动 `vox-code`。
