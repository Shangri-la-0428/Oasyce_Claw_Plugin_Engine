# Oasyce Dashboard

Preact + TypeScript + Vite 单页应用，Oasyce 协议的 Web 管理界面。

## 快速启动

```bash
# 开发模式（HMR）
cd dashboard && npm run dev    # http://localhost:5173

# 生产构建
npm run build                  # 输出到 dist/

# 通过协议启动（推荐）
oas start                   # http://localhost:8420（自动开浏览器）
oas start --no-browser      # 不自动开浏览器
```

## 架构

```
dashboard/
├── src/
│   ├── main.tsx               # 入口
│   ├── app.tsx                # 路由（5 页面）
│   │
│   ├── pages/                 # 页面组件
│   │   ├── home.tsx           # 首页 — 引导 + 快速注册入口
│   │   ├── mydata.tsx         # 我的数据 — 拖拽注册 + 资产列表 + 删除
│   │   ├── explore.tsx        # 探索 — 搜索 + 报价→购买 + 持仓 + 质押
│   │   ├── automation.tsx     # 自动化 — 任务队列 + 规则 + Agent 选择
│   │   └── network.tsx        # 网络 — 身份面板 + 水印工具 + 像素网格 + 验证者
│   │
│   ├── components/
│   │   ├── nav.tsx            # 顶部导航（5 tab + 主题切换 + 语言切换）
│   │   ├── network-grid.tsx   # 像素网格可视化（元胞自动机风格）
│   │   └── toast.tsx          # 消息提示
│   │
│   ├── store/                 # 状态管理（Preact Signals）
│   │   ├── ui.ts              # 主题 + i18n（185 key, zh/en） + toast
│   │   ├── assets.ts          # 资产数据 CRUD
│   │   └── scanner.ts         # 扫描 / 收件箱 / 信任配置
│   │
│   ├── api/client.ts          # HTTP 客户端（get/post/del）
│   └── styles/design.css      # 设计系统（CSS 变量, 暗黑/明亮双模式）
│
├── dist/                      # 生产构建产物（Python 服务器直接 serve）
├── MIGRATION.md               # Legacy → SPA 迁移追踪
└── package.json               # Preact + Vite, 零运行时依赖
```

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 框架 | Preact 10 | 3KB，API 兼容 React |
| 状态 | @preact/signals | 细粒度响应式，无 context 穿透 |
| 构建 | Vite 8 | 秒级 HMR，<100ms build |
| 样式 | 纯 CSS 变量 | 零依赖，主题切换靠 `data-theme` 属性 |
| 类型 | TypeScript strict | 编译期捕获错误 |
| 后端 | Python stdlib HTTPServer | 零依赖，嵌入 `oasyce_plugin/gui/app.py` |

## 页面功能

### 首页 (home)
引导页，展示协议核心理念，提供快速注册入口。

### 我的数据 (mydata)
- 拖拽文件注册（drop zone + click-to-browse）
- 渐进展示：选文件后才出现描述框
- 资产列表：搜索、排序（时间/价值）、标签过滤
- 展开详情：ID 遮罩 + 复制、删除确认

### 探索 (explore)
- 全文搜索 + 资产类型筛选（数据/服务）
- 完整购买流程：输入金额 → 实时报价（含费用明细）→ 确认 → 结果
- 持仓面板：已购资产份额、均价、当前价值
- 质押面板：验证者列表 + 质押操作

### 自动化 (automation)
两个 tab：
- **任务队列**：待确认的注册/交易任务，支持 approve/reject/edit、一键全部通过
- **规则设置**：
  - 信任等级（🔒手动 / ⚡半自动 / 🤖全自动）
  - 执行 Agent（OpenClaw / Cursor / Claude Code / 自定义）
  - 置信阈值（🛡严格≥90% / ⚖均衡≥70% / 🚀宽松≥50%）
  - 目录扫描触发

### 网络 (network)
- 节点身份面板（公钥遮罩 + 复制 + 说明）
- 水印工具三标签页（嵌入 / 提取 / 追踪）
- 像素网格网络可视化
- 验证者列表 + 网络统计

## 设计系统

基于 CSS 变量，构成主义 × 包豪斯功能主义 × 复古未来风格。

- **暗黑模式**（默认）：`#0a0a0a` 背景，`#e8e8e8` 文字
- **明亮模式**：`#faf9f6` 背景，`#111111` 文字
- 切换方式：Nav 按钮 ☀/☾ + `@media prefers-color-scheme` 系统回退
- 持久化：`localStorage('oasyce-theme')`

### 排版层级（严格 4 级）
| 级别 | 用途 | 样式 |
|---|---|---|
| `.display` | Hero 标题 | 36px weight-300 |
| `.body-text` | 正文 | 15px weight-400 |
| `.caption` | 辅助说明 | 12px weight-400 |
| `.label` | 分区标题 | 11px weight-600 UPPERCASE |

### 常用组件类
`.card` `.btn` `.btn-primary` `.btn-ghost` `.btn-danger` `.input` `.search-box` `.badge` `.kv` `.stat` `.dropzone` `.mono` `.skeleton`

## i18n

`store/ui.ts` 内嵌 185 个 key 的 zh/en 字典，通过 `computed` signal 驱动。

```tsx
const _ = i18n.value;
return <h1>{_['mydata']}</h1>;  // signal tracking 自动触发重渲染
```

添加新 key：在 `dict.zh` 和 `dict.en` 同时添加，**必须成对**。

## 后端 API

所有 API 由 `oasyce_plugin/gui/app.py` 提供，前缀 `/api/`。

| 端点 | 方法 | 用途 |
|---|---|---|
| `/api/assets` | GET | 资产列表 |
| `/api/register` | POST | 注册资产 |
| `/api/asset/<id>` | DELETE | 删除资产 |
| `/api/quote` | POST | 报价 |
| `/api/buy` | POST | 购买份额 |
| `/api/shares` | GET | 持仓查询 |
| `/api/staking` | GET | 验证者列表 |
| `/api/stake` | POST | 质押 |
| `/api/identity` | GET | 节点身份 |
| `/api/inbox` | GET | 收件箱 |
| `/api/inbox/<id>/approve` | POST | 批准 |
| `/api/inbox/<id>/reject` | POST | 拒绝 |
| `/api/inbox/<id>/edit` | POST | 编辑 |
| `/api/inbox/trust` | GET/POST | 信任设置 |
| `/api/scan` | POST | 目录扫描 |
| `/api/fingerprint/embed` | POST | 嵌入水印 |
| `/api/fingerprint/extract` | POST | 提取水印 |
| `/api/fingerprints` | GET | 分发记录 |
| `/api/capabilities` | GET | 服务能力列表 |
| `/api/capability/invoke` | POST | 调用服务 |

## 注意事项

- Python 服务器优先加载 `dashboard/dist/`，找不到时 fallback 到 `app.py` 内嵌的 legacy HTML
- 修改前端后必须 `npm run build`，否则服务器还是 serve 旧 dist
- 服务器已启用 `ThreadingMixIn` + `check_same_thread=False`（多线程安全）
- HTML 响应带 `no-cache`，静态资源带文件名 hash（长缓存）
- 如遇浏览器缓存问题，Cmd+Shift+R 硬刷新
