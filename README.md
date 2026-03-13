# 本地文件管理分类与摘要工具

这是一个面向普通用户的 Windows 本地 Python 命令行工具。它会扫描常用文件夹中的文档文件，调用 LLM API 做智能分类，并在你需要时再生成摘要，避免不必要的费用。

现在项目也提供桌面图形界面，普通用户可以直接点击按钮完成扫描、摘要和查看报告。

如果要给 Windows 普通用户使用，项目也提供了 `.exe` 打包方案，可直接打成双击运行的桌面程序。

## 功能说明

- 默认扫描 `桌面`、`文档`、`下载` 三个目录
- 支持在 `config.yaml` 里增加额外扫描目录
- 只处理常见文档类型：PDF、Word、Excel、PPT、TXT、Markdown、CSV
- 自动跳过隐藏文件、临时文件、空文件
- 使用 SQLite 缓存已处理记录，未变化文件不会重复调用模型
- 分类完成后生成 `report.html` 和 `report.json`
- 支持按分类、按单文件、或全部文件生成摘要

## 安装步骤

### 1. 安装 Python

请先安装 Python 3.11 或更高版本。

Windows 上可以在命令提示符输入：

```bash
python --version
```

如果能看到版本号，就说明已安装。

### 2. 安装依赖

在项目目录打开终端后运行：

```bash
pip install -r requirements.txt
```

## 配置方法

编辑项目中的 `config.yaml`。

示例：

```yaml
llm:
  provider: "openai"
  api_key: "sk-xxx"
  model: "gpt-4o-mini"
  summary_model: "gpt-4o-mini"
  base_url: ""

scan:
  default_paths:
    desktop: true
    documents: true
    downloads: true
  paths:
    - "D:/工作文件"
    - "E:/资料"
  exclude_patterns:
    - "node_modules"
    - ".git"
    - "__pycache__"
    - "AppData"

batch_size: 30
classification_workers: 2
summary_workers: 4
```

说明：

- `provider` 支持 `openai` 和 `anthropic`
- `api_key` 也可以不写在配置里，改用环境变量 `LLM_API_KEY`
- `model` 用于分类
- `summary_model` 用于摘要
- `default_paths` 控制是否扫描默认的 `Desktop`、`Documents`、`Downloads`
- `paths` 是额外扫描目录，会和勾选启用的默认目录一起扫描
- `batch_size` 建议从 10-30 起步，路径很长或使用兼容后端时更稳妥
- `classification_workers` 控制分类并发请求数（1-4），默认 2
- `summary_workers` 控制摘要并发请求数（1-8），默认 4

## 使用方法

### 启动图形界面

推荐普通用户直接运行：

```bash
python gui.py
```

或者：

```bash
python main.py gui
```

图形界面支持：

- 填写和保存 API 配置
- 添加额外扫描目录
- 一键扫描并分类
- 一键生成摘要
- 直接打开 HTML 报告
- 在窗口中查看运行日志

### Windows 打包为 EXE

在 Windows 上进入项目目录后，直接双击运行：

```bat
build_windows.bat
```

脚本会自动：

- 创建 `.venv`
- 安装运行依赖和 `pyinstaller`
- 按 `file-organizer.spec` 打包
- 在 `dist/FileOrganizer.exe` 生成可双击运行的程序

如果你不想在本地打包，也可以把分支推到 GitHub，使用仓库里的 [build-windows-exe.yml](/Users/yanglee/Desktop/file-organizer/.github/workflows/build-windows-exe.yml) 在 GitHub Actions 上构建 Windows EXE。

### 扫描并分类

```bash
python main.py scan
```

### 强制重新分类全部文件

```bash
python main.py scan --force
```

### 为某个分类生成摘要

```bash
python main.py summarize --category "财务/税务"
```

### 为单个文件生成摘要

```bash
python main.py summarize --file "C:/Users/你的用户名/Documents/2024年报.pdf"
```

### 为所有已分类文件生成摘要

```bash
python main.py summarize --all
```

### 单独刷新报告

```bash
python main.py report
```

### 查看缓存统计

```bash
python main.py stats
```

## 输出文件说明

- `cache.db`：本地缓存数据库
- `report.html`：可直接双击打开的图形化报告
- `report.json`：给程序或脚本读取的结构化结果
- `error.log`：错误日志，单个文件失败时会记在这里，不会中断整体流程

## 摘要支持说明

支持提取内容的格式：

- `.pdf`
- `.docx`
- `.xlsx`
- `.pptx`
- `.txt`
- `.md`
- `.csv`

旧版 Office 文件 `.doc`、`.xls`、`.ppt` 可以参与分类，但暂不支持正文提取摘要。如果需要摘要，建议先另存为新版格式。

## 适合谁用

如果你只想“扫一遍电脑里的文档，自动分个类，再挑重要文件看摘要”，这个工具就是为这种场景设计的。
