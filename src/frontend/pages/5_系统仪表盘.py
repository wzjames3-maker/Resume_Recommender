"""
智能招聘 RAG 推荐系统 - 系统仪表盘 v2.0

数据统计、健康状态监控、多维度分析图表
"""

import streamlit as st
import os
import pandas as pd
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from src.frontend.api_client import health_check

st.set_page_config(page_title="系统仪表盘", page_icon="📊", layout="wide")

MONGO_URI = os.getenv("MONGODB_URL", "mongodb://admin:password@mongodb:27017/resume_rag?authSource=admin")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "password")
MILVUS_HOST = os.getenv("MILVUS_HOST", "milvus-standalone")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))


@st.cache_resource
def get_mongo():
    return MongoClient(MONGO_URI)


def check_redis() -> bool:
    """Check Redis connectivity"""
    try:
        import redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, socket_timeout=3)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


def check_milvus() -> tuple[bool, int]:
    """Check Milvus connectivity, returns (ok, num_entities)"""
    try:
        from pymilvus import connections, Collection
        connections.connect(host=MILVUS_HOST, port=MILVUS_PORT, timeout=5)
        col = Collection("resume_chunks")
        col.load()
        count = col.num_entities
        connections.disconnect("default")
        return True, count
    except Exception:
        return False, 0


def main():
    if not st.session_state.get("token"):
        st.warning("⚠️ 请先登录")
        st.stop()

    st.title("📊 系统仪表盘")
    st.caption("系统运行状态和数据统计概览")

    # ========== 系统健康 ==========
    st.markdown("## 🏥 系统健康状态")
    health = health_check()

    # Check each service independently
    redis_ok = check_redis()
    mongo_ok = False
    try:
        get_mongo().admin.command("ping")
        mongo_ok = True
    except Exception:
        pass
    milvus_ok, milvus_count = check_milvus()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if health:
            st.success("✅ API 服务正常")
            st.caption(f"版本: {health.get('version', '-')}")
        else:
            st.error("❌ API 服务异常")
    with col2:
        if mongo_ok:
            st.success("✅ MongoDB 正常")
        else:
            st.error("❌ MongoDB 异常")
    with col3:
        if milvus_ok:
            st.success(f"✅ Milvus 正常")
            st.caption(f"{milvus_count} chunks")
        else:
            st.error("❌ Milvus 异常")
    with col4:
        if redis_ok:
            st.success("✅ Redis 正常")
        else:
            st.warning("⚠️ Redis 不可用")

    st.markdown("---")

    # ========== 数据总览 ==========
    st.markdown("## 📈 数据总览")

    try:
        client = get_mongo()
        db = client["resume_rag"]

        resume_count = db.resumes.count_documents({"status": {"$ne": "deleted"}})
        session_count = db.sessions.count_documents({}) if "sessions" in db.list_collection_names() else 0

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📄 简历总数", resume_count)
        with col2:
            st.metric("💬 对话会话", session_count)
        with col3:
            if milvus_ok:
                st.metric("🧮 向量 Chunks", milvus_count)
            else:
                st.metric("🧮 向量 Chunks", "N/A")
        with col4:
            pipeline = [
                {"$match": {"status": {"$ne": "deleted"}}},
                {"$unwind": "$skill_list"},
                {"$group": {"_id": "$skill_list"}},
                {"$count": "total"},
            ]
            skill_result = list(db.resumes.aggregate(pipeline))
            skill_count = skill_result[0]["total"] if skill_result else 0
            st.metric("🏷️ 技能种类", skill_count)

        st.markdown("---")

        # ===== Row 1: 技能 Top 20 + 学历分布 =====
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 🏷️ 热门技能 Top 20")
            pipeline = [
                {"$match": {"status": {"$ne": "deleted"}}},
                {"$unwind": "$skill_list"},
                {"$group": {"_id": "$skill_list", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 20},
            ]
            top_skills = list(db.resumes.aggregate(pipeline))
            if top_skills:
                df = pd.DataFrame(top_skills)
                df.columns = ["技能", "出现次数"]
                st.bar_chart(df.set_index("技能"))

        with col2:
            st.markdown("### 🎓 学历分布")
            pipeline = [
                {"$match": {"status": {"$ne": "deleted"}, "personal_info.years_of_experience": {"$exists": True, "$ne": None}}},
                {"$group": {"_id": "$personal_info.years_of_experience", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ]
            edu_dist = list(db.resumes.aggregate(pipeline))
            if edu_dist:
                df = pd.DataFrame(edu_dist)
                df.columns = ["学历", "人数"]
                st.bar_chart(df.set_index("学历"))

        st.markdown("---")

        # ===== Row 2: 城市分布 Top 20 =====
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 🌍 城市分布 Top 20")
            pipeline = [
                {"$match": {"status": {"$ne": "deleted"}, "personal_info.city": {"$exists": True, "$ne": None, "$ne": ""}}},
                {"$group": {"_id": "$personal_info.city", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 20},
            ]
            city_data = list(db.resumes.aggregate(pipeline))
            if city_data:
                df = pd.DataFrame(city_data)
                df.columns = ["城市", "人数"]
                st.bar_chart(df.set_index("城市"))

        with col2:
            st.markdown("### 🎓 学历-经验交叉分析")
            pipeline = [
                {"$match": {"status": {"$ne": "deleted"}, "personal_info.years_of_experience": {"$exists": True, "$ne": None}}},
                {"$group": {
                    "_id": "$personal_info.years_of_experience",
                    "count": {"$sum": 1},
                    "avg_exp": {"$avg": {"$convert": {"input": "$personal_info.years_of_experience", "to": "double", "onError": 0, "onNull": 0}}}
                }},
                {"$sort": {"count": -1}},
            ]
            cross_data = list(db.resumes.aggregate(pipeline))
            if cross_data:
                df = pd.DataFrame(cross_data)
                df.columns = ["学历", "人数", "平均经验"]
                for _, row in df.iterrows():
                    edu = row["学历"]
                    count = int(row["人数"])
                    avg = round(row["平均经验"], 1) if row["平均经验"] else 0
                    st.metric(f"{edu}", f"{count} 人", f"平均 {avg} 年")

        st.markdown("---")

        # ===== Row 3: 公司 Top 20 =====
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 🏢 热门公司 Top 20")
            pipeline = [
                {"$match": {"status": {"$ne": "deleted"}}},
                {"$unwind": "$experience_list"},
                {"$group": {"_id": "$experience_list.company", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 20},
            ]
            company_data = list(db.resumes.aggregate(pipeline))
            if company_data:
                df = pd.DataFrame(company_data)
                df.columns = ["公司", "人数"]
                st.bar_chart(df.set_index("公司"), horizontal=True)

        with col2:
            st.markdown("### 📅 简历入库趋势（近30天）")
            try:
                pipeline = [
                    {"$match": {
                        "status": {"$ne": "deleted"},
                        "created_at": {"$exists": True},
                    }},
                    {"$group": {
                        "_id": {"$substr": ["$created_at", 0, 10]},
                        "count": {"$sum": 1},
                    }},
                    {"$sort": {"_id": 1}},
                ]
                trend_data = list(db.resumes.aggregate(pipeline))
                if trend_data:
                    df = pd.DataFrame(trend_data)
                    df.columns = ["日期", "数量"]
                    df = df.tail(30)
                    st.line_chart(df.set_index("日期"))
                else:
                    st.info("暂无时间序列数据")
            except Exception:
                st.info("暂无时间序列数据")

    except Exception as e:
        st.error(f"获取数据统计失败: {e}")

    # ========== API 文档 ==========
    st.markdown("---")
    st.markdown("## 📚 API 文档")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("- [Swagger UI](http://localhost:8000/docs)")
    with col2:
        st.markdown("- [ReDoc](http://localhost:8000/redoc)")
    with col3:
        st.markdown("- [OpenAPI JSON](http://localhost:8000/openapi.json)")


if __name__ == "__main__":
    main()
