# Vox Code v2.0.0 - Web-aware Tool CLI

Python 版智能编程 CLI 工具，支持多模型、多 Agent 协作、代码检索、联网搜索等功能。

## 安装

```bash
# 1. 克隆项目
git clone <repo-url>
cd py-cli

# 2. 安装依赖
pip install httpx python-dotenv pyyaml beautifulsoup4 lxml
```

## 配置

创建 `~/.vox-code/config.json` 或使用环境变量：

### GLM (智谱)
```bash
export GLM_API_KEY=your_api_key
export GLM_MODEL=glm-4-plus
```

### DeepSeek
```bash
export DEEPSEEK_API_KEY=your_api_key
export DEEPSEEK_MODEL=deepseek-chat
```

### Ollama (本地)
```bash
export OLLAMA_MODEL=qwen2.5:14b
export OLLAMA_BASE_URL=http://localhost:11434
```

### 联网搜索
```bash
export SEARCH_PROVIDER=serpapi   # serpapi, zhipu, searxng
export SERPAPI_API_KEY=your_key
```

### 调试模式
```bash
export VOX_CODE_DEBUG=true
```

## 运行

```bash
# 方式一：直接运行
python -m paicli

# 方式二：安装后运行
pip install -e .
vox-code
```
## CLI 命令

- `/model <provider>[:<model>]` - 切换模型
- `/plan` - 查看执行计划
- `/team` - 切换单 Agent / Plan-and-Execute / 多 Agent 团队模式
- `/hitl <auto/always/never>` - 设置审批模式
- `/policy` - 查看安全策略
- `/audit` - 查看审计日志
- `/index` - 索引项目代码
- `/search <query>` - 搜索代码库
- `/memory` - 查看记忆状态
- `/clear` - 清空对话
- `/context` - 查看上下文统计
- `/exit` - 退出


