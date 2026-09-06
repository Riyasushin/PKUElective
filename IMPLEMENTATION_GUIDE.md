# 代码怎么工作

程序有两个入口：`--check` / `--once` 用来查询或尝试一门课；不加参数则进入旧的持续轮询。它们共享登录客户端、页面解析器和验证码实现，但控制流程不同。

## 从哪里读代码

| 文件 | 负责什么 |
| --- | --- |
| `main.py`、`autoelective/cli.py` | 读取参数，选择一次执行或线程轮询 |
| `autoelective/workflow.py` | `--check` / `--once` 的完整流程和结果确认 |
| `autoelective/loop.py` | 登录会话维护、持续查询、优先级和互斥/延迟规则 |
| `autoelective/iaaa.py` | 向 IAAA 登录，取得 token |
| `autoelective/elective.py` | 选课系统 SSO、列表、验证码及补选请求 |
| `autoelective/client.py` | requests Session、Cookie、超时和重试 |
| `autoelective/parser.py`、`course.py` | 读表格，以课程名、班号、开课单位匹配课程 |
| `autoelective/captcha/online.py`、`proxy.py` | 单次识别请求，返回 `Captcha`；proxy 只保留兼容类名 |
| `autoelective/hook.py` | 按页面标题、提示文字判断服务器返回结果 |
| `autoelective/config.py` | 读取 INI、目标课程和规则 |
| `autoelective/monitor.py`、`notification/` | 可选状态服务和推送 |

## 一次执行的顺序

`workflow.run_once()` 按以下顺序运行：

1. 检查配置中恰好有一门课，页码为正数。
2. 访问 IAAA，提交登录信息，拿 token 登录选课系统；需要时切换主修/辅双身份。
3. 先访问补退选首页；配置页不是第 1 页时，再取指定页。
4. 按“补选”和“选课状态”表头找到可选表、已选表。
5. 如果目标已出现在状态表，返回 `already_elected` 或 `pending`，不再提交。
6. 在可选表中找目标，读取上限和已选人数。`--check` 到这里结束。
7. `--once` 检查余量和 delay 规则，获取验证码，调用 TT 识图，再向学校验证。
8. 校验通过后只提交一次补选请求，然后重新查询已选表。

只有状态明确为“已选上”，才返回 `elected`。成功提示、HTTP 200、候补记录都不能单独当作选上。提交超时时也先查询：若已选上就返回成功，否则报错，不自动重发。

`--once` 没有定时轮询。满额、延迟或候补会返回非成功结果；验证码达到次数上限会报错退出。

## 请求地址

选课接口公共前缀为 `/elective2008/edu/pku/stu/elective/controller/`。以下是代码当前使用的路径，不表示所有入口和学期均已验证。

| 步骤 | 方法与路径 |
| --- | --- |
| IAAA 登录页 | `GET iaaa.pku.edu.cn/iaaa/oauth.jsp` |
| IAAA 登录 | `POST iaaa.pku.edu.cn/iaaa/oauthlogin.do` |
| 选课系统 SSO | `GET elective.pku.edu.cn/elective2008/ssoLogin.do` |
| 补退选首页 | `GET supplement/SupplyCancel.do`，带 `xh` |
| 后续页 | `GET supplement/supplement.jsp`，带 `xh` 和分页参数 |
| 验证码图片 | `GET /elective2008/DrawServlet` |
| 验证码校验 | `POST supplement/validate.do`，带 `xh`、`validCode` |
| 补选 | `GET supplement/electSupplement.do`，使用页面返回的链接参数 |

后续页每页 20 条，`netui_row=electableListGrid;40` 表示偏移 40 条，即第 3 页。不要把 40 当页码，也不要自己编造补选索引。

补选虽然是 GET，却会改变选课结果。因此客户端单独关闭它的自动重试，并校验链接必须指向本站的补选路径。登录 POST、验证码校验也使用零重试适配器；普通列表 GET 仍有网络重试。

## 验证码

当前流程很直接：图片 → TT 识图 → `Captcha.code` → 学校校验。

- 请求 `https://api.ttshitu.com/base64`，使用 `apikey.json` 的账号、类型和超时。
- 每次只提交一张图的一种识别请求，不再并发投票，也不积累旧结果。
- 学校校验返回 `2` 视为通过，`0` 视为失败重试；代码兼容数字和字符串。
- `--once` 默认最多 3 次，可设为 1–15；轮询代码每次进入验证码循环最多 15 次。
- 缺凭据、网络故障、服务拒绝或异常返回会报错；次数上限不意味着所有错误都会自动重试。

## 持续轮询与一次执行的差别

轮询使用两个工作线程：选课线程把失效会话放到登录队列；登录线程重新认证后把会话放回可用队列。会话池大小不是并行选课数，选课任务仍由一个线程处理。

每轮读取配置页，先跳过已选或已忽略的目标，再按 INI 中的先后顺序尝试有余量的课程：

- mutex：选中一门后忽略同组其他目标。
- delay：有余量且剩余名额不超过阈值时才尝试。
- 请求结束后再等待一个随机间隔；网络耗时和额外等待不包含在该间隔内。

轮询复用了修好的识别器、链接校验和解析函数，但仍按表格位置取表，成功/候补判断也没有完全改为 `workflow.py` 的状态判断。已完成的真实补选测试针对 `--once`，不要把它当成长时间轮询验收。

工作线程结束后，主进程仍可能停在等待中。日志和 `-m` 提供的 `/stat/loop` 比“进程是否存在”更能说明运行情况。

## 两个容易误改的地方

**Cookie 更新**：请求 hook 会用异常表达选课成功或失败。requests 可能因此来不及保存响应 Cookie，`persist_cookies()` 用于补做这一步。调整 hook 时需要保留这一行为。

**配置加载顺序**：配置和环境是单例。必须先解析 `-c` 再初始化依赖配置的模块；直接导入 `loop.py` 还会初始化日志、通知和规则状态。只读测试应从 CLI 的 `--check` 进入。

更多未完成项见[问题与修复状态](REPO_AUDIT_2026-09-06.md)，运行证据见[实测记录](RUN_VALIDATION_2026-09-06.md)。
