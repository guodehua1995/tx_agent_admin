# 报价模块前端页面设计

## 一、技术基座

| 项 | 选型 |
|---|---|
| UI 框架 | Naive UI |
| 表格/弹窗 | CrudTable + CrudModal + useCRUD |
| 路由 | 后端菜单动态注入 `/quotation/*` |
| API 前缀 | `/quotation/` |

---

## 二、页面总览

```
/quotation
├── /quotation/client      → 甲方管理
├── /quotation/rule        → 报价规则管理（含 Excel 导入）
└── /quotation/archive     → 版本归档
```

审批功能集成在「报价规则」页面内（Drawer），无需独立页面。

---

## 三、API 定义（api/index.js 新增）

```javascript
// ── 报价模块 ──────────────────────────────────────────
// 甲方
getClientList: (params = {}) => request.get('/quotation/client/list', { params }),
createClient: (data = {}) => request.post('/quotation/client/create', data),
updateClient: (data = {}) => request.post('/quotation/client/update', data),  // 注意：后端是 PUT
deleteClient: (params = {}) => request.delete('/quotation/client/delete', { params }),
// 报价规则
getRuleList: (params = {}) => request.get('/quotation/rule/list', { params }),
getRuleDetail: (params = {}) => request.get('/quotation/rule/detail', { params }),
createRule: (data = {}) => request.post('/quotation/rule/create', data),
submitRule: (data = {}) => request.post('/quotation/rule/submit', data),
// 审批
getApprovalList: (params = {}) => request.get('/quotation/approval/list', { params }),
doApproval: (data = {}) => request.post('/quotation/approval/action', data),
// Excel
parseExcel: (data = {}) => request.post('/quotation/excel/parse', data, {
  headers: { 'Content-Type': 'multipart/form-data' }
}),
importExcel: (data = {}) => request.post('/quotation/excel/import', data),
// 归档
getArchiveList: (params = {}) => request.get('/quotation/archive/list', { params }),
getArchiveDetail: (params = {}) => request.get('/quotation/archive/detail', { params }),
```

---

## 四、页面 1 — 甲方管理

**路径**：`web/src/views/quotation/client/index.vue`

### 4.1 功能

标准 CRUD 页面，使用 `useCRUD` + `CrudTable` + `CrudModal`。

### 4.2 搜索栏

| 字段 | 组件 | 说明 |
|------|------|------|
| keyword | NInput | 按名称/简称模糊搜索 |

### 4.3 表格列

| 列名 | 字段 | 宽度 | 说明 |
|------|------|------|------|
| 甲方名称 | name | 200 | — |
| 简称 | short_name | 120 | — |
| 联系人 | contact | 100 | — |
| 电话 | phone | 140 | — |
| 状态 | is_active | 80 | NTag: 启用=success / 禁用=default |
| 创建时间 | created_at | 160 | formatDate |
| 操作 | — | 160 | 编辑 / 删除 |

### 4.4 新增/编辑弹窗

| 字段 | 组件 | 必填 | 说明 |
|------|------|------|------|
| 甲方名称 | NInput | 是 | unique |
| 简称 | NInput | 否 | — |
| 联系人 | NInput | 否 | — |
| 电话 | NInput | 否 | — |
| 备注 | NInput(type=textarea) | 否 | — |
| 是否启用 | NSwitch | — | 默认 true |

---

## 五、页面 2 — 报价规则管理

**路径**：`web/src/views/quotation/rule/index.vue`

### 5.1 功能

- 规则列表（筛选甲方 + 状态）
- 新增规则（手动 / Excel 导入）
- 查看规则详情（明细树）
- 提交审批 / 执行审批（Drawer 内）

### 5.2 搜索栏

| 字段 | 组件 | 说明 |
|------|------|------|
| 甲方 | NSelect(remote) | 从 getClientList 加载 options |
| 状态 | NSelect | draft/pending_approval/active/archived |

### 5.3 表格列

| 列名 | 字段 | 宽度 | 说明 |
|------|------|------|------|
| 甲方 | client_name | 180 | 需前端关联展示 |
| 版本 | version | 60 | `v{n}` |
| 状态 | status | 100 | NTag 色彩映射 |
| 来源 | source_type | 100 | 手动/Excel |
| 创建人 | creator_id | 100 | — |
| 创建时间 | created_at | 160 | — |
| 操作 | — | 240 | 详情/提交/审批/删除 |

**状态色彩映射**：
```javascript
const statusColorMap = {
  draft: 'default',
  pending_approval: 'warning',
  active: 'success',
  archived: 'info',
}
const statusLabelMap = {
  draft: '草稿',
  pending_approval: '待审批',
  active: '生效中',
  archived: '已归档',
}
```

### 5.4 操作按钮逻辑

| 按钮 | 显示条件 | 动作 |
|------|---------|------|
| 详情 | 始终 | 打开详情 Drawer |
| 提交审批 | status === 'draft' | 调 submitRule → 刷新列表 |
| 审批 | status === 'pending_approval' | 打开审批 Drawer |
| 删除 | status === 'draft' | 软删除 |

### 5.5 新增规则 — 选择方式弹窗

点击「新增」先弹出方式选择：
- **手动录入** → 打开规则编辑 Drawer
- **Excel 导入** → 打开 Excel 导入 Drawer

### 5.6 手动录入 Drawer

```
┌───────────────────────────────────────────┐
│  新增报价规则                    [保存] [取消]│
├───────────────────────────────────────────┤
│  甲方：[NSelect]    来源：手动录入            │
│                                           │
│  ┌─ 明细编辑 ────────────────────────────┐ │
│  │  [+ 新增一级项目]                      │ │
│  │                                       │ │
│  │  ▼ 一级项目 A                         │ │
│  │     名称: [___] 编码: [___]           │ │
│  │     [+ 新增二级项目] [删除]            │ │
│  │       ├ 二级-1: 名称/编码/单价/单位    │ │
│  │       ├ 二级-2: 名称/编码/单价/单位    │ │
│  │       └ ...                           │ │
│  │                                       │ │
│  │  ▼ 一级项目 B                         │ │
│  │     ...                               │ │
│  └───────────────────────────────────────┘ │
└───────────────────────────────────────────┘
```

**明细编辑组件**（可复用）：

| 字段 | 组件 | 必填 |
|------|------|------|
| 项目名称 | NInput | 是 |
| 编码 | NInput | 否 |
| 单价 | NInputNumber(precision=4) | 二级必填 |
| 单位 | NInput | 二级必填 |
| 备注 | NInput | 否 |
| 排序 | NInputNumber | 否(默认0) |

### 5.7 Excel 导入 Drawer

```
┌───────────────────────────────────────────┐
│  Excel 报价单导入              [确认导入] [取消]│
├───────────────────────────────────────────┤
│  甲方：[NSelect]                           │
│                                           │
│  Step 1: 上传文件                          │
│  [NUpload .xlsx/.xls 拖拽上传]             │
│                                           │
│  Step 2: 预览解析结果（可编辑）              │
│  ┌─────────────────────────────────────┐  │
│  │  解析到 N 条一级项目，M 条二级项目    │  │
│  │  (表格形式展示，同手动录入的树形编辑)  │  │
│  │  ⚠️ 待确认项高亮标黄                 │  │
│  └─────────────────────────────────────┘  │
│                                           │
│  Step 3: 确认无误后点击「确认导入」          │
└───────────────────────────────────────────┘
```

### 5.8 规则详情 Drawer

```
┌───────────────────────────────────────────┐
│  报价规则详情                        [关闭] │
├───────────────────────────────────────────┤
│  甲方: XXX公司    版本: v3    状态: [生效中]  │
│  来源: Excel导入    创建人: 张三             │
│  审批人: 李四      审批时间: 2026-06-10     │
│                                           │
│  ── 明细列表 ──                            │
│  NDataTable (树形展开)                     │
│  | 项目名称 | 编码 | 单价 | 单位 | 备注 |   │
│  |----------|------|------|------|------|   │
│  | ▼一级A   |      |      |      |      |  │
│  |  二级A-1 | A001 | 500  | 元/次 |     |  │
│  |  二级A-2 | A002 | 800  | 元/天 |     |  │
│  | ▼一级B   |      |      |      |      |  │
│  |  ...     |      |      |      |      |  │
└───────────────────────────────────────────┘
```

### 5.9 审批 Drawer

```
┌───────────────────────────────────────────┐
│  审批报价规则                        [关闭] │
├───────────────────────────────────────────┤
│  (同详情展示规则基本信息 + 明细树)           │
│                                           │
│  ── 审批操作 ──                            │
│  审批意见: [NInput textarea]               │
│                                           │
│  [通过 ✓]  [驳回 ✗]                       │
│  (驳回时意见必填)                           │
└───────────────────────────────────────────┘
```

---

## 六、页面 3 — 版本归档

**路径**：`web/src/views/quotation/archive/index.vue`

### 6.1 功能

按甲方查看历史归档版本快照（只读）。

### 6.2 搜索栏

| 字段 | 组件 | 说明 |
|------|------|------|
| 甲方 | NSelect(remote) | 必选，选择后加载归档列表 |

### 6.3 表格列

| 列名 | 字段 | 宽度 | 说明 |
|------|------|------|------|
| 版本号 | version | 80 | `v{n}` |
| 归档原因 | archived_reason | 120 | new_version / reimport |
| 归档人 | archived_by | 100 | — |
| 归档时间 | created_at | 160 | — |
| 操作 | — | 80 | 查看快照 |

### 6.4 快照详情 Drawer

点击「查看」打开 Drawer，展示归档时的完整明细快照（只读 NDataTable 树形展开），数据来自 `snapshot` JSON 字段。

---

## 七、文件结构

```
web/src/views/quotation/
├── client/
│   └── index.vue          # 甲方管理（~250行）
├── rule/
│   ├── index.vue          # 报价规则列表 + 操作入口（~500行）
│   ├── RuleItemEditor.vue # 明细树编辑组件（复用于手动/Excel）（~300行）
│   ├── RuleDetailDrawer.vue   # 规则详情/审批 Drawer（~250行）
│   └── ExcelImportDrawer.vue  # Excel 导入 Drawer（~200行）
└── archive/
    └── index.vue          # 版本归档（~200行）
```

---

## 八、交互要点

1. **甲方 Select 联动**：规则列表的甲方筛选、新增规则的甲方选择均使用远程搜索（debounce 300ms 调 getClientList）
2. **明细编辑器**：使用动态 Array 维护 `items[]`，支持拖拽排序（NButton move up/down 即可，无需引入 sortable 库）
3. **Excel 解析→编辑→提交**：解析结果直接填入 RuleItemEditor，用户可在提交前自由修改
4. **审批权限**：前端通过 `v-permission` 控制审批按钮显示，后端 double check
5. **状态流转提示**：提交审批、审批通过/驳回后用 `$message.success` 提示并刷新列表
6. **版本展示**：甲方生效规则在列表中 NTag 高亮 `active`，同一甲方仅一条绿色标记
