# 返修抽隔计划与容量签报

白班按已接纳修订确定闸的位置。夜班拿到临时档位时源库已经关闭，同一抽隔计划可以用来签不同档位。原路线复盘仍按 README.md 办理。

## 发行和取证

- `plans.freeze.freeze_isolation_plan(source, archive, revision_id, gate_keys)` 按确切修订发行抽隔计划。`gate_keys` 是有向键的可迭代对象，每项为 `(出发站名, 去向名)` 二元组，按集合解释，空组合法。去向可以是原站或原终局。每个键在指定修订内的合计件次须大于零，且至少一端是私有工位。公开到公开、公开到终局的转送不可装闸。不可读修订、非法闸位或写入失败抛 `FreezeError`，无新计划。
- `plans.catalog.load_isolation_plan(archive, plan_id)` 按号领取固定抽隔计划。发行和取证均返回有 `plan_id`、`revision_id` 和 `stations` 的计划对象，`stations` 是按登记顺序排列的公开工位元组。取证只使用归档库。未知计划抛 `PlanNotFound`，已存在的 V1 计划用于新取证入口抛 `ValueError`。
- 固定计划须保全任意合法档位下可复算的证据。私有工位名、原计数、源库终局原名和逐私站原始转送图留源。给每个私站换个编号并照存原出边分布仍属于转存原图。可发布跨业务边界的匿名派生证据或聚合响应，证据的内部表示由实现决定。

## 断源签报与交班

`analysis.request.publish_isolation_report(archive, plan_id, start, p, *, before_commit=None)` 凭抽隔计划号签报。`start` 是计划中的公开起站。`p` 是 `[0, 1]` 内的 `Fraction`，也接受表示端档的整数 `0` 和 `1`。浮点数、布尔值、越界档位、非法起站或 V1 计划抛 `InvalidReviewRequest`。未知计划抛 `PlanNotFound`。

同向重复观测先合计，按出发站总件次归一。每次按原转送概率选中一个闸位时，以同一 `p` 独立抽隔，立刻结束。没有被抽隔就沿已选转送继续，即使去向是原终局。私有自返、跨工位回流及回到公开站后再次遇闸都按实际尝试次数办理。无可观察出边和始终到不了三个终局的质量都归永不终结。零档的放行、原拒绝及永不终结和原流程一致，抽隔为零。空闸组在所有档位均按原流程计量。

签报返回的对象含 `report_id`、`plan_id`、`revision_id`、`start`、`p`、`receipt`，以及放行 `release_probability`、原拒绝 `reject_probability`、抽隔 `isolation_probability`、永不终结 `never_probability`。`p` 和四项概率均为精确 `Fraction`。四项概率非负且合计为一，零值照录。

`reports.history.read_isolation_report(archive, report_id)` 根据已签正文恢复同一份报告。未知号抛 `ReportNotFound`，已存在的 V1 报告用于新领报入口抛 `ValueError`。计划号和报告号分别沿用现有归档号域。`reports.handover.handover(archive, plan_id)` 也可查抽隔计划，继续按签发顺序返回 `HandoverEntry`。

回执沿用 `Receipt(report_id, plan_id)`。签发在同次提交中固定请求、实际计划、源修订和四项结论，同时登记回执和交班。`before_commit` 接收待提交的回执，沿用现有只读视察或抛错中止的约定。中止或写入失败抛 `PublishError`，无新增报告或交班，申请可重试。勘误后仍可按旧计划签报。重开归档后，凭旧报告号领已签存值。

## 样例

`isolation_case.py` 的 `receive_isolation_case(source)` 载入一组等件次观察。A 等概率进入私有 P 或 Q。P 等概率自返或去 B，Q 只自返，B 等概率回 A 或直接放行。`GATE_LAYOUTS` 给出三种装法。直接运行 `python3 -B isolation_case.py` 可核对 V1 的公开账及原报告，A 的下一公开 B 与无公开首达均为 `1/2`，最终放行为 `1/3`。

使用该修订发行三个抽隔计划，关闭源库。起站均为 A，预期如下，四元组依次为放行、原拒绝、抽隔、永不终结。

| 装法和闸位 | 档位 | 四项结果 |
| --- | --- | --- |
| `return_gate`，P→P 与 Q→Q | 0 | (1/3, 0, 0, 2/3) |
| `return_gate` | 1/2 | (1/5, 0, 4/5, 0) |
| `return_gate` | 1 | (1/7, 0, 6/7, 0) |
| `exit_gate`，P→B 与 Q→Q | 0 | (1/3, 0, 0, 2/3) |
| `exit_gate` | 1/2 | (1/7, 0, 6/7, 0) |
| `exit_gate` | 1 | (0, 0, 1, 0) |
| `unmarked_hold`，仅 P→P | 1/2 | (1/5, 0, 1/5, 3/5) |

原拒绝可用两步例复核。A 只去私有 P，P 只去原拒绝终局，在 P 的出边装闸。半开应签 `(0, 1/2, 1/2, 0)`。

## 运行核验

使用现有 `.pointwise-runtime.json`。清单沿用 `version` 为 `1`、`kind` 为 `cli`，`setup` 是准备命令的 argv 列表，`verify` 和 `demo` 各为一条命令的 argv。

交付时用 `verify` 运行原回归并核对两种装法的断源结论、原拒绝与抽隔分列、请求拒绝、提交中止和重开复领。业务断言失败须非零退出。用 `demo` 展示关闭源库后，同一计划的零档与半开签报，以及重开归档后按报告号领到的结果。
