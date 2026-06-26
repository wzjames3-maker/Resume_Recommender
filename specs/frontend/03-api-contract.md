<!-- Module: frontend -->
<!-- Spec Layer: 03 - API Contract -->
<!-- Date: 2026-06-25 -->

# 03-api-contract: Frontend 接口契约

## 3.1 已使用的 API 端点（不变）

| 方法 | 端点 | 用途 |
|------|------|------|
| POST | /api/v1/auth/login | 用户登录 |
| POST | /api/v1/chat | 聊天搜索（SSE streaming） |
| POST | /api/v1/resumes/upload | 简历上传 |
| GET | /api/v1/conversations | 对话列表 |
| GET | /api/v1/conversations/{id} | 对话详情 |
| DELETE | /api/v1/conversations/{id} | 删除对话 |
| GET | /health | 健康检查 |

## 3.2 MongoDB 直连接口

以下功能绕过 API，直接查询 MongoDB（使用 pymongo）：

```
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://admin:password@mongodb:27017/resume_rag?authSource=admin")
```

### 3.2.1 简历列表

```python
collection.find({
    'status': {'$ne': 'deleted'},
    # optional filters:
    'personal_info.city': {'$regex': city},
    'personal_info.years_of_experience': {'$gte': min_exp},
    'education_list.degree': {'$regex': degree},
    'skill_list': {'$in': skills},
    'education_list.is_985': True,
}).sort('created_at', -1).skip(skip).limit(size)
```

### 3.2.2 简历详情

```python
collection.find_one({'id': resume_id})
```

### 3.2.3 简历更新

```python
collection.update_one({'id': resume_id}, {'$set': update_data})
```

### 3.2.4 简历删除（软删除）

```python
collection.update_one({'id': resume_id}, {'$set': {'status': 'deleted'}})
```

### 3.2.5 统计聚合

```python
collection.aggregate([
    {'$match': {'status': {'$ne': 'deleted'}}},
    {'$unwind': '$skill_list'},
    {'$group': {'_id': '$skill_list', 'count': {'$sum': 1}}},
    {'$sort': {'count': -1}},
    {'$limit': 50},
])
```

## 3.3 api_client.py 新增方法

| 方法 | 返回类型 | 说明 |
|------|----------|------|
| get_resume(resume_id) | Optional[Dict] | 从 MongoDB 获取简历详情 |
| list_resumes_api(filters) | Optional[Dict] | 带筛选的简历列表 |
| update_resume(resume_id, data) | bool | 更新简历字段 |
| delete_resume_api(resume_id) | bool | 软删除简历 |
| get_resume_stats() | Optional[Dict] | 获取统计数据 |
| export_candidates_excel(candidates) | bytes | 导出 Excel 字节流 |

## 3.4 错误处理约定

| 场景 | 返回值 |
|------|--------|
| API 不可达 | None → st.error() |
| MongoDB 不可达 | 异常 → st.warning() |
| resume_id 不存在 | None → 显示提示 |
| 导出无数据 | 空 bytes → st.info() |
