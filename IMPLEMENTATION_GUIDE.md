# PKU Auto-Elective 实现原理详解

## 目录

1. [系统架构概览](#1-系统架构概览)
2. [核心工作流程](#2-核心工作流程)
3. [登录认证机制](#3-登录认证机制)
4. [课程监控与选课逻辑](#4-课程监控与选课逻辑)
5. [验证码识别系统](#5-验证码识别系统)
6. [异常处理与容错机制](#6-异常处理与容错机制)
7. [配置系统与规则引擎](#7-配置系统与规则引擎)
8. [通知与监控](#8-通知与监控)

---

## 1. 系统架构概览

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        主程序入口 (cli.py)                       │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  IAAA登录线程    │  │  选课监控线程    │  │  监控服务线程    │  │
│  │ (run_iaaa_loop) │  │(run_elective_loop)│  │ (run_monitor)   │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
│           │                    │                    │          │
│           ▼                    ▼                    ▼          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  IAAAClient     │  │ ElectiveClient  │  │  Monitor Server │  │
│  │  (iaaa.py)      │  │  (elective.py)  │  │  (monitor.py)   │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│           │                    │                                │
│           └────────────┬───────┘                                │
│                        ▼                                        │
│              ┌─────────────────┐                                │
│              │  BaseClient     │                                │
│              │ (client.py)     │                                │
│              └─────────────────┘                                │
├─────────────────────────────────────────────────────────────────┤
│                        验证码识别系统                             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              RecognitionProxy (proxy.py)                │    │
│  │   ┌─────────────────┐    ┌─────────────────┐           │    │
│  │   │  TTShituRecognizer│   │   APIConfig     │           │    │
│  │   │  (online.py)    │    │  (online.py)    │           │    │
│  │   └─────────────────┘    └─────────────────┘           │    │
│  └─────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│                        辅助模块                                   │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│  │ config  │ │ parser  │ │  hook   │ │ course  │ │ logger  │   │
│  │(配置解析)│ │(HTML解析)│ │(请求钩子)│ │(课程模型)│ │(日志系统)│   │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 核心模块说明

| 模块 | 职责 |
|------|------|
| `cli.py` | 命令行入口，负责解析参数、创建线程 |
| `loop.py` | 包含两个核心循环：IAAA登录循环和选课监控循环 |
| `iaaa.py` | IAAA统一认证客户端，处理学校身份认证 |
| `elective.py` | 选课网客户端，处理所有选课相关请求 |
| `client.py` | HTTP客户端基类，封装Session管理和请求发送 |
| `captcha/` | 验证码识别模块，支持多策略并行识别 |
| `hook.py` | 请求/响应钩子，用于错误检测和日志记录 |
| `parser.py` | HTML解析器，提取课程信息和页面状态 |
| `config.py` | 配置文件解析器 |
| `course.py` | 课程数据模型 |
| `exceptions.py` | 自定义异常体系 |

---

## 2. 核心工作流程

### 2.1 双线程协作模型

系统采用**双线程架构**实现登录会话维护和选课操作的分离：

```
                    ┌─────────────────┐
                    │   程序启动       │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌─────────┐    ┌─────────┐    ┌─────────┐
        │创建Client│    │ 启动IAAA │    │ 启动选课 │
        │ 对象池   │    │ 登录线程 │    │ 监控线程 │
        └────┬────┘    └────┬────┘    └────┬────┘
             │              │              │
             ▼              ▼              ▼
    ┌────────────────────────────────────────────────┐
    │                    Client Pool                  │
    │  ┌─────────┐  ┌─────────┐  ...  ┌─────────┐    │
    │  │Client #1│  │Client #2│       │Client #n│    │
    │  │(未登录)  │  │(未登录)  │       │(未登录)  │    │
    │  └─────────┘  └─────────┘       └─────────┘    │
    └────────────────────────────────────────────────┘
                             │
                             │ 登录认证流程
                             ▼
```

### 2.2 IAAA登录线程 (`run_iaaa_loop`)

```python
def run_iaaa_loop():
    while True:
        # 1. 从reloginPool获取需要登录的客户端
        elective = reloginPool.get()
        
        # 2. 创建IAAAClient，设置随机User-Agent
        iaaa = IAAAClient(timeout=iaaa_client_timeout)
        iaaa.set_user_agent(random.choice(USER_AGENT_LIST))
        
        # 3. 请求IAAA首页获取Cookie
        iaaa.oauth_home()
        
        # 4. 发送登录请求获取token
        r = iaaa.oauth_login(username, password)
        token = r.json()["token"]
        
        # 5. 使用token登录选课网
        elective.sso_login(token)
        
        # 6. 处理双学位身份切换
        if is_dual_degree:
            sida = get_sida(r)
            elective.sso_login_dual_degree(sida, sttp, referer)
        
        # 7. 设置客户端过期时间，放入可用池
        elective.set_expired_time(...)
        electivePool.put_nowait(elective)
```

**核心职责**：
- 维护 `elective_client_pool_size` 个有效的选课会话
- 当客户端过期或失效时，重新登录并放回池中
- 每个客户端有独立的 `elective_client_max_life` 生命周期

### 2.3 选课监控线程 (`run_elective_loop`)

```python
def run_elective_loop():
    # 1. 加载配置：课程、互斥规则、延迟规则
    load_courses()
    load_mutexes()
    load_delays()
    
    while True:
        # 2. 从池子获取可用客户端
        elective = electivePool.get()
        
        # 3. 检查会话状态
        if not elective.has_logined:
            raise _ElectiveNeedsLogin  # → IAAA线程处理
        if elective.is_expired:
            raise _ElectiveExpired     # → IAAA线程处理
        
        # 4. 获取补退选页面
        r = elective.get_SupplyCancel(username)
        
        # 5. 解析HTML，提取：
        #    - elected: 已选课程列表
        #    - plans: 可选课程列表（含名额信息）
        
        # 6. 检查目标课程状态
        tasks = []
        for course in goals:
            if course in elected:
                ignore(course, "Elected")  # 已选上，忽略
            elif course in plans and course.is_available():
                tasks.append(course)        # 有名额，加入任务
        
        # 7. 执行选课
        for course in tasks:
            # 7.1 获取并验证验证码
            captcha = recognize_captcha()
            validate_captcha(captcha)
            
            # 7.2 提交选课请求
            elective.get_ElectSupplement(course.href)
            
            # 7.3 处理各种结果异常
            handle_result_exceptions()
        
        # 8. 循环间隔（支持随机偏移）
        time.sleep(_get_refresh_interval())
```

---

## 3. 登录认证机制

### 3.1 IAAA统一认证流程

```
┌──────────┐                               ┌──────────────┐
│  用户    │                               │ IAAA服务器   │
└────┬─────┘                               └──────┬───────┘
     │                                            │
     │ 1. GET /iaaa/oauth.jsp                     │
     │    (appID=syllabus, redirectUrl=...)       │
     ├────────────────────────────────────────────►
     │                                            │
     │ 2. Set-Cookie: JSESSIONID=xxx              │
     │◄────────────────────────────────────────────┤
     │                                            │
     │ 3. POST /iaaa/oauthlogin.do                │
     │    (username, password)                    │
     ├────────────────────────────────────────────►
     │                                            │
     │ 4. {"success": true, "token": "..."}       │
     │◄────────────────────────────────────────────┤
     │                                            │
```

### 3.2 选课网SSO登录

```
┌──────────┐                               ┌──────────────┐
│  程序    │                               │ 选课网服务器 │
└────┬─────┘                               └──────┬───────┘
     │                                            │
     │ 1. GET /ssoLogin.do?token=xxx              │
     │    Cookie: JSESSIONID=dummy_52_chars       │
     ├────────────────────────────────────────────►
     │    ↑ 必须携带随机生成的52字符JSESSIONID    │
     │                                            │
     │ 2. 重定向到选课首页，Set-Cookie            │
     │◄────────────────────────────────────────────┤
     │                                            │
     │ 3. GET /SupplyCancel.do                    │
     │    (补退选页面)                            │
     ├────────────────────────────────────────────►
     │                                            │
     │ 4. HTML页面 (课程列表)                     │
     │◄────────────────────────────────────────────┤
```

### 3.3 双学位身份切换

当 `dual_degree = true` 时，登录流程额外增加：

```python
# 1. SSO登录后获取sida参数
sida = get_sida(r)  # 从响应URL中提取 ?sida=xxx&sttp=bzx

# 2. 发送双学位身份切换请求
elective.sso_login_dual_degree(sida, sttp, referer)

# 3. 支持的身份："bzx"(主修) 或 "bfx"(辅双)
```

---

## 4. 课程监控与选课逻辑

### 4.1 课程数据模型

```python
class Course:
    __slots__ = ['_name', '_class_no', '_school', '_status', '_href', '_ident']
    
    @property
    def status(self) -> tuple:  # (限选人数, 已选人数)
        return self._status
    
    @property
    def remaining_quota(self) -> int:
        maxi, used = self._status
        return maxi - used
    
    def is_available(self) -> bool:
        maxi, used = self._status
        return maxi > used  # 有剩余名额
```

### 4.2 页面解析流程

```
HTML Response
     │
     ▼
┌─────────────┐
│ etree.HTML()│  ← lxml解析
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ get_tables()│  ← 提取两个datagrid表格
└──────┬──────┘
       │
       ├──────────────┐
       ▼              ▼
┌─────────────┐  ┌─────────────┐
│ tables[0]   │  │ tables[1]   │
│ (可选课程)   │  │ (已选课程)   │
└──────┬──────┘  └─────────────┘
       │
       ▼
┌─────────────────┐
│get_courses_with_│  ← 提取课程名、班号、开课单位、
│   detail()      │    名额状态(限数/已选)、补选链接
└─────────────────┘
```

### 4.3 智能选课策略

#### 优先级队列

```
配置顺序 → 优先级

course:cs1  ←── 最高优先级，先尝试
course:cs2  ←── 次优先级
course:cs3  ←── 最低优先级
```

#### 互斥规则 (Mutex)

```ini
[course:math_1]
name = 高等数学(A)
...

[course:math_2]
name = 高等数学(B)
...

[mutex:0]
courses = math_1, math_2
```

**逻辑**：`math_1` 和 `math_2` 只能选其一，一旦某门课选上，另一门自动忽略。

实现（使用numpy矩阵）：

```python
# 创建 N×N 互斥矩阵 (N = 目标课程数)
mutexes = np.zeros((N, N), dtype=np.uint8)

# 设置互斥关系
for mid, m in mutexes.items():
    for ix1, ix2 in combinations(m.cids, 2):
        mutexes[ix1, ix2] = mutexes[ix2, ix1] = 1

# 动态检查
def is_mutex(course_ix):
    for mix in np.argwhere(mutexes[course_ix, :] == 1):
        if goals[mix] in elected:
            return True
```

#### 延迟规则 (Delay)

```ini
[delay:0]
course = cs1
threshold = 10
```

**逻辑**：只有当 `cs1` 的剩余名额 `≤ 10` 时才触发选课（避免抢占早期名额，留给急需的同学）。

---

## 5. 验证码识别系统

### 5.1 系统架构

```
┌─────────────────────────────────────────────────────┐
│                 RecognitionProxy                     │
│                   (proxy.py)                         │
├─────────────────────────────────────────────────────┤
│  多策略并行识别                                       │
│  ┌───────────────────────────────────────────────┐  │
│  │   同时发起3种识别请求 (asyncio并发)              │  │
│  │                                                │  │
│  │   • typeid=3    (通用英文数字)  权重: 0.4       │  │
│  │   • typeid=1003 (英文数字优化)  权重: 0.7       │  │
│  │   • typeid=7    (无感学习模型)  权重: 1.0       │  │
│  └───────────────────────────────────────────────┘  │
│                        │                            │
│                        ▼                            │
│  ┌───────────────────────────────────────────────┐  │
│  │   加权投票机制                                   │  │
│  │   结果 = max(∑权重 × 出现次数)                  │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│               TTShituRecognizer                      │
│                (online.py)                           │
├─────────────────────────────────────────────────────┤
│  1. 图像预处理                                        │
│     • 处理GIF动图（取最后一帧）                        │
│     • 转换为RGB格式                                   │
│     • 转为JPEG并Base64编码                            │
│                                                     │
│  2. API请求                                          │
│     • 调用 TT识图 API (api.ttshitu.com)             │
│     • 用户名/密码认证                                 │
│     • 返回识别结果                                    │
└─────────────────────────────────────────────────────┘
```

### 5.2 验证码验证流程

```python
def recognize_and_validate():
    while True:
        # 1. 获取验证码图片
        r = elective.get_DrawServlet()
        image_data = r.content
        
        # 2. 并行多策略识别
        code = asyncRecognizer.recognize(image_data)
        #    - 并发调用3种typeid的识别
        #    - 加权投票得出最终结果
        
        # 3. 向服务器验证
        r = elective.get_Validate(username, code)
        result = r.json()["valid"]
        
        # 4. 结果处理
        if result == "2":
            return True   # 验证通过，可以选课
        elif result == "0":
            continue      # 验证失败，重试
```

### 5.3 容错机制

```python
RECOGNITION_METHODS = [3, 1003, 7]
RECOGNITION_WEIGHT = {3: 0.4, 1003: 0.7, 7: 1.0}

# 即使单个识别失败，其他策略仍可工作
# 加权投票降低误识别率
```

---

## 6. 异常处理与容错机制

### 6.1 异常体系架构

```
AutoElectiveException
├── UserInputException          # 用户配置错误
├── AutoElectiveClientException
│   ├── StatusCodeError         # HTTP状态码非200
│   ├── ServerError             # 5xx服务器错误
│   ├── OperationFailedError    # 操作失败
│   ├── UnexceptedHTMLFormat    # HTML解析失败
│   ├── IAAAException
│   │   ├── IAAANotSuccessError
│   │   ├── IAAAIncorrectPasswordError  # 密码错误
│   │   └── IAAAForbiddenError          # 账号被锁
│   └── ElectiveException
│       ├── SystemException
│       │   ├── CaughtCheatingError     # 被检测为刷课机
│       │   ├── SessionExpiredError     # 会话过期 → 重新登录
│       │   ├── InvalidTokenError       # Token失效 → 重新登录
│       │   └── CaptchaError            # 验证码错误 → 重试
│       └── TipsException
│           ├── ElectionSuccess         # 选课成功！
│           ├── TimeConflictError       # 时间冲突 → 忽略课程
│           ├── CreditsLimitedError     # 学分超限 → 忽略课程
│           └── QuotaLimitedError       # 名额已满 → 等待下次
```

### 6.2 会话过期自动恢复

```python
try:
    r = elective.get_SupplyCancel(username)
except (SessionExpiredError, InvalidTokenError) as e:
    # 标记客户端需要重新登录
    reloginPool.put_nowait(elective)
    elective = None
    noWait = True  # 立即切换到下一个客户端，不等待
```

### 6.3 Cookie持久化机制

```python
# 问题：当hook中抛出异常时，requests库不会执行extract_cookies_to_jar
# 导致会话Cookie丢失

# 解决方案：BaseClient.persist_cookies()
def persist_cookies(self, r):
    """在捕获异常后手动更新cookies以确保能够保持会话"""
    if r.history:
        for resp in r.history:
            extract_cookies_to_jar(self._session.cookies, resp.request, resp.raw)
    extract_cookies_to_jar(self._session.cookies, r.request, r.raw)
```

---

## 7. 配置系统与规则引擎

### 7.1 配置结构

```ini
[user]                    # 用户认证信息
[client]                  # 客户端行为配置
[monitor]                 # 监控服务配置
[notification]            # 微信通知配置
[course:xxx]              # 目标课程定义
[mutex:xxx]               # 互斥规则定义
[delay:xxx]               # 延迟规则定义
```

### 7.2 规则引擎实现

```python
class AutoElectiveConfig:
    @property
    def courses(self) -> OrderedDict:
        """解析 [course:id] 格式的所有节"""
        for id_, section in self.ns_sections('course'):
            d = self.getdict(section, ('name', 'class', 'school'))
            cs[id_] = Course(**d)
    
    @property
    def mutexes(self) -> OrderedDict:
        """解析 [mutex:id] 节，返回课程ID列表"""
        for id_, section in self.ns_sections('mutex'):
            lst = self.getlist(section, 'courses')
            ms[id_] = Mutex(lst)
    
    @property
    def delays(self) -> OrderedDict:
        """解析 [delay:id] 节，返回(课程ID, 阈值)"""
        for id_, section in self.ns_sections('delay'):
            cid = self.get(section, 'course')
            threshold = self.getint(section, 'threshold')
            ds[id_] = Delay(cid, threshold)
```

### 7.3 刷新间隔随机化

```python
def _get_refresh_interval():
    """添加随机偏移，模拟人类行为"""
    if refresh_random_deviation <= 0:
        return refresh_interval
    
    # 生成 [-deviation, +deviation] 范围内的随机数
    delta = (random.random() * 2 - 1) * refresh_random_deviation * refresh_interval
    return refresh_interval + delta

# 示例：refresh_interval=8, random_deviation=0.2
# 实际间隔：8 * (1.0 ± 0.2) = [6.4, 9.6] 秒
```

---

## 8. 通知与监控

### 8.1 微信推送系统

```
┌─────────────┐      ┌─────────────────┐      ┌─────────────┐
│  选课成功    │─────►│  Notify.send_   │─────►│ sre24.com   │
│  异常发生    │      │  wechat_push()  │      │ (微信推送)   │
└─────────────┘      └─────────────────┘      └─────────────┘
                              │
                              ├── 检查 disable_push
                              ├── 检查 minimum_interval
                              └── 根据 verbosity 过滤
```

### 8.2 消息类型

```python
WECHAT_MSG = {
    0: "出现未知异常，程序中止",
    1: "选课成功，课程为：",
    2: "有名额，验证码识别失败，正在重试",
    3: "出现重复选课，请调整config文件",
    "s": "刷课开始",
    4: "时间冲突，课程为",
    5: "考试时间冲突，课程为"
}

WECHAT_PREFIX = {
    0: "[异常]",
    1: "[成功]",
    2: "[失败]",
    3: "[特殊]"
}
```

### 8.3 多客户端池管理

```python
# 客户端池配置
elective_client_pool_size = 2    # 同时维护2个会话
elective_client_max_life = 600   # 每个会话最长600秒

# 工作流程
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Client #1   │     │ Client #2   │     │  relogin    │
│ (active)    │     │ (active)    │     │    Pool     │
│ expires: T+600    │ expires: T+580    │             │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┴───────────────────┘
                           │
                    轮流使用，过期自动重登
```

---

## 附录：关键数据流图

### 完整的选课请求流程

```
┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
│获取课程页│ → │检查名额 │ → │获取验证码│ → │识别验证码│ → │验证验证码│
└────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘
     │             │             │             │             │
     │ GET Supply  │ parse HTML  │ GET Draw    │ TTShitu API │ POST validate
     │ Cancel.do   │             │ Servlet     │             │
     │             │             │             │             │
     └─────────────┴─────────────┴─────────────┴─────────────┘
                                                         │
                              ┌──────────────────────────┘
                              │ (验证通过)
                              ▼
                    ┌─────────────────┐
                    │  POST elect     │
                    │  Supplement.do  │
                    └────────┬────────┘
                             │
           ┌─────────────────┼─────────────────┐
           │                 │                 │
           ▼                 ▼                 ▼
    ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
    │ElectionSuccess│  │各种错误异常  │   │需要重新登录  │
    │ (选课成功)   │   │(忽略/重试)   │   │(放回登录队列) │
    └─────────────┘   └─────────────┘   └─────────────┘
```

---

## 总结

PKU Auto-Elective 是一个设计精良的自动化选课系统，其核心优势在于：

1. **双线程架构**：登录与会话维护分离，确保高可用性
2. **多客户端池**：支持多会话轮换，降低单点故障风险
3. **智能验证码**：多策略并行识别+加权投票，提高通过率
4. **完善的规则引擎**：支持优先级、互斥、延迟等复杂选课策略
5. **健壮的异常处理**：细粒度的异常分类和自动恢复机制
6. **反检测机制**：随机User-Agent、随机刷新间隔、Cookie持久化等

该系统通过模拟正常用户的行为模式，在遵守学校选课规则的前提下，最大化选课成功率。
