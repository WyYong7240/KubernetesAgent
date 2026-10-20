# Kubernetes 自检自愈运维助手：详细设计与实施计划

> 状态：已确认的设计基线
>
> 范围：在当前 KubernetesAgent 项目中迭代实现；不包含 DSH 插件
>
> 核心原则：LLM 可以诊断和提出命令计划，但不能绕过策略、审批、权限与审计直接修改集群。

## 1. 目标与边界

系统接收 DAGGER 输出的根因定位事件、外部告警或人工创建的故障事件，形成可见工单。系统自动或人工触发后，采集 Kubernetes、指标、日志和调用链上下文；由 LLM 诊断并生成候选命令计划；在本地完成命令策略校验与审批；再通过远程 Kubernetes MCP Server 或受控主机执行器完成验证、执行、回滚和效果确认。

### 1.1 本地控制面与远程能力的边界

以下能力必须部署在运行 KubernetesAgent 的本地环境中：

- RootCauseEvent 工单队列、自动化等级与重试机制。
- DAGGER 事件接收、上下文编排、LangGraph 工作流与 Agent。
- LLM 提示词、命令解析、策略校验、人工审批、审计和验证判定。
- PostgreSQL 数据库、Vue 工单工作台和 FastAPI API。
- 对远程 MCP、Prometheus、日志/Trace、Host Executor 的适配器。

集群或受管服务器仅提供以下受控基础设施：

- 远程 Kubernetes MCP Server（只读和受限写入端点）。
- Prometheus 及可选日志/Trace API。
- Kubernetes ServiceAccount、RBAC、准入策略、NetworkPolicy 与 API 审计。
- 仅在必须时部署的无生产凭据沙箱 Runner。
- MCP 不能覆盖的服务器本地命令所需的低权限 Host Executor 或 SSH 白名单入口。

> 远程主机本地命令不可能在没有远程执行通道的情况下执行。Host Executor/SSH 包装器是最小化的远端执行设施，不承载工单、LLM、审批或策略逻辑。

## 2. 总体架构

```text
┌──────────────────── 本地 KubernetesAgent 控制面 ────────────────────┐
│ Vue 工作台 / FastAPI / PostgreSQL                                   │
│ RootCauseEvent Work Queue / Worker / LangGraph 状态机                │
│ ReAct 诊断 Agent / 结构化规划 Agent / 命令策略控制器                  │
│ 本地沙箱 / 审批 / 审计 / 验证 / 回滚决策                              │
│                                                                       │
│ ClusterExecutionAdapter                                               │
│   ├─ RemoteMcpAdapter                                                  │
│   ├─ PrometheusAdapter                                                 │
│   └─ HostExecutorAdapter                                               │
└───────────────────────────────────────────────────────────────────────┘
                   │ HTTPS + mTLS/OIDC              │ mTLS 或 SSH 证书
                   ▼                                ▼
┌──────────────────────── 集群/服务器侧 ───────────────────────────────┐
│ k8s-mcp-read（只读身份）                                             │
│ k8s-mcp-execute（受限写入身份；私有入口）                             │
│ Prometheus / 日志 / Trace                                             │
│ 可选 Sandbox Runner / Host Executor                                   │
│ ServiceAccount / RBAC / Admission Policy / NetworkPolicy / Audit Log  │
└───────────────────────────────────────────────────────────────────────┘
```

远程 MCP 是 Kubernetes 资源访问网关，而不是工作流控制面。诊断 Agent 只连接只读 MCP；写入 MCP 不向 ReAct Agent 注册，只有审批后的本地执行路由器可调用。

## 3. 统一 RootCauseEvent Work Queue

首期使用 PostgreSQL 实现唯一的持久化工单队列，不要求 RabbitMQ。DAGGER、告警平台和人工创建的事件均进入：

```text
POST /api/v1/root-cause-events
```

接收端在单一数据库事务内执行：

```text
校验来源与签名 → 幂等/去重 → 创建或关联工单 → 写入审计事件 → 排队或等待人工
```

首期的幂等键为 `(source, external_event_id)`：完全重复的投递返回既有事件和工单，不再新增审计事件。跨事件的关联（同一故障的后续告警）必须使用显式的 `correlation_key` 或人工操作；首期不根据 LLM 或文本相似度自动合并，避免错误合并事故。

Worker 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 和租约字段领取工单。审批中的工单不占用 Worker；人工同意、拒绝、取消或超时后，重新进入可处理状态。

### 3.1 自动化等级

| 模式 | 行为 |
| --- | --- |
| `manual_only` | 仅创建工单，人工触发后才开始处理。 |
| `auto_triage` | 自动采集上下文、诊断并生成候选计划。 |
| `auto_validate` | 自动完成本地校验、沙箱和 server-side dry-run。 |
| `approval_required` | 验证通过后等待人工审批；生产默认。 |
| `auto_execute_limited` | 仅非生产、已接入服务、低风险且明确允许的动作可执行。 |

### 3.2 状态机

```text
RECEIVED
→ WAITING_MANUAL | QUEUED
WAITING_MANUAL --人工触发--> QUEUED
→ PROCESSING
→ CONTEXT_READY
→ DIAGNOSED
→ PLAN_READY
→ SANDBOX_PASSED
→ DRY_RUN_PASSED
→ PENDING_APPROVAL
→ EXECUTING
→ VERIFYING
→ RESOLVED | ROLLED_BACK | ESCALATED | FAILED
```

任一尚未执行的非终态工单可以取消：

```text
RECEIVED | WAITING_MANUAL | QUEUED | PROCESSING | CONTEXT_READY |
DIAGNOSED | PLAN_READY | SANDBOX_PASSED | DRY_RUN_PASSED |
PENDING_APPROVAL --取消--> CANCELED
```

`EXECUTING` 或 `VERIFYING` 收到取消请求时先进入 `CANCEL_REQUESTED`。执行器确认尚未产生写入时才转为 `CANCELED`；若已经产生变更，则进入 `ESCALATED` 并由人工决定验证或回滚，不能把已变更的集群误标为“已取消”。`RESOLVED`、`ROLLED_BACK`、`ESCALATED`、`FAILED` 与 `CANCELED` 是终态；仅人工重试可以将 `FAILED` 或 `ESCALATED` 创建为新的处理尝试并重新入队。
每次状态迁移均产生不可变的 `audit_events` 记录。当前状态保留在 `work_orders`，完整历史从审计事件重建。

## 4. 本地模块设计

| 模块 | 职责 | 首期实现 |
| --- | --- | --- |
| `event_ingress` | 接收 DAGGER/告警/人工事件；鉴权、校验、幂等 | FastAPI + Pydantic |
| `work_orders` | 工单、队列、租约、重试、取消和自动化路由 | PostgreSQL + SQLAlchemy Async |
| `orchestration` | 驱动状态机，在审批处暂停和恢复 | LangGraph + PostgreSQL Checkpointer |
| `context_builder` | 汇总根因、K8s 快照、指标、日志、Trace | 异步适配器 + `FaultContext` |
| `diagnosis_agent` | 基于证据补充诊断和排查结论 | ReAct，只绑定只读工具 |
| `knowledge_service` | 查询内部 SOP 和 K8s 文档 | 现有 Chroma/RAG 重构为服务 |
| `planner_agent` | 生成候选命令、前置条件、回滚和验证要求 | LLM 严格 Pydantic 结构化输出 |
| `command_guard` | 解析命令、白名单、风险和回滚规则 | AST + kubectl 语义校验 |
| `sandbox_runner` | 不带生产凭据的预执行校验 | 本地受限容器 |
| `cluster_validator` | 真实 API server dry-run 和影响分析 | MCP/Host Executor 适配器 |
| `approval_service` | 审批、超时、撤销、双人复核 | API + Vue 工作台 |
| `execution_router` | 为已审批命令选择执行目标 | 确定性规则代码 |
| `verification_service` | 对比修复前后 SLO、告警与资源健康度 | Prometheus + MCP 读取 |
| `rollback_service` | 选择和执行预校验补偿操作 | 基于执行前快照 |
| `audit_service` | 记录完整链路，脱敏敏感数据 | 追加式 PostgreSQL 表 |

建议目录：

```text
app/
  api/                 # FastAPI 路由与鉴权
  db/                  # 会话、迁移、仓储
  models/              # Pydantic/SQLAlchemy 数据模型
  work_orders/         # 队列、租约、状态机
  orchestration/       # LangGraph 图与恢复逻辑
  context/             # 证据归一化与采集适配器
  agents/              # diagnosis_agent、planner_agent
  policy/              # command_guard、allowlist、risk、rollback
  adapters/            # MCP、Prometheus、Host Executor
  validation/          # sandbox、cluster_dry_run
  execution/           # router 与执行记录
  verification/        # 指标、资源、告警判定
  audit/               # 审计事件
```

## 5. Agent 与流程编排

不保留当前任意路由的 `Supervisor → OPS / RESEARCH / CHAT` 作为事故处理主路径。事故处理采用确定性状态图，保留两个有限职责的 LLM 节点：

| 角色 | 范式 | 权限 |
| --- | --- | --- |
| 工单编排器 | 确定性状态机 | 无集群写权限 |
| 诊断 Agent | ReAct | 只读 MCP、指标、日志、RAG |
| 规划 Agent | 结构化输出 | 不绑定执行工具 |
| 策略/执行/回滚/验证 | 普通代码 | 通过受控适配器调用远端 |

普通聊天可继续保留 `CHAT` 节点，但不得参与生产工单执行。

### 5.1 故障上下文

`FaultContext` 使用摘要与证据引用，避免向模型输入未经压缩的全量日志和指标：

```json
{
  "incident_id": "inc-20261018-001",
  "scope": {
    "cluster": "prod-cn-01",
    "namespace": "payments",
    "workload": {
      "kind": "Deployment",
      "name": "checkout-api",
      "uid": "...",
      "resource_version": "..."
    }
  },
  "root_cause": {
    "source": "dagger",
    "confidence": 0.87,
    "summary": "数据库连接池耗尽导致请求超时",
    "evidence_refs": ["metric:db_pool", "log:timeout", "trace:abc"]
  },
  "risk": {
    "environment": "production",
    "level": "high",
    "blast_radius": "single-workload"
  }
}
```

## 6. Command Plan、校验与执行

LLM 可生成 Shell/kubectl 风格的展示命令，但实际执行必须先转为规范化 `CommandSpec`。展示字符串仅用于人工审阅和审计；执行器只接受规范化参数数组。

```text
LLM 命令文本
→ Shell AST / kubectl 解析
→ 白名单与语义规则
→ CommandSpec
→ 沙箱与 dry-run
→ 审批
→ 远程执行
```

示例：

```text
展示命令：kubectl -n payments scale deployment/checkout-api --replicas=6

CommandSpec：
tool=kubectl
subcommand=scale
namespace=payments
resource.kind=deployment
resource.name=checkout-api
arguments.replicas=6
```

执行必须使用等价的 `argv` 且 `shell=False`，不得使用 `bash -c`。首期禁止 Shell 控制操作符、管道、重定向、变量展开、命令替换、`exec`、`apply`、`create` 和 `delete`。

### 6.1 首期命令白名单

```text
kubectl get
kubectl describe
kubectl logs
kubectl top
kubectl rollout status
kubectl rollout restart deployment
kubectl scale deployment
```

### 6.2 验证层次

| 层次 | 位置 | 目的 |
| --- | --- | --- |
| 静态验证 | 本地 | 解析语法、工具/参数/资源白名单、风险、回滚完整性 |
| 本地沙箱 | 本地 | 验证 AST、超时、命令版本、模拟输入输出；无生产凭据 |
| server-side dry-run | 目标集群 | 验证 RBAC、准入、配额、真实对象和字段合法性 |
| 执行前重检 | 本地调用远端 | 校验 UID、resourceVersion、前置条件未变化 |

审批应发生在 dry-run 成功之后。审批记录必须绑定计划哈希、目标 UID、规范命令、回滚方案与有效期；任一项变化都会使审批失效。

### 6.3 执行目标路由

| 目标 | 适用场景 | 调用者 |
| --- | --- | --- |
| `MCP_READ` | K8s 资源、事件、日志等读取 | 上下文/诊断模块 |
| `MCP_EXECUTE` | 被远程 MCP 明确支持的受限集群写操作 | 审批后的执行路由器 |
| `HOST_EXECUTOR` | MCP 不支持的 kubectl dry-run、特殊集群命令、服务器本地命令 | 审批后的执行路由器 |

LLM 无权决定路由；`execution_router` 依据 `CommandSpec` 和能力注册表选择目标。

## 7. 效果验证与回滚

每份 Command Plan 必须在审批前包含：

- 执行前快照和显式前置条件。
- 预期资源差异。
- 可验证的回滚方案。
- 验证时间窗口、成功条件和中止条件。

示例：

```text
验证窗口：10 分钟
成功：错误率 < 2%，P95 < 500ms，目标副本均 Ready，原告警恢复
中止：错误率相较基线增加 20%，可用副本下降，出现 CrashLoopBackOff
```

首期回滚支持范围：

| 操作 | 回滚策略 |
| --- | --- |
| Deployment 扩容 | 恢复执行前副本数；存在 HPA 时默认拒绝自动扩容 |
| Deployment 滚动重启 | 停止后续滚动，必要时回退到已知 Revision；需提示并非严格状态回滚 |
| requests/limits 变更 | 后续阶段通过执行前快照生成反向 Patch |
| 镜像回退 | 后续阶段仅允许回退到已验证 Revision，强制审批 |
| 删除资源 | 首期禁止自动执行 |

## 8. Kubernetes/服务器侧预先准备

以下事项需要在集群或受管服务器准备；工单、审批、数据库和 Agent 不部署于集群。

### 8.1 命名空间与接入标记

创建：

```text
kubernetes-mcp-read
kubernetes-mcp-execute
ops-agent-sandbox          # 仅需远程沙箱时
```

为每个被接管的业务命名空间添加：

```yaml
metadata:
  labels:
    ops-agent.io/enrolled: "true"
    ops-agent.io/environment: "production"
    ops-agent.io/automation-mode: "approval_required"
```

### 8.2 ServiceAccount 与 RBAC

创建四类身份：

| ServiceAccount | 位置 | 职责 |
| --- | --- | --- |
| `ops-agent-mcp-observer` | `kubernetes-mcp-read` | 只读 Kubernetes MCP |
| `ops-agent-mcp-executor` | `kubernetes-mcp-execute` | 受限写入 Kubernetes MCP |
| `ops-agent-validator` | `kubernetes-mcp-execute` 或独立命名空间 | server-side dry-run |
| `ops-agent-sandbox` | `ops-agent-sandbox` | 可选远程沙箱，不挂载生产凭据 |

只读身份在已接入业务命名空间中允许：

```text
get/list/watch:
pods, events, deployments, statefulsets, daemonsets, replicasets,
services, endpointslices, horizontalpodautoscalers, poddisruptionbudgets,
resourcequotas, limitranges

get:
pods/log
```

写入身份首期仅允许：

```text
get/patch:
deployments
deployments/scale
```

通过每个业务命名空间的 `RoleBinding` 授权，不使用宽泛的全局 `ClusterRoleBinding`。

严禁授予：

```text
cluster-admin、通配符 *、Secret get/list/watch、pods/exec、nodes/proxy、
Role/RoleBinding、ServiceAccount、Namespace、CRD、Webhook、PersistentVolume
```

### 8.3 远程 Kubernetes MCP Server

- 使用固定版本/digest 的镜像，禁止 `latest`。
- 部署两个独立实例：`k8s-mcp-read` 与 `k8s-mcp-execute`。
- Helm Chart 使用自建 ServiceAccount 和自管 RBAC；禁用宽泛的默认 RBAC。
- `k8s-mcp-read` 对外提供本地 Agent 所需的只读 Toolset。
- `k8s-mcp-execute` 不向诊断 Agent 暴露，仅允许本地执行路由器访问。
- 远程访问使用 HTTPS；跨网络场景增加 mTLS 或 OIDC。
- 先枚举实际 MCP 工具能力；未支持的 dry-run 或命令不得假定可用，应走 Host Executor。

参考：Kubernetes MCP Server 提供 Helm、ServiceAccount、Ingress/Gateway API、TLS 和可配置 RBAC。[项目主页](https://github.com/containers/kubernetes-mcp-server) [Chart 文档](https://github.com/containers/kubernetes-mcp-server/blob/main/charts/kubernetes-mcp-server/README.md)

### 8.4 server-side dry-run 适配

- 校验 MCP 是否有等价 dry-run 工具；没有时，由 Host Executor 执行受控 `kubectl --dry-run=server`。
- `ops-agent-validator` 必须拥有与目标操作一致的 RBAC，否则 dry-run 无法验证真实权限。
- 检查现有 Admission Webhook 是否声明支持 dry-run；不支持会导致 API Server 拒绝 dry-run 请求。
- 返回并保存 Admission 响应、资源差异、Quota/HPA/PDB 风险与 API 错误。

### 8.5 准入、网络与审计

- 用 `ValidatingAdmissionPolicy`、Kyverno 或 OPA Gatekeeper 限制执行身份。
- 仅允许修改带 `plan-id`、`approval-id`、`audit-id` 注解的已接入资源。
- 首期只允许变更 `spec.replicas` 或滚动重启注解；拒绝 image、env、volume、securityContext、serviceAccountName 变更。
- 远程沙箱不得访问生产 API Server、数据库或生产工作负载。
- MCP 执行端点仅允许本地 Agent 固定网络身份访问。
- 为 validator/executor 身份开启 Kubernetes API Audit Log。

Kubernetes 权限遵循最小权限、命名空间边界和无通配符原则；Secret 读取与工作负载创建会显著扩大权限边界。[Kubernetes RBAC 最佳实践](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)

## 9. 数据模型（首期）

```text
RootCauseEvent n ── 1    WorkOrder
WorkOrder      1 ── n    FaultContext
WorkOrder      1 ── n    RemediationPlan
RemediationPlan 1 ── n   ApprovalRecord
RemediationPlan 1 ── n   ExecutionRun
WorkOrder      1 ── n    AuditEvent
```

首期每个新事件创建一张工单；同一 `(source, external_event_id)` 的重复投递只返回既有记录。后续版本可将带有相同显式 `correlation_key` 的多个 `RootCauseEvent` 关联到同一 `WorkOrder`，但不得以模型推断自动合并。

`RemediationPlan` 至少包括：

```text
plan_hash
risk_level
display_command
command_spec
execution_target
preconditions
expected_change
rollback_plan
verification_conditions
evidence_refs
```

审计中记录原始模型输出和命令结果时，必须脱敏 API Key、Token、Secret 内容和高敏日志字段。

## 10. 分阶段实施计划

### Phase 0：工程基线与设计固化

- 新增本设计文档、依赖清单和环境变量模板。
- 将现有单文件 FastAPI/Agent 拆分为 `app/` 包结构。
- 选择 PostgreSQL，接入 SQLAlchemy Async、Alembic 和持久化配置。
- 迁移当前 `MemorySaver`：聊天记忆与工单状态分离。

验收：现有聊天 API 保持可用，数据库迁移可重复执行。

### Phase 1：工单队列与人工工作台

- 实现 `root_cause_events`、`work_orders`、`audit_events`。
- 实现 DAGGER 回调 API、幂等去重和 PostgreSQL Worker 租约。
- 前端新增工单列表、详情、人工触发、取消和重试；取消在执行开始后使用 `CANCEL_REQUESTED` 语义。
- 仅实现 `manual_only` 与 `auto_triage`。

验收：同一 DAGGER 事件不会重复创建工单；服务重启后待处理工单可继续处理。

### Phase 2：远程只读观测与上下文

- 将当前 stdio Kubernetes MCP 客户端替换为远程 HTTPS MCP 适配器。
- 集成 Prometheus HTTP 查询、MCP 资源快照与现有 RAG。
- 定义并落库 `FaultContext` 与证据引用。
- ReAct 诊断 Agent 只绑定只读 MCP 工具。

验收：一张工单可展示根因、目标资源快照、关键指标、日志摘要和证据来源。

### Phase 3：结构化计划与本地策略控制

- 定义 `CommandPlan`、`CommandSpec`、风险级别与回滚模型。
- 实现规划 Agent 的结构化输出和 Prompt 版本记录。
- 实现 Shell AST/kubectl 参数白名单、目标资源校验和执行目标路由。
- 初期仅支持查询、Deployment 滚动重启和受限扩容。

验收：不符合白名单、资源不存在、参数越界或缺少回滚方案的计划被本地拒绝。

### Phase 4：沙箱、dry-run 与审批

- 实现本地无凭据沙箱。
- 实现 `cluster_validator`，支持 MCP 或 Host Executor 的 server-side dry-run。
- 实现审批 API、审批过期、审批绑定计划哈希与 Vue 审批页。
- 加入 `auto_validate` 与 `approval_required`。

验收：未审批、审批过期或目标对象变更的计划均不可执行。

### Phase 5：受控执行、验证与回滚

- 接入 `k8s-mcp-execute` 和/或 Host Executor。
- 对接集群 RBAC、准入策略和 API Audit Log。
- 执行前二次状态检查；执行后验证 SLO、告警、Pod Ready 和错误率。
- 对支持的扩容操作实现快照回滚；失败时升级人工。

验收：从批准到执行、验证和回滚可完整审计；执行身份无越权能力。

### Phase 6：灰度与扩展动作

- 为多副本工作负载引入受 PDB/HPA 约束的灰度策略。
- 增加资源 requests/limits 建议及受控变更。
- 增加已验证 Revision 的版本回退，默认强制人工审批。
- 根据实际吞吐量决定是否由 RabbitMQ 辅助通知 Worker。

验收：所有新增写操作均具有明确影响范围、回滚策略和验证规则。

## 11. 首个实现切片

第一个可交付切片应只实现：

```text
DAGGER 事件接收
→ PostgreSQL 工单
→ 人工触发
→ 远程只读 MCP 上下文采集
→ 诊断/计划草案
→ 前端展示
```

此切片不具备集群写入能力，不需要先创建执行 RBAC，能先验证 DAGGER 事件格式、工单体验、MCP 连通性和上下文质量。其稳定后再进入命令校验、dry-run、审批和执行阶段。

## 12. PR 1：工单基础与安全事件入口

PR 1 的目标是将项目从聊天原型推进为可持久化的本地控制面基础，但不连接任何集群写入端点，也不启动诊断 Agent。范围如下：

```text
工程包结构与配置
→ PostgreSQL / Alembic 基线
→ RootCauseEvent 幂等接收
→ WorkOrder 状态机与追加式审计
→ 人工触发、取消、重试 API
→ 单元与 API 集成测试
```

### 12.1 交付内容

- 新增 `app/` 控制面包；现有 `k8sAgent.py` 聊天原型在本 PR 保持不变，迁移到统一 API 是后续兼容性工作。
- 增加 `work_orders`、`root_cause_events`、`audit_events` 表及可重复执行的 Alembic 初始迁移。
- 定义版本化 `POST /api/v1/root-cause-events` 契约；生产环境要求 `X-Dagger-Signature: sha256=<hex>` HMAC-SHA256 验签。
- 使用数据库唯一约束保证 `(source, external_event_id)` 幂等；首次投递返回 `201`，重复投递返回既有工单并返回 `200`。
- 增加工单查询、人工触发、取消、重试 API。Worker 领取和租约恢复在下一 PR 实现；本 PR 先持久化 `next_run_at` 与租约字段。
- 输入和审计持久化前对常见 `token`、`secret`、`password`、`authorization`、`api_key` 字段脱敏。
- 不提供 MCP 执行配置、命令执行器、Kubernetes 写 RBAC 或执行 API。

### 12.2 验收

- 重复提交同一 DAGGER 事件只得到一个事件和一张工单。
- 创建事件、创建工单、初始状态迁移和审计事件在同一事务中提交。
- `manual_only` 事件进入 `WAITING_MANUAL`，人工触发后才进入 `QUEUED`；`auto_triage` 事件直接进入 `QUEUED`。
- 非执行中工单取消后进入 `CANCELED`；执行中或验证中的工单只能进入 `CANCEL_REQUESTED`。
- `FAILED` 和 `ESCALATED` 工单允许人工重试；其他状态重试返回冲突。
- 生产环境缺少签名密钥或签名无效时拒绝 DAGGER 事件。

### 12.3 本地联调记录（2026-10-19）

- FastAPI 与 Alembic 统一读取项目根目录 `.env`，进程环境变量优先。ORM 枚举按 `.value` 持久化，与迁移中的检查约束一致。
- PostgreSQL 位于 WSL Docker，Windows 后端通过 `127.0.0.1:5432` 连接；开发数据库已执行 `20261019_0001` 迁移。
- PostgreSQL 集成测试通过 Alembic 在独立随机 schema 中建表，并检查 ORM/迁移一致性；覆盖并发重复投递、人工操作、脱敏与新应用实例读取。测试结束后清理独立 schema。
- 本地 HTTP 服务使用 `127.0.0.1:38889`，已验证首次提交 `201`、重复提交 `200`、人工触发进入 `QUEUED`、取消进入 `CANCELED`。可用 `examples/root-cause-event.json` 进行手工测试。
- PR1 仅接受 `manual_only` 和 `auto_triage`，其他自动化模式拒绝入库。人工操作 API 当前为开发接口，操作者请求头只用于审计；正式部署前还需补齐认证授权。
