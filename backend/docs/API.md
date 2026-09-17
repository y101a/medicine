# 认证接口契约

统一前缀：`/api/v1`。请求与响应使用 JSON；登录状态由 HttpOnly Cookie 管理。

## 注册

`POST /auth/register`

请求字段：`username`、`realName`、`phone`、`idCard`、`gender`、`password`。
成功返回 201 和 `{ "user": AuthUser }`，但不会自动登录。

## 登录

`POST /auth/login`

请求字段：`username`、`password`。用户名匹配不区分大小写。成功后设置访问
Cookie 和刷新 Cookie，并返回 `{ "user": AuthUser }`。

连续 5 次密码错误会锁定 15 分钟。不存在的用户名与错误密码使用相同错误提示，
避免泄露账户是否存在。

## 刷新与退出

- `POST /auth/refresh`：轮换刷新令牌并续期登录状态。
- `POST /auth/logout`：撤销当前刷新会话并删除 Cookie。

## 当前用户

`GET /users/me`

要求有效访问 Cookie。手机号与身份证只返回脱敏值，不返回原文。

## 修改当前用户资料

`PATCH /users/me`，需要登录 Cookie。成功返回 200 和更新后的 AuthUser
（与 GET /users/me 一致，没有外层 user 包装）。

请求示例：`{"realName": "李明", "gender": "male"}`。
可只提交其中一个字段，未提交的字段保持原值。
姓名去除首尾空格后限制 2–20 个字符，仅允许中文、英文字母和 ·，加密保存。
性别允许 male、female、private。手机号和身份证仍仅返回脱敏值。

空对象、显式 null、非法姓名/性别或任何其他字段均返回 422，整次修改不生效。
用户名、手机号、身份证、密码、角色、状态、注册时间和用户 ID 不可通过此接口修改。
目标用户始终从登录 Cookie 确定，未登录返回 401，停用账户返回 403。

## 用户头像

- `PUT /users/me/avatar`：使用 `multipart/form-data` 上传字段 `avatar`。
- `GET /users/me/avatar`：读取当前登录用户头像。

仅支持 JPG、PNG、WebP，文件最大 3 MB。后端校验真实图片内容、移除元数据并统一
居中裁切为 512×512 WebP。头像文件使用用户 UUID 命名并保存在
`AVATAR_STORAGE_DIR`，用户只能上传和读取自己的头像。

## 错误响应

```json
{
  "code": "VALIDATION_ERROR",
  "message": "提交的信息校验未通过",
  "details": []
}
```

常用状态码：401 未登录或凭据错误、403 账户停用、409 唯一字段冲突、
422 参数校验失败、423 账户暂时锁定。

## 医学知识检索

`POST /knowledge/search`，要求有效登录 Cookie。

请求示例：

~~~json
{
  "query": "普通感冒是否应该自行服用抗生素",
  "topK": 5
}
~~~

后端在发送阿里云向量服务前会移除手机号、身份证、邮箱、显式姓名和详细地址，并把
查询截断到最多 500 个字符。原始查询和脱敏查询均不写入知识库或检索日志表。

生产环境仅召回来源为 `approved`、文档为 `approved` 且向量配置一致的文本块。开发
环境还允许明确标记为 `prototype` 的原型资料。返回项按余弦相似度排序，并包含
`trustLevel`（`approved` 或 `prototype`）、`organization`、`title`、
`canonicalUrl`、`versionLabel`、`publishedAt`、`sectionTitle` 和原始证据文本。
如果库中不存在符合这些条件的向量，接口直接返回空列表，不把查询发送给外部模型。

`queryRedacted` 表示本次查询在发送模型前是否移除了直接身份信息。该接口返回检索
证据，不给出诊断结论；调用方不得把相似度分数解释为患病概率。

## 咨询流式回答中的 RAG

`POST /consultations/{cid}/stream` 在调用聊天模型前进入 LangGraph 生成上下文图。正常
路线执行红旗复检、查询脱敏和最多 4 个证据块召回；证据作为不可信数据隔离后加入
系统提示词，要求模型使用 `[来源1]` 格式引用且不得编造来源。

流的 `start` 事件增加 `retrieval`：

~~~json
{
  "type": "start",
  "retrieval": {
    "status": "completed",
    "gateReason": "medical_content",
    "errorCode": null,
    "sources": [
      {
        "sourceKey": "developer_prototype_knowledge",
        "organization": "项目开发者",
        "title": "合理用药与抗菌药物原型资料",
        "canonicalUrl": "https://prototype.invalid/medical-knowledge/medicine-use",
        "sectionTitle": "普通感冒与抗菌药物",
        "similarity": 0.79,
        "trustLevel": "prototype"
      }
    ]
  }
}
~~~

status 可能为 completed、empty、failed 或 skipped。事件不会返回证据正文、原始用户
问题或数据库对象。

`retrieval.gateReason` 说明门控结果：`medical_content` 表示医学相关并执行检索，
`non_medical_content` 表示普通聊天并跳过检索，`emergency` 表示红旗路线已经终止。

产生实际科普正文时，去重后的来源快照会随助手消息保存在加密字段中，并通过
`MessageOut.citations` 返回；结构化追问卡不保存引用。前端仅在 citations 非空时显示
“参考资料 N 条”折叠区域。approved 来源可以打开原文，prototype 只显示开发测试警示，
不会提供 `prototype.invalid` 无效链接。相似度仅用于内部排序，不在界面解释为患病概率。

## 健康记录

前缀 `/health-records`，全部需要登录，且只能访问当前用户自己的记录。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /health-records/settings` | 读取采集开关与首次通知状态 |
| `PATCH /health-records/settings` | 关闭或重新开启自动采集 |
| `POST /health-records/onboarding` | 提交首次采集的身体状况（也可跳过） |
| `POST /health-records/extract` | 按某条用户消息增量提取事实，前端在回答完成后调用 |
| `GET /health-records` | 列出当前用户的健康记录 |
| `POST /health-records` | 手动新增一条记录 |
| `PATCH /health-records/{record_id}` | 修改一条记录，来源改为用户自述 |
| `DELETE /health-records/{record_id}` | 删除一条记录 |

约定：

- 记录正文使用 Fernet 加密保存；去重依据是 NFKC + casefold 后的 SHA-256 指纹，不会
  改写用户原文标点。
- `source` 为 `onboarding`、`conversation` 或 `user`。对话提取的记录一定来自用户明确
  陈述，推断性表述与手机号、身份证、邮箱在写入前丢弃。
- 关闭采集后，既有记录不再进入回答上下文，但记录本身不会被删除。
- 跨用户访问一律返回 404，不区分“不存在”和“无权限”。
- 健康记录不参与红旗预检。`POST /consultations/{cid}/stream` 只把记录作为受限背景注入
  系统提示词，要求不得据记录推断病因，也不得因记录中存在某项情况而降低对红旗症状的警惕。
