# XHSContentFetcher

一个面向个人知识库工作流的小红书内容采集与笔记生成工具。  
输入一条小红书分享链接（图文或视频），自动输出一份可直接放入 Obsidian 的 Markdown 学习笔记，并同步保存图片、视频、关键帧等素材。

---

## 1. 项目目标

本项目解决以下问题：

1. 将小红书内容从“消费”转为“可复用知识”。
2. 自动抓取正文、评论、图片/视频素材，减少手工整理成本。
3. 通过 OCR + DeepSeek 生成结构化学习笔记，方便长期沉淀。
4. 产物路径与格式兼容 Obsidian，可直接纳入个人知识库。

---

## 2. 功能清单

### 2.1 内容抓取

1. 支持图文链接与视频链接（含 `explore`、`discovery/item` 等形式）。
2. 抓取帖子详情（标题、正文、标签、互动数据等）。
3. 抓取评论：
   - 顶层评论分页采集
   - 高赞评论筛选
   - 高回复评论筛选
   - 高回复子评论采集（失败自动跳过，不中断主流程）

### 2.2 媒体处理

1. 图片下载（自动识别扩展名，避免 `.bin` 文件）。
2. 视频下载（优先高质量流，支持备用链接回退）。
3. 视频分辨率控制：
   - 1080 以内保留原规格
   - 超过 1080 自动降采样到 1080
4. 视频关键帧抽取（默认 8 帧，可配置）。

### 2.3 OCR 与总结

1. 支持 PaddleOCR（中文识别）。
2. OCR 文本进入总结输入上下文。
3. DeepSeek 使用 OpenAI 兼容接口，启用思考模式：
   - `reasoning_effort="max"`
   - `extra_body={"thinking": {"type": "enabled"}}`

### 2.4 模板化笔记输出

1. 生成时优先读取根目录模板文件：
   - `Tempate.md`（兼容 `Template.md` / `template.md`）
2. 强制按模板章节输出。
3. 自动把模板中的资源占位（如 `assets.images[*].path`）替换为真实相对路径。
4. 支持“图文并茂”内联渲染（图片跟随解释段落）。

### 2.5 Obsidian 对接

1. 可直接输出到指定 Vault。
2. 可选自动调用 Obsidian CLI 打开生成笔记（`--open-obsidian`）。
3. 已在本机 Obsidian CLI（最新版）实测通过。

---

## 3. 环境要求

### 3.1 必需

1. Python 3.10+
2. ffmpeg / ffprobe（加入 PATH）
3. 可用小红书 Cookie（至少包含 `a1`）

### 3.2 可选（建议）

1. DeepSeek API Key（用于生成高质量学习笔记）
2. PaddleOCR + PaddlePaddle（用于 OCR）
3. Obsidian 桌面端 + CLI（用于自动打开笔记）

---

## 4. 安装

在项目根目录执行：

```bash
pip install -e .
```

如果要启用 OCR：

```bash
pip install paddleocr paddlepaddle
```

首次 OCR 会自动下载模型，耗时较长，属于正常现象。

---

## 5. 配置方式

### 5.1 保存 Cookie

```bash
xhs-fetch config set-cookie --cookie "a1=...; web_session=...; ..."
```

### 5.2 保存 DeepSeek Key

```bash
xhs-fetch config set-deepseek-key --api-key "sk-xxxx"
```

### 5.3 查看当前配置

```bash
xhs-fetch config show
```

---

## 6. 使用方式

### 6.1 标准全链路（抓取 + OCR + DeepSeek）

```bash
xhs-fetch run "https://www.xiaohongshu.com/explore/xxxx?xsec_token=...&xsec_source=..." \
  --deepseek-api-key "sk-xxxx" \
  --output-root output
```

### 6.2 输出到 Obsidian Vault 并自动打开

```bash
xhs-fetch run "https://www.xiaohongshu.com/discovery/item/xxxx?xsec_token=...&xsec_source=..." \
  --vault-dir "C:\\Users\\<用户名>\\Documents\\Obsidian Vault" \
  --open-obsidian
```

### 6.3 调试模式（跳过 OCR / 跳过 LLM）

```bash
xhs-fetch run "<分享链接>" --skip-ocr --skip-llm
```

---

## 7. 目录与产物结构

默认输出结构：

```text
<output_root>/
  <note_slug>/
    <note_slug>.md
    assets/
      images/
      video/
      frames/
```

当使用 `--vault-dir` 时，输出目录会变为：

```text
<vault_dir>/<notes_folder>/<note_slug>/...
```

---

## 8. 模板机制说明

生成时会在项目根目录查找模板文件，优先级如下：

1. `Tempate.md`
2. `Template.md`
3. `template.md`

模板内容会原样作为章节骨架，模型在该骨架上填充内容。  
如果模板中包含：

1. `assets.images[*].path`：会替换为真实图片路径。
2. `assets.video_frames[*].path`：会替换为关键帧路径。
3. “缩放50%”描述：会输出为 `<img src="..." width="50%" />`。

---

## 9. 常见问题与排错

### Q1：报错“未提供 Cookie / 缺少 a1”

请重新登录小红书网页端，复制完整 Cookie 字符串，并确认包含 `a1=...`。

### Q2：`discovery/item` 链接解析失败

已在代码中修复该路径的 note_id 解析逻辑；请确保链接包含有效 `xsec_token` 与 `xsec_source`。

### Q3：OCR 很慢

首次运行会下载 OCR 模型；后续会复用本地缓存，速度会明显提升。

### Q4：Obsidian 无法自动打开

请确认：

1. 本机可执行 `obsidian --help`
2. `--vault-dir` 路径正确
3. 笔记文件位于已注册的 Vault 路径内

---

## 10. 合规与声明

1. 本项目仅用于个人学习研究与知识管理。
2. 请遵守目标平台的服务条款、robots 规则与当地法律法规。
3. 请勿将抓取内容用于侵权、违法或未授权商用场景。

---

## 11. 当前状态

本项目已完成：

1. 图文与视频全链路跑通。
2. OCR 与 DeepSeek 生成流程跑通。
3. Obsidian CLI 对接实测可用。
4. 模板化输出（根目录模板）可用。
