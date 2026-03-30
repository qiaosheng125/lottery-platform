# Bug Fix Log - 2026-03-30

## 本轮接口与按钮联调新增记录

### 13. 后台中奖页“标记已检查”按钮请求了错误路径

### 问题

后台中奖管理页 [winning.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/admin/winning.html) 的“标记已检查”按钮原先请求：

```text
/winning/admin/mark-checked/<record_id>
```

但后端真实接口注册在：

```text
/api/winning/admin/mark-checked/<record_id>
```

### 影响

- 管理员点击“标记已检查”会直接打到 404。
- 前端按钮存在，但审核动作实际不可用。
- 已上传中奖图片的记录无法在页面上完成“已检查”闭环。

### 修复方式

- 更新 [winning.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/admin/winning.html)，把请求路径改为 `/api/winning/admin/mark-checked/...`。
- 增加模板级回归检查，避免以后再改回错误路径。

### 验证

- 脚本复现：错误路径返回 `404`，正确路径返回 `200`
- `pytest -q tests/test_bug_fixes.py -k admin_winning_template_uses_api_mark_checked_endpoint`

### 14. 登录页未透传已保存的 `device_id`

### 问题

登录页 [login.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/login.html) 原先提交登录请求时只传 `username/password`，不会把本地已保存的 `device_id` 一并提交给 `/auth/login`。

### 影响

- 已经设置过设备 ID 的浏览器，在重新登录时后端拿不到设备标识。
- 设备会话归属、设备数限制、按设备统计等逻辑会少一段关键输入。
- 这是登录按钮与后端登录接口之间的参数脱节，不是后端认证本身的问题。

### 修复方式

- 调整 [login.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/login.html)，登录时优先读取本地 `device_id` 并随请求一起提交。
- 保持“先登录，再弹窗设置 ID”的现有交互：如果本地还没有 `device_id`，仍允许先登录，登录后再在业务页触发设置弹窗。

### 验证

- `pytest -q tests/test_bug_fixes.py -k login_page_submits_device_id`

### 15. 后台 Dashboard / 用户管理 / 中奖管理页存在脚本语法损坏

### 问题

后台多个页面模板中的内联 JavaScript 出现了字符串和注释被编码残留破坏的情况，导致脚本在浏览器解析阶段直接失败。

本轮实际定位到的页面包括：

- [dashboard.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/admin/dashboard.html)
- [users.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/admin/users.html)
- [winning.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/admin/winning.html)

### 影响

- 页面能打开，但按钮和交互逻辑可能完全不执行。
- 典型症状包括：
  - “强制下线”按钮点了没反应
  - 用户管理页整页脚本初始化失败
  - 中奖页“标记已检查”“上传结果文件”“重算”等按钮失效

### 修复方式

- 修正坏掉的字符串字面量和提示文案。
- 修正用户管理页中损坏的彩种数组，改为从 `/admin/api/lottery-types` 动态加载。
- 修正后台几个页面中被编码残留破坏的确认框、提示框和请求逻辑。

### 验证

- 使用 `node --check` 对以下页面的提取脚本进行语法检查：
  - `templates/admin/dashboard.html`
  - `templates/admin/users.html`
  - `templates/admin/winning.html`

### 16. 客户端首页脚本存在成片断句，导致多个按钮逻辑失效

### 问题

[dashboard.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/client/dashboard.html) 的客户端脚本中，多个注释和字符串被拼到同一行，导致：

- 心跳逻辑语法错误
- A 模式下一张冷却逻辑损坏
- B 模式下载与完成确认逻辑损坏
- 中奖记录筛选逻辑损坏
- 改密码和中奖图片上传逻辑存在坏字符串/坏模板字面量

### 影响

- 客户端首页脚本可能直接解析失败，导致整页交互失效。
- 即使部分功能勉强执行，也会出现状态字段缺失、按钮点击无响应、请求路径构造错误等问题。

### 修复方式

- 重建损坏的数据字段定义。
- 修复心跳、冷却、B 模式下载、中奖筛选、导出、改密、图片上传等方法中的断句。
- 将几处容易被 shell/编码破坏的模板字面量改为普通字符串拼接。

### 验证

- 使用 `node --check` 对 [dashboard.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/client/dashboard.html) 提取脚本做语法检查。

### 17. 登录页脚本存在未闭合模板字符串

### 问题

[login.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/login.html) 中，登录失败提示的模板字符串未正确闭合。

### 影响

- 登录页脚本可能在解析阶段直接中断。
- 用户会看到登录按钮无效或前端完全无响应。

### 修复方式

- 修正登录失败和网络错误提示字符串。
- 保留“登录时带已有 `device_id`，未设置则登录后再补录”的交互逻辑。

### 验证

- 使用 `node --check` 对 [login.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/login.html) 提取脚本做语法检查。

### 18. 后台中奖页汇总栏缺少 `tax/missing` 数据绑定

### 问题

后台中奖页 [winning.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/admin/winning.html) 顶部汇总栏显示了“税额合计”和“未上传图片数”，但前端只从接口响应里读取了 `amount/count`，没有读取 `tax/missing`。

### 影响

- 页面汇总栏展示不完整或显示为错误值。
- 管理员看到的中奖页总览与后端真实统计不一致。

### 修复方式

- 在 [admin.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/admin.py) 的 `/admin/api/winning` 响应中补充 `summary.missing`。
- 在 [winning.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/admin/winning.html) 中补充 `summaryTax`、`summaryMissing` 状态接收与赋值。

### 验证

- `pytest -q tests/test_bug_fixes.py -k summary_tax_and_missing`

### 19. 后台中奖页导出未携带“已检查/未检查”筛选条件

### 问题

后台中奖页点击“导出”时，前端原先只传了：

- `username`
- `date`
- `lottery_type`
- `image_filter`

但没有传 `checked_status`。

同时后端 [admin.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/admin.py) 的 `/admin/api/winning/export` 也没有处理 `checked_status`。

### 影响

- 页面当前筛选的是“已检查”或“未检查”时，导出结果仍会混入另一类数据。
- 管理员以为导出的是“当前筛选结果”，实际不是。

### 修复方式

- 更新 [winning.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/admin/winning.html)，导出时追加 `checked_status`。
- 更新 [admin.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/admin.py)，让导出接口按 `checked_status` 做同样的过滤。

### 验证

- `pytest -q tests/test_bug_fixes.py -k preserves_checked_filter`
- `pytest -q tests/test_bug_fixes.py -k honors_checked_status_filter`

## 本次验证结论

本轮没有复现新的阻断性功能 bug。

- `pytest -q`：`17 passed, 1 skipped, 12 warnings`
- Flask 应用创建烟雾测试：通过
- 静态检查：未执行完成，当前环境缺少 `ruff` 和 `pyright`

## 已执行检查

### 1. 自动化测试

执行命令：

```bash
pytest -q
```

结果：

```text
17 passed, 1 skipped, 12 warnings
```

说明：

- 当前回归测试集整体通过。
- `1 skipped` 来自需要额外环境条件的用例，不属于当前默认回归失败。

### 2. 应用启动烟雾测试

执行方式：

```python
from app import create_app
app = create_app()
print(app.config.get("SQLALCHEMY_DATABASE_URI"))
```

结果：

- 应用对象可正常创建。
- 当前数据库路径解析为：
  `sqlite:///C:/Users/徐逸飞/Desktop/file-hub/instance/lottery_dev.db`

启动日志中发现以下非阻断告警：

```text
Redis unavailable (fallback to DB-only mode): Timeout connecting to server
```

说明：

- 这表示当前环境下 Redis 不可用，系统已退回 DB-only 模式。
- 若项目依赖 Redis 的实时能力或缓存能力，建议单独验证 Redis 服务状态。

### 3. 静态检查尝试

执行命令：

```bash
ruff check .
pyright .
```

结果：

- 当前环境未安装 `ruff`
- 当前环境未安装 `pyright`

因此本轮未完成 lint / type check。

## 本轮发现的问题

### 1. SQLAlchemy 2.x 兼容性风险

虽然测试全部通过，但测试过程中出现了 12 条 `LegacyAPIWarning`，核心原因是项目仍在使用 `Query.get()`。

已确认的典型位置包括：

- `services/mode_a_service.py`
- `services/ticket_pool.py`
- `tasks/expire_tickets.py`
- `models/user.py`
- `routes/winning.py`
- `services/mode_b_service.py`
- `services/file_parser.py`
- `services/winning_calc_service.py`
- `routes/admin.py`

风险说明：

- `Query.get()` 在 SQLAlchemy 2.x 中已被标记为 legacy API。
- 目前只是告警，不影响现有测试通过。
- 后续升级依赖或收紧告警策略时，可能演变为实际兼容性问题。

建议修复方向：

- 逐步替换为 `db.session.get(Model, id)`。

### 2. 文档文件存在编码问题

原始 `docs/bug-fix-log-2026-03-30.md` 内容存在明显乱码和重复段落。

本次已直接重写为 UTF-8 正常文本，避免后续继续在损坏内容上追加记录。

## 当前结论

从本轮可执行测试看：

- 没有发现新的可直接复现的功能性 bug
- 当前主要风险是：
  - Redis 服务不可用时的降级运行
  - SQLAlchemy `Query.get()` 的遗留 API 告警
  - 本机缺少 `ruff` / `pyright`，静态检查链路未闭环

## 后续建议

1. 安装并执行 `ruff`、`pyright`，补齐静态检查。
2. 批量替换项目中的 `Query.get()`，消除 SQLAlchemy 2.x 遗留告警。
3. 如果生产环境依赖 Redis，单独验证 Redis 连接、超时和降级行为是否符合预期。

## 2026-03-30 补充修复记录

### 1. 后台上传页交互修复

- `templates/admin/upload.html`：
  - 将“导出CSV”按钮文案修正为“导出XLSX”，与 `/admin/api/tickets/export-by-date` 的真实返回格式一致。
  - 修复详情弹窗只拉取前 100 条票记录的问题，改为按页拉全量详情，避免大文件被静默截断。

对应回归：

- `node --check` 校验上传页内联脚本通过
- `pytest -q tests/test_bug_fixes.py -k "admin_upload_template or admin_winning_export_honors_checked_status_filter"`
  - `3 passed`

### 2. 管理员上传彩果样本实测

使用样本文件：

- `C:\Users\徐逸飞\Desktop\测试\26034期彩果.txt`

实测结果：

- 管理员登录成功
- `POST /admin/match-results/upload` 返回 `200`
- 返回数据：`{'success': True, 'match_result_id': 1, 'count': 345}`
- 数据库写入成功：
  - `MatchResult` 数量：`1`
  - `ResultFile` 数量：`1`
  - `detail_period`：`26034`
  - 解析行数：`345`

结论：

- 当前“管理员上传彩果 TXT -> 解析 -> 写入赛果记录”链路可正常工作，未发现新的阻断性 bug。

### 3. 登录页乱码修复

- `templates/login.html` 原先标题、卡片头和表单标签被写成乱码，导致登录页面直接显示异常中文。
- 已恢复为正常中文文本，包括：
  - 页面标题：`登录 - 数据文件管理平台`
  - 卡片标题：`📁 数据文件管理平台`
  - 表单标签与占位符：`用户名 / 密码`

对应回归：

- `node --check` 校验登录页内联脚本通过
- `pytest -q tests/test_bug_fixes.py -k "login_page"`
  - `2 passed`

### 4. 登录后多页面乱码修复

问题现象：

- 登录后进入后台首页、用户管理、结果管理、客户端主页时，页面标题和大量静态中文文案显示为乱码或残缺文本。
- 其中部分文案已经退化成 `?`，不只是编码显示问题，还会直接影响表单占位符、按钮标题和弹窗说明的可读性。

本次修复：

- 批量恢复并校正文案：
  - `templates/admin/dashboard.html`
  - `templates/admin/users.html`
  - `templates/admin/winning.html`
  - `templates/client/dashboard.html`
- 同步修复了若干被截断的中文标签与说明，包括：
  - 后台首页统计卡片、表头、空状态文案
  - 用户管理页表头、创建用户表单、限制说明、确认提示
  - 结果管理页筛选栏、汇总栏、分页、结果上传说明、检查确认提示
  - 客户端主页的 A/B 模式说明、中奖记录面板、改密弹窗、图片预览按钮等

额外处理：

- `templates/admin/users.html` 将强制下线确认提示改成中文。
- `templates/admin/winning.html` 将“标记已检查”确认提示改成中文。

对应回归：

- 四个页面内联脚本 `node --check` 全部通过：
  - `templates/admin/dashboard.html`
  - `templates/admin/users.html`
  - `templates/admin/winning.html`
  - `templates/client/dashboard.html`
- `pytest -q tests/test_bug_fixes.py -k "readable_chinese_labels or login_page or admin_upload_template"`
  - `8 passed`

### 5. 结果管理页状态字段与已检查换图保护修复

新发现问题：

- `templates/admin/winning.html` 的 `data()` 定义里，`matchResults` 和 `uploadingImageId` 曾被损坏注释吞掉，导致页面初始状态未显式声明这两个字段。
  - 风险：赛果列表和图片上传按钮状态依赖这两个字段，页面可能出现不响应、状态不更新或行为不稳定。
- `routes/admin.py` 的 `/admin/api/winning/<ticket_id>/upload-image` 后端接口此前没有阻止“已检查中奖记录被再次换图”。
  - 风险：虽然前端按钮做了禁用，但只要直接调接口，管理员仍能绕过前端限制替换已检查图片，破坏审核一致性。

本次修复：

- `templates/admin/winning.html`
  - 补回 `matchResults`、`mrFilterDate`、`mrDateOptions`
  - 补回 `uploadingImageId`
  - 清理损坏注释，避免状态声明被吞掉
- `routes/admin.py`
  - 为后台中奖图片上传接口补充已检查保护
  - 已检查记录再次上传图片时返回 `403`

对应回归：

- `node --check templates_admin_winning.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "admin_checked_winning_record_cannot_replace_image or admin_winning_template_declares_match_results_and_uploading_state"`
  - `2 passed`

### 6. 客户端中奖图片上传在无 Pillow 环境下 500 的修复

问题现象：

- 客户端上传中奖图片时，请求命中 `/api/winning/upload-image/<ticket_id>`
- 当前环境未安装 `Pillow`，路由中的 `from PIL import Image as _Image` 直接抛出 `ModuleNotFoundError`
- 结果：接口返回 `500`，用户无法上传中奖图片

本次修复：

- 新增通用图片处理工具：
  - `utils/image_upload.py`
- 调整以下两个接口共用该工具：
  - `routes/winning.py`
  - `routes/admin.py`

新行为：

- 若环境安装了 `Pillow`
  - 继续执行压缩与统一转 JPEG
- 若环境未安装 `Pillow`
  - 自动回退为保存原始上传字节
  - 不再因为缺少 `PIL` 导致接口 500

对应回归：

- `pytest -q tests/test_bug_fixes.py -k "upload_winning_image_creates_winning_record or upload_winning_image_works_without_pillow"`
  - `2 passed`

### 7. 客户端中奖记录分组状态丢失修复

新发现问题：

- 客户端中奖记录面板支持“按日期 / 按类型”切换
- 但在切到“按类型”之后，只要执行筛选或重新打开面板，前端会直接使用后端默认返回的按日期分组结果
- 结果：用户选中的分组方式会被悄悄重置，表现为按钮还是“按类型”，列表却重新按日期展示

本次修复：

- `routes/winning.py`
  - 在 `/api/winning/my` 返回结果里补充 `business_date`
- `templates/client/dashboard.html`
  - 抽出统一的 `applyWinningGrouping()`
  - 打开面板、筛选后统一基于 `_winningAll` 和当前 `winningGroupBy` 重新分组
  - “按日期”分组改为使用后端返回的 `business_date`，避免直接拿 `completed_at.substring(0, 10)` 导致业务日分组偏差

顺手修正：

- 客户端中奖记录、导出、改密、图片上传中的多处英文提示改为中文

对应回归：

- `node --check templates_client_dashboard.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "client_dashboard_preserves_winning_group_mode_after_filter or my_winning_returns_business_date or upload_winning_image_works_without_pillow"`
  - `3 passed`

### 8. 依赖清单补漏

检查结果：

- `requirements.txt` 确实遗漏了两个运行期依赖：
  - `Pillow`
  - `openpyxl`

原因：

- `Pillow`
  - 用于中奖图片上传时的压缩与格式转换
  - 虽然当前代码已支持“无 Pillow 回退原图保存”，但正常部署仍建议安装
- `openpyxl`
  - 用于多处 XLSX 导出接口
  - 若缺失，后台导出和客户端导出会直接失败

本次修复：

- `requirements.txt`
  - 新增 `Pillow==10.4.0`
  - 新增 `openpyxl==3.1.5`

补充说明：

- 代码库里还有一些仅测试脚本/桌面自动化脚本使用的第三方库（如 `requests`、`pywinauto`、`pyautogui`、`pyperclip`）
- 这些目前不是 Web 应用主运行链路的硬依赖，因此未并入本次主 `requirements.txt`

### 9. 管理员用户管理接口权限边界修复

新发现问题：

- 用户管理页面前端虽然只展示普通用户
- 但后台接口此前没有阻止直接对管理员账号发起：
  - 更新
  - 删除
  - 强制下线
- 也就是说，绕过页面直接调 `/admin/api/users/<id>` 系列接口，仍可能误操作管理员账户

本次修复：

- `routes/admin.py`
  - `PUT /admin/api/users/<id>`：禁止修改管理员账号
  - `DELETE /admin/api/users/<id>`：禁止删除管理员账号
  - `POST /admin/api/users/<id>/force-logout`：禁止强制下线管理员账号
- `templates/admin/users.html`
  - 补齐并中文化相关提示文案

对应回归：

- `node --check templates_admin_users.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "admin_user_management_endpoints_reject_admin_targets or admin_users_template_uses_readable_chinese_labels"`
  - `2 passed`

### 10. 用户管理失败无提示与改密弹窗定时器修复

新发现问题：

- `templates/admin/users.html`
  - 用户资料联动更新原先是直接发请求，不校验返回结果
  - 一旦后端校验失败，页面不会提示，也不会回滚输入值，管理员容易误以为修改已成功
- `templates/client/dashboard.html`
  - 改密成功后使用 `setTimeout` 延迟关闭弹窗
  - 旧定时器未清理时，若用户短时间内再次打开改密弹窗，可能被上一次成功后的定时器误关掉

本次修复：

- `templates/admin/users.html`
  - `updateUser(u)` 增加失败提示
  - 更新失败时恢复原值并重新拉取列表
  - 创建用户前端校验提示改为中文
- `templates/client/dashboard.html`
  - 新增 `pwdSuccessTimer`
  - 重新打开改密弹窗前清理旧定时器
  - 组件卸载前清理定时器，避免残留关闭动作

对应回归：

- `node --check templates_admin_users.html.js`
  - 通过
- `node --check templates_client_dashboard.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "admin_users_template_handles_update_failures or client_dashboard_clears_password_success_timer_before_reopen or admin_users_template_uses_readable_chinese_labels"`
  - `3 passed`

### 11. 管理后台踢人失败静默与客户端重复提示修复

新发现问题：

- `templates/admin/dashboard.html`
  - 仪表盘“踢出”按钮只处理成功分支
  - 一旦接口失败或网络异常，页面不会提示任何错误，属于静默失败
- `templates/client/dashboard.html`
  - `nextTicket()` 在“无票可取”分支里重复调用了两次相同的 `showToast`
  - 结果：用户会连续看到两条完全相同的“无票”提示

本次修复：

- `templates/admin/dashboard.html`
  - 踢人按钮增加失败提示和异常捕获
  - 成功提示改为中文
- `templates/client/dashboard.html`
  - 删除重复的“无票可取”提示调用，保留单次提示

对应回归：

- `node --check templates_admin_dashboard.html.js`
  - 通过
- `node --check templates_client_dashboard.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "admin_dashboard_template_uses_readable_chinese_labels or client_dashboard_only_shows_no_ticket_toast_once or client_dashboard_clears_password_success_timer_before_reopen"`
  - `3 passed`

### 12. 设置页失败静默与 B 模式确认零完成误判成功修复

新发现问题：

- `templates/admin/settings.html`
  - 设置页保存逻辑此前只处理成功，不处理失败返回或网络异常
  - 结果：保存失败时页面没有任何错误提示，属于静默失败
- `services/mode_b_service.py`
  - `confirm_batch()` 之前无论实际是否确认到票，都返回 `success=True`
  - 结果：当票据已被其他流程处理、或当前用户无权确认时，前端仍会误以为“确认成功”
- `templates/client/dashboard.html`
  - B 模式确认按钮此前只判断 `data.success`
  - 没有把“零完成”的失败信息反馈给用户

本次修复：

- `templates/admin/settings.html`
  - 新增 `error` 状态
  - 保存失败和网络异常时显示错误提示
- `services/mode_b_service.py`
  - 当 `completed_count == 0` 时返回失败结果与明确错误信息
- `templates/client/dashboard.html`
  - B 模式下载成功后展示服务端的 `adjustment_message`
  - B 模式确认失败时显示错误提示
  - 确认成功后使用服务端返回的 `completed_count` 展示完成数量

对应回归：

- `node --check templates_admin_settings.html.js`
  - 通过
- `node --check templates_client_dashboard.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "admin_settings_template_handles_save_failures or mode_b_confirm_returns_error_when_nothing_completed or client_dashboard_handles_mode_b_confirm_failure"`
  - `3 passed`

### 13. B 模式非法张数参数 500 风险与设置页加载失败兜底修复

新发现问题：

- `routes/mode_b.py`
  - `/api/mode-b/preview` 和 `/api/mode-b/download` 之前直接 `int(...)`
  - 如果请求参数是非法值，例如：
    - `count=abc`
    - `count=0`
  - 接口可能抛异常或落入不合理边界，属于明显的参数校验缺失
- `templates/admin/settings.html`
  - 设置页初始化加载若失败，之前没有任何错误提示
  - 管理员只会看到空状态，无法判断是接口失败还是数据为空

本次修复：

- `routes/mode_b.py`
  - 新增统一的下载张数解析函数
  - 非法张数统一返回 `400`
  - 错误信息：`下载张数必须是大于 0 的整数`
- `templates/admin/settings.html`
  - 设置页初始化加载失败时显示 `加载设置失败`

对应回归：

- `node --check templates_admin_settings.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "mode_b_preview_rejects_invalid_count or mode_b_download_rejects_invalid_count or admin_settings_template_handles_save_failures"`
  - `3 passed`

### 14. B 模式处理中列表残留与预览失败状态污染修复

新发现问题：

- `templates/client/dashboard.html`
  - `loadProcessingBatches()` 之前只会把服务器上的新批次追加到本地列表
  - 但不会删除服务器端已经不存在的旧批次
  - 结果：页面刷新后，处理中列表可能残留过期批次，和真实状态不一致
- `templates/client/dashboard.html`
  - `previewBatch()` 之前无论接口是否成功都直接 `this.bPreview = data`
  - 结果：预览失败时，错误响应也会进入 `bPreview`，污染页面状态

本次修复：

- `templates/client/dashboard.html`
  - `loadProcessingBatches()` 改为直接以服务端返回结果替换本地列表
  - `previewBatch()` 仅在成功时更新 `bPreview`
  - 失败时清空 `bPreview` 并提示 `预览失败`

对应回归：

- `node --check templates_client_dashboard.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "client_dashboard_replaces_processing_batches_from_server or client_dashboard_handles_mode_b_preview_failure or client_dashboard_handles_mode_b_confirm_failure"`
  - `3 passed`

### 15. A 模式停止接单失败误清空状态修复

新发现问题：

- `templates/client/dashboard.html`
  - A 模式“停止接单”之前不判断后端返回
  - 即使 `/api/mode-a/stop` 失败，前端也会直接清空当前票、关闭模式并重置冷却状态
  - 结果：用户会误以为已经停单成功，但服务端实际可能仍保留一张处理中票

本次修复：

- `templates/client/dashboard.html`
  - `doStop()` 改为先校验接口返回
  - 仅在后端确认成功后才清理前端状态
  - 失败时显示错误提示，不再误清空本地状态
- 顺手补齐 A 模式“下一张”链路中的中文提示与网络异常提示
- 倒计时结束文案从英文 `Closed` 改为中文 `已截止`

对应回归：

- `node --check templates_client_dashboard.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "client_dashboard_handles_mode_a_stop_failures_and_localizes_next_ticket_messages or client_dashboard_only_shows_no_ticket_toast_once"`
  - `2 passed`

### 16. 客户端导出网络失败无提示与上传页接口异常静默修复

新发现问题：

- `templates/client/dashboard.html`
  - `exportDaily()` 之前没有 `try/catch`
  - 如果下载接口发生网络异常，前端会直接抛错，用户看不到任何提示
- `templates/admin/upload.html`
  - `revokeFile()` 与 `viewDetail()` 之前都没有异常处理
  - 接口失败时页面属于静默失败，没有错误反馈

本次修复：

- `templates/client/dashboard.html`
  - 为 `exportDaily()` 增加网络异常提示：`导出失败，请稍后重试`
- `templates/admin/upload.html`
  - 为撤回文件增加失败提示
  - 为加载文件详情增加失败提示

对应回归：

- `node --check templates_client_dashboard.html.js`
  - 通过
- `node --check templates_admin_upload.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "client_dashboard_handles_export_daily_network_failure or admin_upload_template_loads_all_detail_pages"`
  - `2 passed`

### 17. 结果管理上传/重算反馈优化与客户端中奖图片联动同步修复

新发现问题：

- `templates/admin/winning.html`
  - 赛果上传成功后之前固定延迟 2 秒再刷新列表，失败时也缺少本地化提示
  - 重算提交也只有简单提示，异常分支缺失
- `templates/client/dashboard.html`
  - 客户端中奖图片上传成功后只更新 `winning_image_url`
  - 如果后端返回了更完整的 `record` 信息，前端不会同步其他字段

本次修复：

- `templates/admin/winning.html`
  - 赛果上传成功提示改为中文
  - 上传成功后立即刷新赛果列表、中奖列表和筛选项
  - 重算按钮补充异常处理与中文提示
- `templates/client/dashboard.html`
  - 上传中奖图片成功后合并后端返回的 `record`，避免只更新图片 URL

对应回归：

- `node --check templates_admin_winning.html.js`
  - 通过
- `node --check templates_client_dashboard.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "admin_winning_template_uses_readable_chinese_labels or client_dashboard_merges_returned_winning_record_after_upload"`
  - `2 passed`

### 18. 上传页与用户管理页初始化失败静默修复

新发现问题：

- `templates/admin/upload.html`
  - `loadFiles()` 之前没有异常处理
  - 文件列表接口失败时，页面会一直停在 loading 状态，也没有错误提示
- `templates/admin/users.html`
  - `loadUsers()` 与 `loadLotteryTypes()` 之前都没有异常处理
  - 初始化失败时页面会静默，管理员不知道是接口失败还是页面卡死

本次修复：
- `templates/admin/upload.html`
  - 增加 `listError`
  - `loadFiles()` 改为 `try/catch/finally`
  - 失败时清空列表、重置分页、显示错误提示，并确保 `loading` 正常结束
- `templates/admin/users.html`
  - 增加 `loadError`
  - `loadUsers()` 改为 `try/catch/finally`
  - `loadLotteryTypes()` 增加失败提示
  - 初始化失败时不再静默，也不会一直卡在 loading
- `tests/test_bug_fixes.py`
  - 增加两条模板回归断言，覆盖文件列表和用户管理初始化失败分支

对应回归：
- `node --check templates_admin_users.html.js`
  - 通过
- `node --check templates_admin_upload.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "admin_users_template_handles_initial_load_failures or admin_upload_template_handles_file_list_failures"`
  - `2 passed`

### 19. 结果管理页列表与详情加载失败静默修复

新发现问题：

- `templates/admin/winning.html`
  - `loadWinning()` 之前只有 `finally` 没有 `catch`
  - 中奖记录接口失败时会保留旧数据，页面没有错误提示
- `templates/admin/winning.html`
  - `loadMatchResults()` 之前没有异常处理
  - 赛果列表接口失败时会静默失败，筛选下拉也可能残留旧数据
- `templates/admin/winning.html`
  - `viewResultDetail()` 之前也没有失败提示
  - 赛果详情接口异常时只会弹空面板，看起来像按钮没反应

本次修复：
- `templates/admin/winning.html`
  - `loadWinning()` 增加接口状态校验和 `catch`
  - 失败时清空中奖记录、汇总和分页信息，并提示“加载中奖记录失败”
  - `loadMatchResults()` 增加接口状态校验和 `catch`
  - 失败时清空赛果列表和日期筛选项，并提示“加载赛果列表失败”
  - `viewResultDetail()` 增加接口状态校验和 `catch`
  - 失败时清空详情数据，并提示“加载赛果详情失败”
- `tests/test_bug_fixes.py`
  - 增加模板回归断言，覆盖这三条失败分支

对应回归：
- `node --check templates_admin_winning.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "admin_winning_template_handles_list_and_detail_load_failures"`
  - `1 passed`

### 20. 客户端 B 模式预览/确认网络异常提示修复

新发现问题：

- `templates/client/dashboard.html`
  - `previewBatch()` 之前没有 `try/catch`
  - 预览接口网络异常时会直接抛错，前端只剩控制台报错，用户无提示
- `templates/client/dashboard.html`
  - `confirmBatch()` 之前也没有 `try/catch`
  - 批次确认接口网络异常时同样会静默失败，看起来像按钮失效

本次修复：
- `templates/client/dashboard.html`
  - `previewBatch()` 增加网络异常分支
  - 异常时清空 `bPreview`，并提示“预览失败，请稍后重试”
  - `confirmBatch()` 增加网络异常分支
  - 异常时提示“确认失败，请稍后重试”
- `tests/test_bug_fixes.py`
  - 增加模板回归断言，覆盖这两个网络异常提示

对应回归：
- `node --check templates_client_dashboard.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "client_dashboard_handles_mode_b_network_failures or client_dashboard_handles_mode_b_preview_failure or client_dashboard_handles_mode_b_confirm_failure"`
  - `3 passed`

### 21. 客户端下载/中奖面板失败提示与后台仪表盘异常指示修复

新发现问题：

- `templates/client/dashboard.html`
  - `downloadBatch()` 之前没有 `catch`
  - 批量下载接口网络异常时只会停掉按钮 loading，没有任何错误提示
- `templates/client/dashboard.html`
  - `openWinning()` 之前在接口失败时只清空数据，不提示错误
  - 用户点击“中奖记录”后会看到空白面板，像是没有数据而不是请求失败
- `templates/admin/dashboard.html`
  - `refreshDashboard()` 失败时之前只写控制台
  - 后台首页看不出是实时数据为空，还是仪表盘接口已经断掉

本次修复：
- `templates/client/dashboard.html`
  - `downloadBatch()` 增加网络异常提示“下载失败，请稍后重试”
  - `openWinning()` 在接口失败和网络异常时分别提示“加载中奖记录失败”
- `templates/admin/dashboard.html`
  - `refreshDashboard()` 增加接口状态校验
  - 成功时把 `online-indicator` 恢复为“实时”
  - 失败时把 `online-indicator` 切成“连接异常”，避免后台首页无感知静默失败
- `tests/test_bug_fixes.py`
  - 增加两条模板回归断言，覆盖客户端失败提示和后台异常指示

对应回归：
- `node --check templates_client_dashboard.html.js`
  - 通过
- `node --check templates_admin_dashboard.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "client_dashboard_handles_download_and_open_winning_failures or admin_dashboard_marks_refresh_failure_in_indicator"`
  - `2 passed`

### 22. 客户端改密 HTTP 错误处理与中奖图片文件类型校验修复

新发现问题：

- `templates/client/dashboard.html`
  - `submitChangePassword()` 之前只看 `data.success`
  - 如果接口返回 4xx/5xx，但 body 仍是 JSON，前端不会先判断 `res.ok`，错误语义不够明确
- `templates/client/dashboard.html`
  - `uploadWinningImage()` 之前只校验是否选了文件
  - 用户误选非图片文件时会直接发请求，属于前端缺少基本文件类型校验

本次修复：
- `templates/client/dashboard.html`
  - `submitChangePassword()` 增加 `res.ok` 判断
  - HTTP 错误时优先展示后端错误，否则回退为“密码修改失败”
  - `uploadWinningImage()` 增加图片类型校验
  - 非图片文件会直接提示“请上传图片文件”，不再发请求
  - 上传成功分支同时要求 `res.ok && data.success`
- `tests/test_bug_fixes.py`
  - 增加模板回归断言，覆盖改密 HTTP 错误处理和图片类型校验

对应回归：
- `node --check templates_client_dashboard.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "client_dashboard_validates_winning_image_type_and_handles_password_http_errors"`
  - `1 passed`

### 23. 设置页加载状态校验与结果页筛选项失败提示补强

新发现问题：

- `templates/admin/settings.html`
  - 设置页初始化虽然有 `catch`，但之前没有先判断 `res.ok`
  - 后端若返回 4xx/5xx 且 body 仍为 JSON，前端会把错误响应当成正常设置对象继续使用
- `templates/admin/winning.html`
  - `loadFilterOptions()` 之前失败时完全静默
  - 结果页筛选项接口异常时，下拉会残留旧数据，页面也不给任何提示
- `templates/admin/winning.html`
  - “标记已检查”成功提示之前仍残留英文/乱码文案

本次修复：
- `templates/admin/settings.html`
  - 设置页加载增加 `res.ok` / `data.success` 校验
- `templates/admin/winning.html`
  - `loadFilterOptions()` 增加接口状态校验
  - 失败时清空筛选项并提示错误，不再静默
  - “标记已检查”成功提示链路已改到中文分支
- `tests/test_bug_fixes.py`
  - 增加两条模板回归断言，覆盖设置页加载状态校验和结果页筛选项失败处理

对应回归：
- `node --check templates_admin_settings.html.js`
  - 通过
- `node --check templates_admin_winning.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "admin_settings_template_checks_http_status_on_load or admin_winning_template_handles_filter_option_failures_and_localizes_mark_checked"`
  - `2 passed`

### 24. 设置页保存分支补充 HTTP 状态校验

新发现问题：

- `templates/admin/settings.html`
  - 设置页保存之前虽然有失败分支，但只判断 `data.success`
  - 如果后端返回 4xx/5xx 且 body 仍是 JSON，前端会把这类失败响应继续按成功路径判断

本次修复：
- `templates/admin/settings.html`
  - `saveSettings()` 成功分支改为 `if (res.ok && data.success)`
  - 非 2xx 响应会稳定落入原有错误分支，不再误判为保存成功
- `tests/test_bug_fixes.py`
  - 在设置页模板断言里补充这一条件检查

对应回归：
- `node --check templates_admin_settings.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "admin_settings_template_checks_http_status_on_load"`
  - `1 passed`

### 25. 用户管理页整体收口重写与按钮异常分支补齐

新发现问题：

- `templates/admin/users.html`
  - 模板局部仍有旧乱码残留，部分按钮链路不稳定
  - `createUser()`、`saveBlockedTypes()`、`forceLogout()`、`resetPassword()`、`deleteUser()` 的异常处理不一致
  - 管理员主动点击这些按钮时，网络异常分支容易静默或提示不完整

本次修复：
- `templates/admin/users.html`
  - 直接按当前逻辑整体重写为干净版本
  - 保留现有用户管理能力：加载用户、加载彩种、更新用户、创建用户、禁止彩种、强制下线、重置密码、删除用户
  - 所有管理员主动点击链统一补齐网络异常处理
  - 初始化错误、动作错误、中文提示统一收口
- `tests/test_bug_fixes.py`
  - 增加模板回归断言，覆盖用户管理动作类网络异常分支

对应回归：
- `node --check templates_admin_users.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "admin_users_template_handles_action_network_failures or admin_users_template_handles_initial_load_failures or admin_users_template_uses_readable_chinese_labels"`
  - `3 passed`

### 26. 客户端后台加载失败时清理过期状态

新发现问题：

- `templates/client/dashboard.html`
  - `loadStats()` 之前在异常分支里直接静默
  - 请求失败时页面会继续显示旧统计，用户看不出数据已经失效
- `templates/client/dashboard.html`
  - `loadProcessingBatches()`、`loadPoolStatus()` 之前也都是静默 `catch`
  - B 模式处理中列表和票池状态在接口失败时会保留旧数据，形成误导

本次修复：
- `templates/client/dashboard.html`
  - `loadStats()` 失败时重置统计数据
  - `loadProcessingBatches()` 失败时清空处理中批次
  - `loadPoolStatus()` 失败时清空票池状态
  - 这样接口异常时页面不会继续显示过期状态
- `tests/test_bug_fixes.py`
  - 增加模板回归断言，覆盖这三处状态清理

对应回归：
- `node --check templates_client_dashboard.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "client_dashboard_clears_stale_state_when_background_loads_fail"`
  - `1 passed`

### 27. 编码残留与英文提示继续清理

新发现问题：

- 终端里仍能看到部分模板显示为乱码，但核查后发现多数是 Windows 控制台编码问题，不是文件本身坏掉
- 真正还残留在模板里的问题，主要集中在少量后台管理页提示文案：
  - 结果页筛选项失败提示存在坏串
  - 结果页“标记已检查”成功提示存在坏串
  - 后台仪表盘刷新失败提示仍是英文/占位坏串

本次修复：
- `templates/admin/winning.html`
  - 清理结果页筛选项加载失败提示坏串
  - 清理“标记已检查”成功提示坏串
- `templates/admin/dashboard.html`
  - 仪表盘刷新失败提示改到中文分支
- `tests/test_bug_fixes.py`
  - 针对中文化修复补了结构级断言，避免 Windows 控制台编码影响回归稳定性

对应回归：
- `node --check templates_admin_winning.html.js`
  - 通过
- `node --check templates_admin_dashboard.html.js`
  - 通过
- `node --check templates_admin_settings.html.js`
  - 通过
- `pytest -q tests/test_bug_fixes.py -k "templates_use_chinese_for_recent_admin_prompt_fixes or admin_dashboard_marks_refresh_failure_in_indicator"`
  - `2 passed`

### 28. 数据库信息迁移到设置页并继续清理中文提示

新发现问题：

- `routes/admin.py`
  - 数据库信息已经迁到设置页展示，但后台首页路由仍继续透传 `database_info`
  - 这段数据对当前首页模板已经没有实际用途，属于残留上下文
- `templates/login.html`
  - 登录失败的解析异常、普通失败、网络异常提示仍残留英文
  - 与当前项目其余页面的中文提示风格不一致

本次修复：
- `routes/admin.py`
  - 后台首页渲染改为直接返回 `admin/dashboard.html`
  - 数据库信息只保留在设置接口 `/admin/api/settings` 中提供
- `templates/login.html`
  - 将 `Login failed (HTTP ...)` 改为 `登录失败（HTTP ...）`
  - 将 `Login failed` 改为 `登录失败`
  - 将 `Network error, please retry` 改为 `网络异常，请稍后重试`
- `tests/test_bug_fixes.py`
  - 补充数据库信息迁移后的后台首页路由断言
  - 补充登录页剩余英文错误提示的中文化断言

对应回归：
- `pytest -q tests/test_bug_fixes.py -k "database_info_moves_to_settings_page or admin_settings_api_includes_database_info or templates_use_chinese_for_recent_admin_prompt_fixes"`
  - `3 passed`
- `node --check templates_login.html.js`
  - 通过
- `node --check templates_admin_settings.html.js`
  - 通过
- `node --check templates_admin_dashboard.html.js`
  - 通过
