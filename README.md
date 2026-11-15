# Yuer 搜索

自建元搜索引擎：**传统结果列表 · 0 数据收集 · 0 广告 · 每用户自定义权重 · 多引擎聚合**。
纯 Vercel 免费部署（不绑卡），面向 <10 人使用，为大陆直连访问做了专门优化。

> 2026 年背景：Bing Search API 已退役、Brave API 免费层取消且注册绑卡、Google CSE JSON API
> 停止新客户（2027-01-01 停服）。本项目全部结果源走「官方免费 API + 灰色抓取」组合，不依赖任何需要绑卡的服务。

## 架构

```
浏览器 ── s.yuer6327.top（Vercel 边缘 CDN + 函数区域 hkg1）
  │
  ├─ 聚合模式（默认，国内直连可用）
  │    GET /api/search?q=…  → Python Function 并行抓取：
  │      DuckDuckGo lite/html（curl_cffi TLS 伪装，lite 失败自动换 html）
  │      Bing www.bing.com/search（mkt=zh-CN + 相关性护栏，广告剔除）
  │      Marginalia 官方免费 API（英文独立索引，中文查询自动跳过）
  │      Brave 抓取（可选，默认关闭，需 BRAVE_ENABLED=1）
  │    → 基线屏蔽域名以 -site: 下推进查询（屏蔽不止第一页）
  │    → 归一化 per-engine JSON，边缘缓存 s-maxage=1800 + SWR 24h
  │    → 前端融合排序：引擎权重 × 域名调整 × 位置衰减，URL 去重，多源验证标记
  │
  ├─ Bing 单引擎模式（`/search?q=…&mode=bing`，API 等价 `engines=bing`）
  │    只请求 Bing（最稳最快的中文主力源），不聚合其他引擎；浏览器搜索关键词推荐用这个
  │
  └─ Google 模式（能直连 Google 的用户）
       CSE embed 控件（免费、无每日额度限制，不在 JSON API 停服范围）
       进入前探活 cse.google.com，不可达自动提示切回聚合模式
       渲染回调剥跟踪属性 + 按用户 localStorage 规则隐藏被屏蔽站点
```

## 需求对照

| 需求 | 实现 |
|---|---|
| 纯 Vercel 免费部署、不绑卡 | 静态前端 + 1 个 Python Function，Hobby 计划零成本 |
| 0 数据收集 | 服务端不记录查询、无 Cookie、无统计；个人偏好仅存浏览器 localStorage |
| 0 广告 | UI 无广告；抓取层剔除上游广告位（Bing `b_ad` 等） |
| 每用户自定义类别/站点权重 | 设置面板：域名规则 block/raise/lower（≤300 条）+ 类别 Lens（≤20 个）+ 引擎开关，全部本地 |
| 多引擎聚合 | DDG + Bing + Marginalia（+ 可选 Brave）并行抓取、权重融合、URL 去重 |
| 快 | **两段式渐进加载**（第一批结果 ~0.5s 即渲染，其余引擎后台并行、完成后一键前端重排，不重发请求）、边缘缓存按查询词 30 分钟（重复查询零回源）、函数区域 hkg1、Vite 产物 ~47KB gzip |
| 稳 | 单引擎失败不影响其他引擎（per-engine 状态条）；9s 编排硬上限；Marginalia 官方 API 作合规兜底 |
| 准 | Bing `mkt=zh-CN` 中文主力 + 相关性护栏防"静默垃圾结果"；Google 模式补 Google 质量 |

## 本地开发

前置：Node 18+、Python 3.11+。

```bash
# 后端（终端 1）：Vite 已配置把 /api 代理到 8787
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # Windows；Linux/macOS 为 .venv/bin/pip
.venv/Scripts/python -m uvicorn api.index:app --port 8787

# 前端（终端 2）
npm install
npm run dev          # http://localhost:5173

# 测试
.venv/Scripts/python tests/run_tests.py          # 离线 fixture 测试
.venv/Scripts/python tests/run_tests.py --live   # 追加低频实测（勿频繁执行）
```

> 本地 API 启动时会自动读取仓库根目录 `.env`（不会上传）；Vercel 则使用项目环境变量，不读取 `.env`。
>
> 注意：本地从大陆直连时 DuckDuckGo 大概率超时（GFW），属预期——部署到 Vercel（境外出口）后正常。

## 部署到 Vercel

### 1. 推送仓库并导入

```bash
gh repo create yuer-search --public --source=. --remote=origin --push   # 或 private
```

在 [vercel.com](https://vercel.com) → Add New → Project → 选该仓库导入，Framework 自动识别 Vite，直接 Deploy。
Vercel 会自动构建前端（`npm run build` → `dist/`）并把 `api/` 下的入口（index/search/health，共享 `_app.py`
应用主体）部署为 Python Function。注意：`api/` 目录按「文件名 = 路由」映射——`/api/search` 由 `api/search.py` 提供。

### 2. 函数区域切到香港（国内延迟关键）

Project → Settings → Functions → Functions Region：
⚠️ Hobby 计划不支持多区域——先切到 North America 分组、**取消 iad1 的勾**，再单选 **hkg1 (Hong Kong)**。
（仓库里的 `vercel.json` 已写 `"regions": ["hkg1"]`，Dashboard 显示一致即可。）

### 3. 绑定自定义域名（国内可达性关键）

`*.vercel.app` 在大陆被全量 DNS 污染，必须用自定义域名。
在你域名的 DNS 处（Cloudflare/DNSPod 均可，**保持仅 DNS，不要开橙色云代理**）添加：

```
s.yuer6327.top   CNAME   cname-china.vercel-dns.com
```

`cname-china.vercel-dns.com` 是 Vercel 官方维护的中国优化线路（比 `cname.vercel-dns.com` 更适合国内）。
Vercel → Settings → Domains → 添加 `s.yuer6327.top`，等证书签发。
若个别省份仍慢，可用 [enhanced-FaaS-in-China](https://github.com/xingpingcn/enhanced-FaaS-in-China) 的优选 CNAME/IP。

### 4. 环境变量（可选）

| 变量 | 作用 |
|---|---|
| `GOOGLE_CSE_CX` | Google 模式的 CSE 引擎 ID——运行时经 `/api/config` 注入前端（Vercel 环境变量名不允许 `VITE_` 前缀；旧名 `VITE_GOOGLE_CSE_CX` 仍兼容）；不设则前端隐藏 Google 模式入口 |
| `BRAVE_ENABLED` | 设 `1` 启用 Brave 抓取引擎（默认关闭；反爬风险自负） |

### 5. 验证缓存与预热

```bash
curl -sI "https://s.yuer6327.top/" | grep -i x-vercel-cache     # 第二次访问应 HIT
curl -sI "https://s.yuer6327.top/api/search?q=test" | grep -iE "cache-control|x-vercel-cache"
```

仓库自带 [缓存预热工作流](.github/workflows/cache-hit-check.yml)：push 到 main 后自动预热边缘缓存并统计
`X-Vercel-Cache` 命中率（目标 ≥95%），结果写入 Actions Summary。用 [itdog.cn](https://www.itdog.cn) 三网拨测确认全国可达。

## 环境变量 / API Key 统一清单（2026-11-15）

全部免费、无需绑卡。**不填的 key 对应引擎自动跳过**（不报错、不进状态条），填入 Vercel 环境变量后 Redeploy 即自动启用。

| 环境变量 | 服务 / 注册地 | 免费额度 | 引擎 | 说明 |
|---|---|---|---|---|
| —（无需） | — | — | Bing / B站 / SearXNG / Marginalia | 开箱即用，零配置 |
| `TAVILY_API_KEY` | [tavily.com](https://tavily.com) | **1000 credits/月**，每月重置 | Tavily | 官方明示不绑卡；长期稳定兜底源 |
| `SERPER_API_KEY` | [serper.dev](https://serper.dev) | **2500 次**（一次性） | Serper(Google) | 官方明示不绑卡；Google 中文质量基准 |
| `EXA_API_KEY` | [exa.ai](https://exa.ai) | $10/月（每月重置）≈2500 次 | Exa | 官方文档不绑卡；语义搜索，无字面相关性护栏 |
| `FIRECRAWL_API_KEY` | [firecrawl.dev](https://firecrawl.dev) | 1000 credits/月 ≈500 次搜索 | Firecrawl | 搜索+正文抓取一体 |
| `BRIGHTDATA_API_TOKEN`（+ 可选 `BRIGHTDATA_ZONE`，默认 `serp`） | [brightdata.com](https://brightdata.com)（SERP API：控制台 Settings 生成账户 API Token） | **5000 credits/月**，官方明示不绑卡（注册或有 KYC 摩擦） | BrightData(百度) | **免费方案里唯一官方级百度结果**；调用 `api.brightdata.com/request`，zone 建议经 SERP API 产品页激活 |
| `SCRAPERAPI_KEY` | [scraperapi.com](https://scraperapi.com) | 1000 credits/月 | ScraperAPI(百度) | 作为百度 tn=json 的传输通道（代理过验证码） |
| `HASDATA_KEY` | [hasdata.com](https://hasdata.com) | 1000 credits/月 | HasData(百度) | 同上，第二个百度传输通道 |
| `SEARXNG_INSTANCES` | —（可选） | — | SearXNG | 逗号分隔的实例清单；不填用内置默认 8 个，熔断轮换自动跳过坏实例。⚠️ **2026-11-15 全量实测：searx.space 官方清单 83 个公共实例从数据中心出口 0 个开放 JSON**（41 限速 / 12 回 HTML / 12 不可达 / 9 显式 403 / 其余 404/418/502）——白嫖公共实例路线已证伪；本引擎保留作探针与自建 SearXNG（如 Koyeb）的接入点，`/api/debug/searxng?instances=...` 可随时复测 |
| `BRAVE_ENABLED` | —（已有） | — | Brave | 已设 `1`（引擎本身被挑战页拦，保留观察） |
| `GOOGLE_CSE_CX` | —（已配置） | — | Google 模式 | 已生效 |

## Google 模式配置

> ⚠️ **2026-11 实测更新**：Google 已对新引擎弃用「Search the entire web」（控制台显示
> "This feature is being deprecated and can no longer be enabled"，与 JSON API 停服同一轮产品收缩）。
> 因此 Google 模式的形态是「**精选站点池内的 Google 质量搜索**」（上限 50 个域名），而非全网搜索。
>
> ❌ **服务端中继 Google 已实测不可行**（Google 对云 IP 定向丢弃 element/v1 端点：预热/Cookie/Referer/
> 参数变体全部黑洞，对照路径 404 秒回，证据见 `/api/debug/cse`）。`google` 引擎（search_engines/cse.py）
> 默认关闭保留代码，换出口 IP（自建反代）后可重新打开；大陆直连用户请使用聚合模式。

1. 用你的 Google 账号在 [programmablesearchengine.google.com](https://programmablesearchengine.google.com) 免费创建搜索引擎：
   - 创建表单的 "Select sites or pages to search" 随便填一个占位（如 `www.google.com/*`），它不会生效；
   - Image search 关闭、SafeSearch 保持开启。
2. 创建后，在 **Sites to search**（Add sites to include 文本框）粘贴 [`config/cse-sites.txt`](config/cse-sites.txt)
   的内容（每行一条，~40 个主流开发站点，留有余量；语义 `*.example.com` = 含子域名的整个域名）。
3. 记下 **Search engine ID**（cx），设为 Vercel 环境变量 `GOOGLE_CSE_CX`，然后 Redeploy——前端经
   `/api/config` 运行时读取（cx 本身是公开值），设置后即出现 Google 模式入口。
4. "Add sites to exclude" 在白名单模式下基本冗余（屏蔽只在包含站点内生效）——白名单本身就是最强的屏蔽。
   `config/baseline.json` 的农场黑名单对聚合模式照常生效（-site: 下推 + 前端过滤）。
5. 行为说明：embed 控件免费且无每日额度限制（不在 2027 JSON API 停服范围）；前端探活
   `cse.google.com`，大陆直连用户进入 Google 模式时会看到降级提示并一键切回聚合模式；
   免费版 embed 的广告位由前端剔除（`googleMode.ts` 的 postProcess）。
   测试引擎本身可用公开 URL `https://cse.google.com/cse?cx=<你的cx>`（需能直连 Google）。

## 自定义

### 全局基线（部署者，`config/baseline.json`）

前后端共用的唯一来源：引擎权重与默认开关、域名 block/raise/lower、类别模板、`-site:` 下推数量。
改完重新部署即全局生效。默认基线继承 Luxirty Search 的内容农场名单（CSDN/阿里云开发者/豆丁等 22 条）
并提权 GitHub / StackOverflow / MDN / V2EX / 掘金 / 博客园 / SegmentFault。

### 每用户覆盖（浏览器设置面板）

右上角 ⚙ 打开：引擎开关、站点规则（支持 `*.example.com` 通配与 `/正则/`，后添加覆盖先添加）、
类别 Lens（include/exclude 域名 + 关键词过滤，随时切换生效）、导出/导入 JSON。
全部存浏览器 localStorage，永不上传；结果页每条右侧有「屏蔽此站点」一键按钮。

### 新增引擎

在 `search_engines/` 加一个模块，实现统一契约：

```python
def search(query, *, lang, page, baseline_block, timeout, deadline=None) -> dict:
    # 返回 {"name": "...", "status": "ok|degraded|skipped", "latency_ms": int,
    #        "results": [{"title","url","domain","snippet"}], "note": str?}
    # 硬失败抛 EngineError（消息不得含查询词）
```

在 `search_engines/__init__.py` 注册、`config/baseline.json` 加权重，前端无需改动（自动出现在状态条与设置面板）。

## 引擎风险与调参（诚实清单）

| 引擎 | 类型 | 风险 | 对策 |
|---|---|---|---|
| Bing | HTML 抓取 | 反爬烈度最低；风险是 class 混淆变更、zh 市场参数异常（社区有负面个例） | 相关性护栏自动丢弃静默垃圾；解析器多选择器兜底 |
| **B 站** | 公开 JSON 接口 | -412 风控（缺 buvid3 才触发）；接口随时可能收紧 | 伪造 buvid3 + Referer（searxng 同款）；英文查询自动跳过 |
| Marginalia | 官方免费 API | 限速严格、官方标记 deprecated；纯英文独立索引 | 仅作兜底源、中文查询自动跳过、失败静默降级 |
| Tavily | 官方 API | 免费 1000 次/月；中文偏英文语料（社区口碑） | 环境变量 TAVILY_API_KEY 配置后自动启用；未配置自动跳过 |
| Serper(Google) | 官方 API | 2500 次一次性额度 | 环境变量 SERPER_API_KEY 配置后自动启用；结果带逐条相关性校验 |
| DuckDuckGo | HTML 抓取 | **已实锤硬封锁**（假 202/验证码/TCP 封锁，预热无效） | 保留代码与机遇性重试；不指望 |
| Brave | HTML 抓取 | 挑战页（防护不止 TLS 指纹） | env 开关保留；遇挑战页自动放弃 |
| Google CSE 中继 | element/v1 | **Google 对云 IP 定向黑洞该端点**（变体矩阵实测） | 默认关闭；浏览器直连的 Google 模式不受影响 |
| Mojeek | HTML 抓取 | **2026-11 实测已上 JS challenge** | 默认关闭，代码保留 |
| 百度 tn=json | JSON 接口 | **wappass 验证码**（无 Cookie 连住宅 IP 都触发，需完整 Cookie 指纹生成） | 默认关闭；替代：Bright Data 免费层（5000/月，支持百度 SERP） |

2026-11-15 全网调研后新增的适配器（mojeek/baidu/tavily/serper）即使被反爬拦下也默认关闭、代码保留——反爬环境是移动靶，引擎契约让任何源"关/开/换"都只是一行配置。结果源均为免费路径（无需绑卡）。

## 隐私声明

- 服务端：不记录查询内容（日志无查询词）、不设 Cookie、无第三方统计、无用户标识。
- 边缘缓存：仅按「查询词+参数」为键缓存归一化结果 30 分钟，不含任何用户维度信息。
- 客户端：个人规则/类别/引擎开关仅存本浏览器 localStorage；「导出 JSON」可迁移。
- 固有的：任何搜索引擎下，你的查询词都会发往上游引擎（Bing/DDG/Marginalia/Google）——这是搜索的本质，无法回避。

## License

MIT。架构与交互设计参考了 Luxirty Search（AGPL，仅借鉴思路未复制代码）、tiagozip/metasearch
（用户级规则/Lenses 设计）、mat-1/metasearch2（引擎权重模型，CC0）。
