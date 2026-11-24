# LucyValentine-PIM-001

[English](README.md) | 中文

灵感来自 **Lucy ~The Eternity She Wished For~** 的桌面陪伴程序：  
**中文输入 → 日文台词 + 中文释义 → 表情立绘 + 可选本地 TTS**。

> 非官方粉丝项目，与原作权利方无关。  
> 代码 MIT。立绘 / 游戏音频 / 训练权重需**自行准备** — 见 [NOTICE](NOTICE)。

## 一键初始化

在仓库根目录（Windows）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_lucy.ps1
# 设置云端 API Key（示例）：
$env:QIANWEN_API_KEY = "sk-..."
python scripts\run_desktop_lucy.py
```

初始化脚本会：

- 创建 `output/`、`sessions/`、`images_hq/`、`voice_models/`
- 若无 `settings.yaml`，从 `settings.example.yaml` 复制一份
- 把 `project_root` / TTS worker 路径指到本仓库
- `pip install -r companion/requirements.txt`
- 检查推理权重是否存在（**不包含任何训练步骤**）

## 语音（仅推理）

本仓库只说明**现成权重如何加载**，不含训练教程。

按 [`voice_models/README.md`](voice_models/README.md) 放置 checkpoint，再在 `settings.yaml` 里打开语音。

## 立绘（自备 + 可选高清放大）

游戏立绘**不在**本仓库中。把你有权使用的 `Images-l*.png` 放到 `images/`，然后：

- 将 `paths.images_dir` 指到 `images/`，或
- 用 `scripts/upscale_lucy_sprites.ps1` 做 Real-ESRGAN 放大 → 输出到 `images_hq/`

完整步骤见 [`images_hq/README.md`](images_hq/README.md)（可对照下文摘要）。

### 立绘准备摘要

1. 合法持有原作或其它你有权使用的素材。
2. 将立绘 PNG 放到仓库旁的 `images/`（文件名形如 `Images-l001.png`）。
3. 从 [Real-ESRGAN Releases](https://github.com/xinntao/Real-ESRGAN/releases) 下载 Windows ncnn-vulkan 版，解压到：

```text
<repo>/tools/realesrgan-ncnn-vulkan/realesrgan-ncnn-vulkan.exe
```

4. 安装依赖并放大：

```powershell
pip install pillow
$env:LUCY_ROOT = (Get-Location).Path
powershell -ExecutionPolicy Bypass -File scripts\upscale_lucy_sprites.ps1 -Gpus "0"
```

5. 桌宠设置里图片目录保持 `images_hq`（`setup_lucy.ps1` 默认已写好）。

未经授权请勿再分发游戏立绘或放大结果；本项目只提供放大**工具脚本**。

## 大模型（LLM）

密钥优先放环境变量（`llm.api_key_env`）。不要提交 `settings.yaml`。

| 模式 | 说明 |
|------|------|
| Ollama | `base_url: http://127.0.0.1:11434/v1`，`api_key: ollama` |
| 云端 | 设置 `$env:QIANWEN_API_KEY`（或你的服务商变量） |

## 目录结构

| 路径 | 作用 |
|------|------|
| `companion/` | Agent、桌宠、配置 |
| `scripts/setup_lucy.ps1` | 一键路径初始化 |
| `scripts/companion_tts_worker.py` | GPT-SoVITS 推理 worker |
| `voice_models/` | 推理权重放置说明（仅文档） |
| `images_hq/` | 放大后的表情图（PNG 仅本地；见该目录 README） |
| `scripts/upscale_lucy_sprites.ps1` | Real-ESRGAN RGBA 放大脚本 |

体积较大的目录（`GPT-SoVITS-*`、`RVC`、立绘 PNG、`voice`、`dataset`、`output`）默认不进 git。

## 桌宠操作

右键：聊天记录（有保存 wav 时可 ▶ 重播）、信息、设置、退出。  
设置 → 声音 → 播放方式：**整句**（默认）或 **一句一句**。

## 许可

MIT — [LICENSE](LICENSE)、[NOTICE](NOTICE)、[SECURITY](SECURITY.md)。
