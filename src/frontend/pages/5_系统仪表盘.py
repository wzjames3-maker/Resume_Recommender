"""
智能招聘 RAG 推荐系统 - 系统仪表盘 v2.1

数据统计、健康状态监控、多维度分析图表
通过 API 客户端访问后端，不直连数据库
"""

import streamlit as st
import pandas as pd
from src.frontend.api_client import health_check, get_resume_stats, list_conversations

st.set_page_config(page_title="系统仪表盘", page_icon="📊", layout="wide")


def main():
    if not st.session_state.get("token"):
        st.warning("⚠️ 请先登录")
        st.stop()

    st.title("📊 系统仪表盘")
    st.caption("系统运行状态和数据统计概览")

    # ========== 系统健康 ==========
    st.markdown("## 🏥 系统健康状态")
    health = health_check()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if health:
            st.success("✅ API 服务正常")
            st.caption(f"版本: {health.get('version', '-')}")
        else:
            st.error("❌ API 服务异常")
    with col2:
        if health and health.get("mongodb") == "ok":
            st.success("✅ MongoDB 正常")
        else:
            st.error("❌ MongoDB 异常")
    with col3:
        if health and health.get("milvus") == "ok":
            st.success("✅ Milvus 正常")
        else:
            st.error("❌ Milvus 异常")
    with col4:
        if health and health.get("redis") == "ok":
            st.success("✅ Redis 正常")
        else:
            st.warning("⚠️ Redis 不可用")

    st.markdown("---")

    # ========== 数据总览 ==========
    st.markdown("## 📈 数据总览")

    stats = get_resume_stats()
    if stats is None:
        st.error("❌ 获取统计数据失败，请检查 API 连接")
        return

    resume_count = stats.get("total_resumes", 0)

    conversations = list_conversations(page=1, size=1)
    session_count = conversations.get("total", 0) if conversations else 0

    skills = stats.get("skills", [])
    cities = stats.get("cities", [])
    companies = stats.get("companies", [])
    educations = stats.get("educations", [])

    skill_count = len(skills)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📄 简历总数", resume_count)
    with col2:
        st.metric("💬 对话会话", session_count)
    with col3:
        if health and health.get("milvus") == "ok":
            st.metric("🧮 向量索引", "就绪")
        else:
            st.metric("🧮 向量索引", "N/A")
    with col4:
        st.metric("🏷️ 技能种类", skill_count)

    st.markdown("---")

    # ===== Row 1: 技能 Top 20 + 学历分布 =====
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🏷️ 热门技能 Top 20")
        if skills:
            df = pd.DataFrame(skills)
            df.columns = ["技能", "出现次数"]
            st.bar_chart(df.set_index("技能"))
        else:
            st.info("暂无技能数据")

    with col2:
        st.markdown("### 🎓 学历分布")
        if educations:
            df = pd.DataFrame(educations)
            df.columns = ["学历", "人数"]
            st.bar_chart(df.set_index("学历"))
        else:
            st.info("暂无学历数据")

    st.markdown("---")

    # ===== Row 2: 城市分布 Top 20 + 公司分布 =====
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🌍 城市分布 Top 20")
        if cities:
            df = pd.DataFrame(cities)
            df.columns = ["城市", "人数"]
            st.bar_chart(df.set_index("城市"))
        else:
            st.info("暂无城市数据")

    with col2:
        st.markdown("### 🏢 热门公司 Top 20")
        if companies:
            df = pd.DataFrame(companies)
            df.columns = ["公司", "人数"]
            st.bar_chart(df.set_index("公司"), horizontal=True)
        else:
            st.info("暂无公司数据")

    # ========== API 文档 ==========
    st.markdown("---")
    st.markdown("## 📚 API 文档")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("- [Swagger UI](/docs)")
    with col2:
        st.markdown("- [ReDoc](/redoc)")
    with col3:
        st.markdown("- [OpenAPI JSON](/openapi.json)")


if __name__ == "__main__":
    main()
