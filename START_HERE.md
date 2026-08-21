# 从这里开始

`.env.example` 是模板；`.env` 是实际运行时读取的配置文件。

```powershell
Copy-Item .env.example .env
notepad .env
python server.py --check
./start.ps1
```

打开 http://localhost:8000 后，先点击左侧“测试 AI 连接”。若连接成功，状态会显示“OpenRouter 已连接”；若失败，页面会明确显示 HTTP、网络或配置错误，不会悄悄降级。
