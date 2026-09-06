# 实际运行验收：2026-09-06

结论：完整选课链路已真实跑通。机器学习（04833420，班号 1，信息科学技术学院）已选上；没有退课操作。

## 环境和凭据

- `.venv`：Python 3.14.0，`uv sync --locked --python /opt/homebrew/bin/python3.14` 成功，依赖来自现有 uv.lock。
- `config.ini`：正式目标仍为计算机组织与体系结构（04830140，班号 1，第 1 页）。
- `/private/tmp/pkuelective-test.ini`：机器学习单独测试配置，实时查询后修正为第 1 页。
- `config.ini`、`apikey.json` 权限为 0600，已被 Git 忽略；本报告不包含凭据或会话。

## 实测证据

开始时用户提供的是第 3 页位置。直接登录服务器后，第 3 页没有目标，逐页只读查询在第 1 页找到机器学习。课程页码随列表变化，不能固定使用旧浏览器快照。

第一次真实 `--once` 在识别阶段报 RecognizerError，没有到达提交。该次具体原因未保留，不能断言是余额、凭据或识别服务问题。随后增加脱敏错误说明，再次运行成功。

成功命令：

```sh
.venv/bin/python -u main.py --once --captcha-attempts 3 -c /private/tmp/pkuelective-test.ini
```

实际输出：

```text
IAAA and elective login completed
Target: 机器学习; page=1; quota=(180, 154)
Captcha validation attempt 1: 2
Submitting target once
Verified target state: 已选上
Result: elected
```

进程退出码 0。之后独立重新登录并执行 `--check`，输出：

```text
IAAA and elective login completed
Target state: 已选上
Result: already_elected
```

复核进程退出码同样为 0。最终成功依据是两次服务器查询的“已选上”状态，不是仅凭提交响应文案。

## 修复

- 统一识别返回值为 Captcha，移除旧代理跨图片积累队列/投票及复用关闭连接的问题。
- 识别改用配置指定的一种方法，单次 POST，配置超时生效，使用 HTTPS；不再对同张图默认发三个识别请求。
- 新增单目标 `--check` 和 `--once`；验证码有限重试；补选最多提交一次；提交成功文案、超时或重复选课之后查询核实结果。
- 按表头识别表格，兼容嵌套文字、多 class、缺少操作链接，并解析选课状态；候补独立于已选上。
- 提交链接支持相对 URL，限制在本站补选路径；提交接口禁用自动重试。
- 原轮询路径同样获得识别类型修复和有限验证码重试；延迟初始化识别器；删除登录失败时明文打印密码的语句。
- 样例 burst 注释改为独立行，默认随机分布改为文档描述一致的 normal；修正 README 中 apikey 文件扩展名。

## 离线测试

`tests/test_workflow.py` 的 12 项测试通过，覆盖成功后核实、只读不提交、已选跳过、满额跳过、假成功提示、候补、提交超时后的状态核对、验证码上限、数值验证状态、连续两图不串结果、失败识别、提交 URL 及零重试。

## 边界

真实验收覆盖 `--once` 的机器学习目标。未实际补选体系结构，未开展长时间轮询稳定性测试，也未验证双学位和候补阶段。旧轮询框架中的自动重启、日志完整脱敏、多页目标发现等审计建议并未全部完成；不能据一次成功推断长期稳定。
