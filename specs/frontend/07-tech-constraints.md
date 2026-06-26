<!-- Module: frontend -->
<!-- Spec Layer: 07 - Tech Constraints -->
<!-- Date: 2026-06-25 -->

# 07-tech-constraints: Frontend 技术约束

## 7.1 框架约束

| 类别 | 选择 | 版本 | 理由 |
|------|------|------|------|
| 框架 | Streamlit | >=1.40 | 纯 Python、原生聊天组件 |
| HTTP | requests | >=2.31 | 同步、稳定 |
| Excel | openpyxl | >=3.1 | .xlsx 格式支持 |
| MongoDB | pymongo | >=4.0 | 与后端一致 |

## 7.2 禁用项

- JavaScript / React / Vue
- CSS 框架（Bootstrap / Tailwind）
- 前端构建工具（Webpack / Vite）
- 服务端渲染框架（Next.js / Nuxt）

## 7.3 性能约束

| 约束 | 值 | 说明 |
|------|-----|------|
| 单次 API 超时 | 60s | send_chat_message |
| 单次上传超时 | 120s | upload_resume |
| MongoDB 查询超时 | 10s | 直连查询 |
| 导出最大行数 | 1000 | 单次上限 |
| 对比最大人数 | 5 | compare_candidates |

## 7.4 部署约束

| 约束 | 值 |
|------|-----|
| 启动命令 | streamlit run src/frontend/app.py --server.port 8501 --server.address 0.0.0.0 |
| 容器内路径 | /app/src/frontend/ |
