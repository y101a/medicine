# 病理诊断科普助手前端

Vue 3、TypeScript、Vite、Pinia、Vue Router、Element Plus 和 Axios。
开发环境已经关闭模拟认证，请求通过 Vite 代理访问本机 FastAPI。

## 本地启动

先确认 Docker Desktop 已启动，然后在 VS Code 打开项目，建立三个 PowerShell 终端。

终端一：

```powershell
cd "D:\medicine and mannagement system\merchant_sales_cos-main\backend"
docker compose up -d
```

终端二：

```powershell
cd "D:\medicine and mannagement system\merchant_sales_cos-main\backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

终端三：

```powershell
cd "D:\medicine and mannagement system\merchant_sales_cos-main\frontend"
npm run dev
```

浏览器打开 <http://127.0.0.1:5173/login>。

请统一使用 `127.0.0.1`，不要一会儿使用 `localhost`、一会儿使用
`127.0.0.1`，否则 Cookie 会被浏览器视为不同站点。

## 检查

```powershell
npm run test
npm run build
```

真实接口开关位于 `.env.development`，当前为
`VITE_USE_MOCK_API=false`。Vite 会将 `/api` 请求转发到
`http://127.0.0.1:8000`。

