# 小红书笔记爬虫 (Xiaohongshu Note Crawler)

基于 [DrissionPage](https://github.com/g1879/DrissionPage) 的小红书笔记爬虫工具，通过模拟真实浏览器操作来搜索、提取和导出小红书笔记数据。

## 功能特性

- **关键词搜索** — 支持多个关键词批量爬取，自动滚动加载更多结果
- **搜索排序** — 支持综合排序、最热排序、最新排序
- **笔记详情提取** — 从 `window.__INITIAL_STATE__` 提取结构化数据，包括：
  - 标题、正文内容、作者信息
  - 点赞数、评论数、收藏数、分享数
  - 发布时间、图片链接、标签
  - 笔记类型（图文/视频）
  - 完整的笔记链接（含 `xsec_token`）
- **多条件过滤** — 按笔记类型（图文/视频）、最低点赞数、发布时间范围过滤
- **增量爬取** — 基于 SQLite 的去重机制，避免重复爬取已采集的笔记
- **多格式导出** — 支持 Excel、CSV、JSON、Google Sheets
- **图片下载** — 可选下载笔记配图到本地
- **登录持久化** — 浏览器固定端口运行，扫码登录一次后会话长期有效
- **定时任务** — 支持 Cron 表达式定时执行爬取任务
- **反爬对策** — 随机延迟、模拟人工滚动、自动关闭登录弹窗

## 项目结构

```
xiaohongshu_crawler/
├── main.py                  # 主入口，CLI 和流程编排
├── config.yaml              # 配置文件
├── requirements.txt         # Python 依赖
├── crawler/
│   ├── browser.py           # 浏览器管理（启动、连接、登录）
│   ├── searcher.py          # 搜索结果页爬取
│   ├── extractor.py         # 笔记详情页数据提取
│   └── image_downloader.py  # 图片下载器
├── storage/
│   ├── dedup.py             # SQLite 去重 + 日期过滤
│   └── exporter.py          # 多格式数据导出（含 Google Sheets）
├── scheduler/
│   └── task_scheduler.py    # 定时任务调度
├── utils/
│   └── helpers.py           # 工具函数（URL 编码、时间解析等）
└── data/
    ├── exports/             # 导出文件存放目录
    ├── images/              # 下载的图片
    ├── browser_data/        # 浏览器用户数据（保持登录状态）
    └── crawled.db           # 去重数据库
```

## 安装

```bash
cd scripts/xiaohongshu_crawler
pip install -r requirements.txt
```

## 快速开始

### 1. 首次登录（扫码）

首次使用需要扫码登录小红书，登录状态会持久保存：

```bash
python main.py --login
```

运行后会打开 Chromium 浏览器并显示小红书首页，使用手机 App 扫码登录即可。登录完成后浏览器会保持打开，后续爬取无需再次登录。

### 2. 执行爬取

```bash
# 使用配置文件中的默认关键词
python main.py

# 指定关键词
python main.py --keyword "新加坡求职"

# 指定关键词 + 限制数量
python main.py --keyword "Python" --max-notes 50 --scroll-times 10

# 开启详细日志
python main.py --keyword "AI" -v
```

### 3. 关闭浏览器

爬取结束后浏览器默认保持运行（用于保持登录），如需关闭：

```bash
python main.py --close-browser
```

## 命令行参数

| 参数 | 缩写 | 类型 | 说明 |
|------|------|------|------|
| `--config` | `-c` | string | 指定 YAML 配置文件路径，默认使用项目根目录的 `config.yaml` |
| `--keyword` | `-k` | string | 搜索关键词，覆盖配置文件中的 `keywords` |
| `--max-notes` | `-n` | int | 每个关键词最多爬取的笔记数量 |
| `--scroll-times` | `-s` | int | 搜索结果页向下滚动的次数 |
| `--sort` | — | string | 搜索排序方式：`general`（综合）、`popularity`（最热）、`time`（最新） |
| `--min-likes` | — | int | 最低点赞数阈值，低于此值的笔记会被过滤 |
| `--login` | — | flag | 打开浏览器进行扫码登录 |
| `--schedule` | — | flag | 以定时任务模式运行 |
| `--close-browser` | — | flag | 关闭后台运行的浏览器进程 |
| `--verbose` | `-v` | flag | 开启 DEBUG 级别日志 |

> 命令行参数优先级高于配置文件，未指定的参数从 `config.yaml` 读取。

## 配置文件说明 (`config.yaml`)

### search — 搜索配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `keywords` | list | `["Python", "AI"]` | 搜索关键词列表，每个关键词独立执行一轮完整爬取 |
| `max_notes` | int | `100` | 每个关键词最多采集的笔记数 |
| `scroll_times` | int | `20` | 搜索结果页向下滚动次数，滚动越多加载的笔记越多 |
| `sort_by` | string | `"popularity"` | 搜索排序：`general`（综合）、`popularity`（最热）、`time`（最新） |

### filter — 过滤配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `note_type` | string | `"normal"` | 笔记类型过滤：`normal`（图文）、`video`（视频）、留空则不过滤 |
| `min_likes` | int | `10` | 最低点赞数，低于该值的笔记会被丢弃 |
| `date_range.enabled` | bool | `true` | 是否启用时间过滤 |
| `date_range.recent_days` | int | `180` | 只保留最近 N 天内发布的笔记 |
| `date_range.start_date` | string | `null` | 绝对起始日期，格式 `"2025-08-01"`（设置 `recent_days` 时被忽略） |
| `date_range.end_date` | string | `null` | 绝对结束日期，格式 `"2026-02-07"`（设置 `recent_days` 时被忽略） |

### output — 输出配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `formats` | list | `["excel","csv","json","google_sheets"]` | 导出格式，可任意组合 |
| `download_images` | bool | `false` | 是否将笔记图片下载到本地 |
| `output_dir` | string | `"./data/exports"` | 导出文件保存目录 |
| `image_dir` | string | `"./data/images"` | 图片保存目录 |

### google_sheets — Google Sheets 导出配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `credentials_file` | string | — | Google 服务账号 JSON 密钥文件路径 |
| `spreadsheet_id` | string | `""` | 已有 Google Sheet 的 ID（留空则自动创建新表） |
| `spreadsheet_name` | string | `"小红书爬虫数据"` | 新建表格的名称（仅当 `spreadsheet_id` 为空时生效） |
| `share_with` | string/list | `""` | 共享邮箱，支持逗号分隔多个邮箱或 YAML 列表格式 |

#### Google Sheets 配置步骤

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 创建项目
2. 启用 **Google Sheets API** 和 **Google Drive API**
3. 创建服务账号并下载 JSON 密钥文件，放入 `credentials/` 目录
4. 在 `config.yaml` 中填写 `credentials_file` 路径和 `share_with` 邮箱
5. **推荐**：手动创建一个 Google Sheet，将其共享给服务账号邮箱（JSON 中的 `client_email`），然后将 Sheet ID 填入 `spreadsheet_id`，避免每次创建新文件占用存储配额

### scheduler — 定时任务配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `false` | 是否启用定时任务 |
| `cron` | string | `"0 8 * * *"` | Cron 表达式，默认每天早上 8 点执行 |

### behavior — 爬虫行为配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `min_delay` | float | `0.5` | 动作之间（如滚动）的最小随机延迟（秒） |
| `max_delay` | float | `2.0` | 动作之间的最大随机延迟（秒） |
| `detail_page_delay` | float | `20.0` | 进入笔记详情页后的等待时间（秒），实际等待 = 此值 + random(min_delay, max_delay) |
| `login_wait` | int | `20` | 扫码登录等待时间（秒） |

## 导出字段

每条笔记包含以下字段：

| 字段 | 说明 |
|------|------|
| Note ID | 笔记唯一 ID |
| Note Type | 笔记类型：`normal`（图文）/ `video`（视频） |
| Title | 标题 |
| Content | 正文内容 |
| Author | 作者昵称 |
| Author ID | 作者用户 ID |
| Likes | 点赞数 |
| Comments | 评论数 |
| Collects | 收藏数 |
| Shares | 分享数 |
| Publish Time | 发布时间 |
| Note Link | 笔记链接（含 xsec_token，可直接打开） |
| Author Link | 作者主页链接 |
| Image URLs | 图片链接（逗号分隔） |
| Tags | 标签（逗号分隔） |

## 使用示例

```bash
# 爬取"新加坡求职"相关的最热图文笔记，最多 30 篇，点赞 >= 50
python main.py -k "新加坡求职" -n 30 --sort popularity --min-likes 50

# 爬取"Python"笔记，只要最近 90 天的，导出到 Google Sheets
python main.py -k "Python" --recent-days 90

# 使用定时任务模式，按 config.yaml 中的 cron 表达式定期运行
python main.py --schedule

# 详细日志模式，方便排查问题
python main.py -k "AI" -n 10 -v
```

## 注意事项

- 首次运行必须先执行 `python main.py --login` 扫码登录
- 浏览器运行在固定端口 9515，保持后台运行以维持登录会话
- 爬取速度受 `detail_page_delay` 影响，建议不要设置过低以避免触发反爬
- Google Sheets 导出建议使用固定的 `spreadsheet_id`，避免频繁创建新表格占满存储配额
- 导出的笔记默认按评论数降序排列
