# PKUAutoElective

北京大学补退选助手：查询选课计划中的课程，有名额时尝试补选。目标课程需要先在网页上加入“选课计划”；程序不会自动添加计划或退课。

2026-09-06 已用“机器学习”完成真实补选，并重新登录确认“已选上”。长期轮询、双学位和候补阶段还没有完整验证，详见[实测记录](RUN_VALIDATION_2026-09-06.md)。

## 安装

需要 Python 3.13 及以上、uv。在仓库目录运行：

```sh
uv sync --locked
```

仓库的 `.python-version` 指定 3.13。本次实测使用已安装的 Python 3.14，可显式选择：

```sh
uv sync --locked --python python3.14
```

下面命令使用 macOS / Linux 的 `.venv/bin/python`，确保运行的是刚装好依赖的环境。

## 配置

首次使用时复制样例；已有配置就直接编辑，不要覆盖：

```sh
cp config.sample.ini config.ini
cp apikey.sample.json apikey.json
chmod 600 config.ini apikey.json
```

在 `config.ini` 中修改账号、页码，再添加目标课程。以下只是需要修改的部分，其他配置保留样例值：

```ini
[user]
student_id = 你的学号
password = 你的选课密码
dual_degree = false
identity = bzx

[client]
supply_cancel_page = 1

[course:architecture]
name = 计算机组织与体系结构
class = 1
school = 信息科学技术学院
```

- `name`、`class`、`school` 对应网页上的课程名、班号、开课单位，须与页面一致。班号 `01` 和 `1` 等价。
- `[course:architecture]` 中的 `architecture` 是你起的标识。写成课程号也可以，但程序实际仍按上述三个字段匹配。
- `supply_cancel_page` 是目标在可选列表中的页码，从 1 开始。页码可能变化，找不到课程时先核对页面。
- 需要选择主修/辅双身份的账号，设置 `dual_degree = true`；`identity` 为 `bzx`（主修）或 `bfx`（辅双）。

在 `apikey.json` 中填写 TT 识图账号，注意它与学校账号是两套凭据：

```json
{
  "username": "你的TT识图账号",
  "password": "你的TT识图密码",
  "RecognitionTypeid": "1003",
  "Timeout": "15"
}
```

`RecognitionTypeid` 是识别类型，`Timeout` 是请求超时秒数。本次实测使用 `1003`。每张验证码调用一次识别服务；服务可能产生费用。只读查询不需要这份凭据。

两个个人配置文件已被 Git 忽略。INI 注释放在独立行，避免把注释读成配置值。

## 运行

先查一次，确认账号、课程和页码正确：

```sh
.venv/bin/python main.py --check -c config.ini
```

需要尝试一次真实补选时运行：

```sh
.venv/bin/python main.py --once --captcha-attempts 3 -c config.ini
```

需要持续等待空位时运行：

```sh
.venv/bin/python -u main.py -c config.ini
```

| 模式 | 行为 |
| --- | --- |
| `--check` | 登录、查询，然后退出；不识别验证码、不提交 |
| `--once` | 有名额才识别验证码，最多提交一次，再查询是否选上 |
| 不加上述参数 | 持续轮询，有名额时尝试补选；前台按 `Ctrl+C` 停止 |

`--check` 和 `--once` 每次只支持一门配置课程。轮询支持多门目标和互斥规则，但可选目标必须在同一配置页，尚不支持自动跨页查找。配置修改后需要重启进程才会生效。

`--once` 默认最多尝试 3 次验证码，可设为 1–15；这个参数不控制轮询模式。`--once` 遇到提交超时会先查已选状态，不直接重发。

### 读懂结果

| 输出 | 含义 |
| --- | --- |
| `available` / `full` | 有余量 / 已满；`available` 不代表已经选上 |
| `elected` | 本次提交后查询确认已选上 |
| `already_elected` | 查询发现已经选上，不再提交 |
| `pending` | 已出现在状态表中，但状态不是“已选上”，例如候补 |
| `delayed` | 还没达到配置的延迟阈值 |
| `Failed: …` | 出错，后面是异常类型；识别错误会附脱敏说明 |

`--once` 退出码：选上为 `0`，满额/延迟/候补为 `2`，异常为 `1`。`--check` 正常完成查询为 `0`，即使课程已满。课程缺失或页面解析失败会报错。

### 常见问题

- **找不到课程**：先确认已加入选课计划，再检查页码和三个匹配字段。
- **`RecognizerError`**：检查 TT 账号、余额、识别类型和错误说明。不能仅凭这一异常判断具体原因。
- **有余量却选不上**：开课阶段、院系权限、时间冲突等仍由学校系统判断。
- **进程还在但日志不动**：可能是请求等待或工作线程退出。旧轮询主进程不会可靠地随工作线程结束而退出，不能只看 PID 判断运行正常。

## 可选设置

普通使用可以保留样例默认值：

| 设置 | 什么时候需要改 |
| --- | --- |
| `refresh_interval`、`random_deviation` | 控制每轮结束后的等待；默认 normal 以 8 秒为中心波动，整轮还包含请求等耗时 |
| `mutex:*` | 几门课只选一门时使用；已选中其中一门后忽略其他目标，不会退课 |
| `delay:*` | 仅在剩余名额小于等于阈值时尝试；不想刻意推迟就不要配 |
| `monitor` | 轮询加 `-m` 后启用本机状态服务，默认 `127.0.0.1:7074`，可看 `/stat/loop` |
| `notification` | 可选推送，默认关闭；服务未重新验证 |

保留 `debug_print_request = false` 和 `debug_dump_request = false`；现有详细请求日志仍可能包含认证信息。

## 测试与维护

离线测试不会登录或选课：

```sh
.venv/bin/python -m unittest discover -s tests -v
```

- [代码怎么工作](IMPLEMENTATION_GUIDE.md)：入口、请求顺序、两个运行模式的差别。
- [问题与修复状态](REPO_AUDIT_2026-09-06.md)：配置细节和还没解决的问题。
- [实测记录](RUN_VALIDATION_2026-09-06.md)：实际输出和验证范围。

本项目基于 [zhongxinghong/PKUAutoElective](https://github.com/zhongxinghong/PKUAutoElective)，感谢原作者及 Mzhhh、KingOfDeBug 等贡献者。旧版本说明可在 Git 历史中查看。
