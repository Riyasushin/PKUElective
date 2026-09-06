# 实测记录：2026-09-06

当天使用 `--once` 成功补选机器学习（04833420，班号 1，信息科学技术学院），随后重新登录确认“已选上”。没有执行退课。这是当时的测试记录，不是实时课表。

## 环境

Python 3.14.0，依赖按原有 `uv.lock` 安装：

```sh
uv sync --locked --python python3.14
```

测试使用独立配置 `/private/tmp/pkuelective-test.ini`，正式 `config.ini` 的体系结构目标保持不变。个人配置和 TT 凭据当时均为 0600 权限，并被 Git 忽略。临时配置不随仓库提供；复现时请用自己的配置路径。

## 实际过程

最初的浏览器快照把目标放在第 3 页。程序直接登录后，在第 1 页找到它，因此测试配置改为第 1 页。

第一次尝试停在 `RecognizerError`，没有提交补选。具体原因未保留，不能断言是账号、余额或服务故障。增加脱敏错误说明后再次尝试，成功完成：

```sh
.venv/bin/python -u main.py --once --captcha-attempts 3 -c /private/tmp/pkuelective-test.ini
```

```text
IAAA and elective login completed
Target: 机器学习; page=1; quota=(180, 154)
Captcha validation attempt 1: 2
Submitting target once
Verified target state: 已选上
Result: elected
```

退出码为 0。然后另起进程重新登录，用 `--check` 复核：

```text
IAAA and elective login completed
Target state: 已选上
Result: already_elected
```

复核退出码也是 0。成功依据是服务器已选表中的明确状态，不只是提交成功提示。两次实测尝试中，只有第二次到达补选提交。

## 验证了什么

| 范围 | 结果 |
| --- | --- |
| IAAA 与选课系统登录 | 通过 |
| 列表读取、页码和目标匹配 | 通过；测试目标实际在第 1 页 |
| TT 识图与学校验证码校验 | 成功那次在第 1 次校验通过，类型为 1003 |
| 补选与结果确认 | 提交一次；提交后和独立登录后都确认已选上 |
| 离线测试 | 12 项通过，覆盖成功、满额、已选、候补、假成功、超时核对、验证码上限、识别状态及链接重试 |
| 长期轮询、双学位、候补阶段 | 尚未完整验证 |

离线测试命令：

```sh
.venv/bin/python -m unittest discover -s tests -v
```

修复清单和剩余问题见[问题与修复状态](REPO_AUDIT_2026-09-06.md)。这次验收针对机器学习的单次流程，没有实际补选体系结构，也不能替代长期轮询测试。
