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
| 快 | 边缘缓存按查询词 30 分钟（重复查询零回源）、函数区域 hkg1、Vite 产物 ~47KB gzip |
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

> 注意：本地从大陆直连时 DuckDuckGo 大概率超时（GFW），属预期——部署到 Vercel（境外出口）后正常。

## 部署到 Vercel

### 1. 推送仓库并导入

```bash
gh repo create yuer-search --public --source=. --remote=origin --push   # 或 private
```

在 [vercel.com](https://vercel.com) → Add New → Project → 选该仓库导入，Framework 自动识别 Vite，直接 Deploy。
Vercel 会自动构建前端（`npm run build` → `dist/`）并把 `api/index.py` 部署为 Python Function。

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
| `VITE_GOOGLE_CSE_CX` | Google 模式的 CSE 引擎 ID；不设则前端隐藏 Google 模式入口 |
| `BRAVE_ENABLED` | 设 `1` 启用 Brave 抓取引擎（默认关闭；反爬风险自负） |

### 5. 验证缓存与预热

```bash
curl -sI "https://s.yuer6327.top/" | grep -i x-vercel-cache     # 第二次访问应 HIT
curl -sI "https://s.yuer6327.top/api/search?q=test" | grep -iE "cache-control|x-vercel-cache"
```

仓库自带 [缓存预热工作流](.github/workflows/cache-hit-check.yml)：push 到 main 后自动预热边缘缓存并统计
`X-Vercel-Cache` 命中率（目标 ≥95%），结果写入 Actions Summary。用 [itdog.cn](https://www.itdog.cn) 三网拨测确认全国可达。

## Google 模式配置

1. 用你的 Google 账号在 [programmablesearchengine.google.com](https://programmablesearchengine.google.com) 免费创建搜索引擎：
   - 「搜索整个网络」开启；不需要图片搜索；「在结果中显示广告」关闭。
   - 记下引擎 ID（cx），设为 Vercel 环境变量 `VITE_GOOGLE_CSE_CX` 后重新部署。
2. 基线屏蔽在 CSE 控制台「搜索功能 → 注释（Annotations）」里配置 `屏蔽` 规则
   （可参照 `config/baseline.json` 的 block 列表逐条添加，或用控制台批量导入）。
   —— 这是唯一需要你手工在 Google 控制台做的"全局基线"步骤。
3. 行为说明：embed 控件免费且无每日额度限制（不在 2027 JSON API 停服范围）；前端探活
   `cse.google.com`，大陆直连用户进入 Google 模式时会看到降级提示并一键切回聚合模式。

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
| DuckDuckGo | HTML 抓取 | **最高风险**：2025-2026 风控升级（验证码/假 202/TCP 封锁），云 IP 重灾区 | curl_cffi TLS 伪装 + lite/html 双端点 + 边缘缓存压频率；挂了不影响其他引擎 |
| Marginalia | 官方免费 API | 限速严格、官方标记 deprecated；纯英文独立索引 | 仅作兜底源、中文查询自动跳过、失败静默降级 |
| Brave | HTML 抓取 | 反爬军备竞赛（TLS 指纹 + 挑战页） | 默认关闭；开启后遇挑战页自动放弃 |
| Google CSE | 官方 embed 控件 | 产品线收缩中，长期命运有不确定性；大陆直连不可用 | 仅作增益模式，探活降级，聚合模式为核心 |

结果源均为免费路径（无需绑卡）。抓取属灰色地带，某源某天失效需换——引擎契约让替换成本很低。

## 隐私声明

- 服务端：不记录查询内容（日志无查询词）、不设 Cookie、无第三方统计、无用户标识。
- 边缘缓存：仅按「查询词+参数」为键缓存归一化结果 30 分钟，不含任何用户维度信息。
- 客户端：个人规则/类别/引擎开关仅存本浏览器 localStorage；「导出 JSON」可迁移。
- 固有的：任何搜索引擎下，你的查询词都会发往上游引擎（Bing/DDG/Marginalia/Google）——这是搜索的本质，无法回避。

## License

MIT。架构与交互设计参考了 Luxirty Search（AGPL，仅借鉴思路未复制代码）、tiagozip/metasearch
（用户级规则/Lenses 设计）、mat-1/metasearch2（引擎权重模型，CC0）。
