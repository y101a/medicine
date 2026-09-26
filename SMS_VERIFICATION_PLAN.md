# 模拟短信、手机号验证与密码找回实施方案

> 状态：接口契约已冻结，代码尚未实施
> 日期：2026-09-26
> 分工：Codex 负责 backend/；DSH（DeepSeek）负责 frontend/
> 目标：前后端可依据本文件并行开发，第一阶段不调用真实短信、不产生短信费用

## 1. 背景与现状

- 注册表单已经强制填写中国大陆手机号，但当前只校验格式和唯一性，没有验证手机号归属。
- 登录页“忘记密码？”目前只显示“忘记密码功能暂未开放”。
- 后端只有注册、登录、刷新令牌和退出接口，没有短信挑战、手机号验证或密码重置接口。
- 用户手机号已经加密保存，并使用不可逆指纹建立唯一约束；不得新增明文手机号列。
- 当前访问令牌是 15 分钟有效的无状态 JWT；只删除刷新会话不能立刻让已经签发的访问令牌失效，
  因此本方案同时引入认证版本号。

## 2. 已确认的产品决策

1. 新用户注册必须完成手机号验证码验证，才能创建账户。
2. 忘记密码使用“已验证手机号 + 短信验证码”找回。
3. 已有用户保持可登录，但迁移后默认视为“手机号尚未验证”；登录后在设置页完成一次验证。
4. 已有用户在完成手机号验证前，不能使用短信找回密码。开发库测试账号可登录后补验证。
5. 第一阶段使用模拟短信提供商，不调用阿里云、不发送真实短信、不收费。
6. 模拟短信的交互、接口、限流、有效期和真实服务一致，后续只替换后端 provider。
7. 正式接入时使用阿里云“号码认证服务（PNVS）的短信认证”，不是需要企业资质的普通短信服务。
8. 本期只支持中国大陆手机号，不做国际号码。

## 3. 模拟短信的可见效果

用户操作与真实短信一致：

1. 输入手机号并点击“获取验证码”。
2. 页面提示“验证码已发送”，按钮进入 60 秒倒计时。
3. 后端生成随机 6 位验证码，有效期 5 分钟。
4. 开发环境启动终端显示一次：

   ~~~text
   [DEV SMS] 138****8000 验证码 482731，5 分钟内有效
   ~~~

5. 用户在页面输入验证码，验证成功后继续注册、绑定或重置密码。

模拟验证码只输出到当前开发终端，不写数据库明文、不写文件、不进入持久化日志或审计表。
HTTP 响应绝不返回验证码。自动化测试可注入固定验证码；人工开发环境仍使用随机验证码。

## 4. 安全硬约束

- SMS_PROVIDER=fake 只允许 APP_ENVIRONMENT=development 或 test。
- 生产环境检测到 fake provider 必须拒绝启动，不能静默回落。
- 验证码使用 secrets 生成；数据库只保存专用密钥 HMAC-SHA256 摘要。
- 不使用普通 SHA-256，也不使用可被离线穷举的无密钥摘要。
- 验证码 5 分钟过期、最多验证 5 次、只能成功使用一次。
- 验证成功得到的 verificationToken 10 分钟过期，只能用于对应手机号和对应用途。
- 手机号改变后，前端必须清除旧 challenge/token；后端也必须核对手机号指纹。
- 密码找回的“手机号存在/不存在、已验证/未验证”对外返回相同响应和近似执行路径，
  不得形成账户枚举接口。
- 验证码、完整手机号、新密码、AccessKey、原始 IP 不得进入应用日志和审计表。
- 限流在 PostgreSQL 中实现或以数据库记录计算，不能复用只能约束单进程的内存限流。
- 重置密码后必须撤销全部刷新会话、提升认证版本号，使全部旧访问令牌立即失效。
- 新密码继续使用现有 Argon2id 哈希；不得保存明文或可逆密码。

## 5. 冻结 API 契约

所有字段使用现有前端约定的 camelCase；错误仍使用项目统一错误结构。

### 5.1 发送注册或找回密码验证码

~~~http
POST /api/v1/auth/phone-verifications/code
Content-Type: application/json
~~~

请求：

~~~json
{
  "phone": "13800138000",
  "purpose": "registration"
}
~~~

purpose 只允许 registration 或 password_reset。

响应：202 Accepted

~~~json
{
  "challengeId": "uuid",
  "expiresInSeconds": 300,
  "resendAfterSeconds": 60
}
~~~

对于密码找回，即使手机号不存在或尚未验证，也返回同形状响应；此时不调用短信 provider，
而是在数据库创建不可验证的诱饵 challenge，避免账户枚举和无效短信费用。

### 5.2 校验注册或找回密码验证码

~~~http
POST /api/v1/auth/phone-verifications/verify
Content-Type: application/json
~~~

请求：

~~~json
{
  "challengeId": "uuid",
  "code": "482731"
}
~~~

响应：200 OK

~~~json
{
  "verificationToken": "一次性不透明令牌",
  "expiresInSeconds": 600
}
~~~

令牌只绑定 challenge、手机号指纹和 purpose，不代表用户已登录。

### 5.3 注册接口变更

POST /api/v1/auth/register 在现有请求上增加：

~~~json
{
  "phoneVerificationToken": "一次性不透明令牌"
}
~~~

后端必须确认令牌：

- purpose 为 registration
- 绑定手机号与请求 phone 一致
- 未过期、未消费

注册和消费令牌必须在同一数据库事务完成。成功后写入 users.phone_verified_at。

### 5.4 重置密码

~~~http
POST /api/v1/auth/password-reset
Content-Type: application/json
~~~

请求：

~~~json
{
  "phone": "13800138000",
  "verificationToken": "一次性不透明令牌",
  "newPassword": "new-password"
}
~~~

成功：204 No Content。

同一事务内必须：

1. 校验并消费 password_reset 令牌。
2. 更新 Argon2id 密码哈希与 password_changed_at。
3. 清零登录失败计数和锁定时间。
4. auth_version 加一。
5. 撤销该用户所有未撤销的 auth_sessions。
6. 写入不含手机号和验证码的审计事件。

### 5.5 已有用户验证当前手机号

发送：

~~~http
POST /api/v1/users/me/phone-verification/code
~~~

无请求体；手机号必须从当前用户的加密资料解密取得，不接受前端传入手机号。

响应与 5.1 相同。

确认：

~~~http
POST /api/v1/users/me/phone-verification/confirm
Content-Type: application/json
~~~

~~~json
{
  "challengeId": "uuid",
  "code": "482731"
}
~~~

成功：204 No Content，写入 users.phone_verified_at。

### 5.6 当前用户响应变更

AuthUser 增加：

~~~json
{
  "phoneVerified": true
}
~~~

注册完成的新用户为 true；迁移前已有用户在补验证前为 false。

## 6. 错误码与中文文案

| HTTP | code | 用途 |
| --- | --- | --- |
| 422 | SMS_PHONE_INVALID | 手机号格式不合法 |
| 429 | SMS_RATE_LIMITED | 发送过于频繁；details 提供 retryAfterSeconds |
| 422 | SMS_CHALLENGE_INVALID | challenge 不存在、用途不符或已消费，使用统一文案 |
| 422 | SMS_CODE_INVALID | 验证码错误，不说明剩余次数 |
| 422 | SMS_CODE_EXPIRED | 验证码已过期 |
| 429 | SMS_ATTEMPTS_EXCEEDED | 错误次数过多，challenge 作废 |
| 422 | PHONE_VERIFICATION_REQUIRED | 注册缺少有效手机号验证 |
| 422 | PHONE_VERIFICATION_TOKEN_INVALID | 一次性令牌无效、过期或手机号不匹配 |
| 503 | SMS_PROVIDER_NOT_CONFIGURED | 非开发环境未配置真实 provider |
| 502 | SMS_PROVIDER_FAILED | 真实 provider 调用失败（预留） |
| 504 | SMS_PROVIDER_TIMEOUT | 真实 provider 超时（预留） |

密码找回发送阶段统一显示：

> 如果该手机号已绑定并完成验证，验证码将发送到该手机。

不得显示“手机号未注册”或“手机号尚未验证”。

## 7. 数据库设计与迁移

下一迁移固定为：

~~~text
20260926_0023_phone_verification
down_revision = 20260924_0022
~~~

### 7.1 users 增加

~~~text
phone_verified_at timestamptz NULL
~~~

迁移时已有用户保持 NULL，不得因为数据库里已有手机号就自动标记为已验证。

### 7.2 user_credentials 增加

~~~text
auth_version integer NOT NULL DEFAULT 1 CHECK (auth_version >= 1)
~~~

访问令牌新增 ver claim。认证依赖读取用户凭据并比对版本；密码重置后旧 token 立即失效。
部署升级后不含 ver 的旧访问令牌按会话失效处理，用户重新登录即可。

### 7.3 新表 phone_verification_challenges

建议字段：

~~~text
id uuid primary key
user_id uuid NULL references users(id) on delete cascade
phone_fingerprint varchar(64) not null
purpose varchar(32) not null
provider varchar(32) not null
code_digest varchar(64) not null
provider_reference varchar(128) null
request_ip_fingerprint varchar(64) not null
is_decoy boolean not null default false
attempt_count integer not null default 0
max_attempts integer not null default 5
created_at timestamptz not null
expires_at timestamptz not null
resend_available_at timestamptz not null
verified_at timestamptz null
verification_token_hash varchar(64) null
verification_token_expires_at timestamptz null
consumed_at timestamptz null
~~~

约束与索引：

- purpose 只允许 registration、password_reset、phone_binding。
- attempt_count 大于等于 0；max_attempts 大于 0；时间顺序合理。
- 对 phone_fingerprint + purpose + created_at 建索引。
- 对 request_ip_fingerprint + created_at 建索引。
- 账号删除级联删除其关联 challenge；未关联注册 challenge 按过期惰性清理。

## 8. 限流默认值

- 同手机号 60 秒只能发送 1 次。
- 同手机号每小时最多 5 次、每天最多 10 次。
- 同 IP 指纹每 10 分钟最多 10 次、每天最多 30 次。
- 同 challenge 最多校验 5 次。
- 重发新 challenge 后，旧 challenge 立即失效。

限流命中返回 429 SMS_RATE_LIMITED 和 retryAfterSeconds。前端倒计时只是体验层，
后端必须独立执行全部限流。

## 9. Provider 抽象与环境变量

后端定义统一 provider 接口，第一阶段实现 FakeSmsVerificationProvider；
未来实现 AliyunPnvsSmsVerificationProvider。业务服务不得散落 fake/aliyun 条件分支。

新增 .env.example 变量：

~~~env
SMS_PROVIDER=fake
SMS_CODE_SECRET=replace_with_at_least_32_random_bytes
SMS_CODE_EXPIRE_SECONDS=300
SMS_TOKEN_EXPIRE_SECONDS=600
SMS_RESEND_SECONDS=60
SMS_MAX_ATTEMPTS=5
SMS_LIMIT_PHONE_HOURLY=5
SMS_LIMIT_PHONE_DAILY=10
SMS_LIMIT_IP_10M=10
SMS_LIMIT_IP_DAILY=30

# 第二阶段真实短信认证使用；第一阶段保持为空。
ALIYUN_PNVS_ACCESS_KEY_ID=
ALIYUN_PNVS_ACCESS_KEY_SECRET=
ALIYUN_PNVS_ENDPOINT=dypnsapi.aliyuncs.com
ALIYUN_PNVS_SIGN_NAME=
ALIYUN_PNVS_TEMPLATE_CODE=
~~~

RAM AccessKey 与百炼 QWEN_API_KEY 不是同一种密钥，不得复用或混淆。

## 10. 后端任务（Codex）

建议新增：

- backend/app/models/phone_verification.py
- backend/app/schemas/phone_verification.py
- backend/app/services/sms_providers/base.py
- backend/app/services/sms_providers/fake.py
- backend/app/services/phone_verification.py
- backend/migrations/versions/20260926_0023_phone_verification.py
- backend/tests/test_phone_verification.py

建议修改：

- backend/app/models/user.py
- backend/app/models/__init__.py
- backend/app/core/config.py
- backend/app/core/security.py
- backend/app/api/dependencies.py
- backend/app/api/routes/auth.py
- backend/app/api/routes/users.py
- backend/app/schemas/auth.py
- backend/app/services/auth.py
- backend/.env.example
- backend/docs/API.md
- backend/docs/DATA_MODEL.md

实现要点：

- 注册、重置密码和 challenge 消费使用数据库事务与行锁，防止并发重复消费。
- 对验证码与一次性 token 使用常量时间比较。
- 过期 challenge 在请求时惰性清理；不在用户机器创建计划任务或后台自启动。
- 审计复用现有 audit_logs，建议 action 为 sms_code_requested、sms_code_verified、
  phone_verified、password_reset。
- 审计只记录结果与受控 reason code，不记录手机号、验证码、token 或 IP。

## 11. 前端任务（DSH / DeepSeek）

新增：

- frontend/src/views/ForgotPasswordView.vue
- 对应单元测试和 Playwright 场景

修改：

- frontend/src/types/auth.ts
- frontend/src/api/auth.ts
- frontend/src/api/mockAuth.ts
- frontend/src/stores/auth.ts
- frontend/src/views/RegisterView.vue
- frontend/src/views/LoginView.vue
- frontend/src/views/SettingsView.vue
- frontend/src/router/index.ts
- frontend/src/views/auth-views.test.ts
- frontend/BROWSER_ACCEPTANCE.md

交互要求：

- 注册页手机号右侧提供“获取验证码”；手机号格式正确才可点击。
- 输入验证码并通过验证后，再允许提交注册。
- 用户修改手机号时立即清除验证成功状态。
- 登录页“忘记密码？”改为跳转 /forgot-password，不再显示占位提示。
- 找回页按“手机号 → 验证码 → 新密码”展示，可做单页分步，不增加侧边栏入口。
- 获取找回验证码后始终显示统一文案，不能根据接口时长或错误提示推断账户是否存在。
- 设置页在 phoneVerified=false 时显示“验证当前手机号”；不展示完整手机号。
- 重置成功后跳转登录页并提示“密码已重置，请使用新密码登录”。
- 不在 localStorage/sessionStorage 保存验证码、verificationToken、新密码或完整手机号。
- 倒计时以服务端 resendAfterSeconds 为准，刷新页面不必恢复未完成验证码流程。

## 12. 前后端并行顺序

1. 本文件即冻结契约；若字段或路径需要变化，先在 COORDINATION.md 第 6 节记录，不能静默改。
2. Codex：迁移、模型、provider、服务和接口；只占用 backend/ 与迁移数据库。
3. DSH：按第 5 节契约用 page.route/mock API 实现页面、状态与测试；不等待数据库。
4. Codex 后端专项测试和完整基线通过后，在 7.2 报告最终契约是否有偏差。
5. DSH 切换到真实本地后端联调；联调前不得宣称真实短信链路通过。
6. 双方各自显式暂存自己的文件，禁止 git add .。

高冲突点：

- frontend/src/types/auth.ts 与 backend/app/schemas/auth.py 必须严格保持字段一致。
- AuthUser.phoneVerified 必须同时更新 mock、Pinia、注册结果与 /users/me。
- 后端迁移和数据库测试只由 Codex 串行执行；前端接口桩测试不占数据库。

## 13. 验收清单

### 13.1 后端自动化

- fake provider 只在 development/test 可用，production 启动拒绝。
- 验证码随机、仅保存 HMAC 摘要、HTTP 响应不含验证码。
- 注册无 token、错 purpose、手机号不匹配、过期或已消费 token 均拒绝。
- 同 token 并发注册只有一个成功。
- 不存在/未验证手机号的找回请求与正常请求返回同形状。
- 验证码错误、过期、超过次数、重复使用均有受控错误。
- 手机号/IP/时间窗口限流跨 worker 共享。
- 密码重置后旧密码失败、新密码成功。
- 全部刷新会话撤销，旧访问令牌因 auth_version 失效。
- 账号删除级联 challenge；审计不含敏感值。
- Alembic 0022 → 0023 → 0022 → 0023 往返通过。

### 13.2 前端自动化

- 注册必须先验证手机号，修改手机号会清除验证。
- 获取按钮倒计时、重复点击、错误码中文展示。
- 忘记密码入口正确跳转，成功后回登录页。
- 找回流程不显示“手机号不存在/未验证”。
- phoneVerified=false 时设置页显示补验证入口，true 时隐藏。
- 验证码和 token 不写浏览器存储。
- Playwright 覆盖成功、错误验证码、过期、限流、取消和窄屏可用性。

### 13.3 人工开发验收

1. 设置 APP_ENVIRONMENT=development、SMS_PROVIDER=fake。
2. 注册新手机号，终端看到随机验证码并成功注册。
3. 登录后确认 phoneVerified=true。
4. 使用忘记密码重置，旧密码不能登录，新密码可以登录。
5. 重置前已登录的其他浏览器会话再次请求时返回会话失效。
6. 用不存在手机号找回，页面只显示统一文案，终端不输出验证码。
7. 把环境改成 production 且仍为 fake，应用应拒绝启动。

## 14. 本期不做

- 真实阿里云短信调用和真实费用验收。
- 短信验证码直接登录。
- 短信作为第二因素登录（MFA）。
- 修改/换绑手机号。
- 图形验证码、设备指纹或第三方风控；达到真实公网规模前再补。
- 人工申诉找回。
- 国际手机号。

## 15. 第二阶段切换真实短信

第一阶段验收后，新增阿里云 PNVS provider，并保持第 5 节接口完全不变。上线前必须完成：

- 开通阿里云号码认证服务中的短信认证。
- 创建专用 RAM 用户和最小权限 AccessKey。
- 配置平台签名/模板参数、余额或套餐。
- 隐私政策说明手机号会交由阿里云短信认证处理。
- 设置费用预警、防盗刷和发送频率预警。
- 只用无真实病历数据的测试账户做少量付费端到端验收。
