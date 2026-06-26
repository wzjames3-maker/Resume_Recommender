"""
智能招聘 RAG 推荐系统 - 用户管理页面

管理员查看用户列表、角色权限、系统配置
"""

import streamlit as st
import os

st.set_page_config(page_title="用户管理", page_icon="👥", layout="wide")


def main():
    if not st.session_state.get("token"):
        st.warning("⚠️ 请先登录")
        st.stop()

    if st.session_state.get("role") != "admin":
        st.error("🚫 此页面仅限管理员访问")
        st.stop()

    st.title("👥 用户管理")
    st.caption("管理系统用户、角色权限和系统配置")

    # ===== 用户列表 =====
    st.markdown("## 📋 用户列表")
    st.markdown("### 内置用户账号")

    users = [
        {"用户名": "admin", "角色": "管理员", "权限": "全部权限（搜索/上传/管理/删除/系统配置）", "状态": "🟢 活跃"},
        {"用户名": "hr", "角色": "HR 用户", "权限": "搜索、上传、查看简历", "状态": "🟢 活跃"},
        {"用户名": "viewer", "角色": "只读用户", "权限": "仅查看推荐结果和仪表盘", "状态": "🟢 活跃"},
    ]

    import pandas as pd
    df = pd.DataFrame(users)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # ===== 角色权限矩阵 =====
    st.markdown("---")
    st.markdown("## 🔐 角色权限矩阵")

    permissions = {
        "功能": ["智能搜索", "简历上传", "简历详情查看", "简历管理", "简历编辑", "简历删除", "对话历史", "系统仪表盘", "用户管理"],
        "admin": ["✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅", "✅"],
        "hr": ["✅", "✅", "✅", "❌", "❌", "❌", "✅", "✅", "❌"],
        "viewer": ["✅", "❌", "❌", "❌", "❌", "❌", "❌", "✅", "❌"],
    }
    df_perm = pd.DataFrame(permissions)
    st.dataframe(df_perm, use_container_width=True, hide_index=True)

    # ===== 系统配置 =====
    st.markdown("---")
    st.markdown("## ⚙️ 系统配置")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🔗 API 端点")
        api_configs = {
            "LLM Provider": os.getenv("LLM_PROVIDER", "sensenova"),
            "LLM Model": os.getenv("LLM_MODEL", "deepseek-v4-flash"),
            "LLM Base URL": os.getenv("LLM_BASE_URL", "https://token.sensenova.cn/v1"),
            "OCR Provider": os.getenv("OCR_PROVIDER", "siliconflow"),
            "OCR Model": os.getenv("OCR_MODEL", "deepseek-ai/DeepSeek-OCR"),
            "Embedding Provider": os.getenv("EMBEDDING_PROVIDER", "siliconflow"),
            "Embedding Model": os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
            "Reranker Model": os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
        }
        for k, v in api_configs.items():
            st.markdown(f"- **{k}:** `{v}`")

    with col2:
        st.markdown("### 🗄️ 数据库配置")
        db_configs = {
            "MongoDB Host": os.getenv("MONGODB_URL", "mongodb://admin:password@localhost:27017/resume_rag"),
            "Milvus URI": os.getenv("MILVUS_URI", "http://localhost:19530"),
            "Milvus Collection Prefix": os.getenv("MILVUS_COLLECTION_PREFIX", "resume_"),
            "Redis Host": os.getenv("REDIS_HOST", "localhost"),
            "Redis Port": os.getenv("REDIS_PORT", "6379"),
        }
        for k, v in db_configs.items():
            # Mask passwords
            display_val = v
            if "://" in str(v) and "@" in str(v):
                parts = str(v).split("@")
                prefix = parts[0].split("://")[0]
                display_val = f"{prefix}://***:***@{'@'.join(parts[1:])}"
            st.markdown(f"- **{k}:** `{display_val}`")

    st.markdown("---")
    st.markdown("### 🛡️ 安全配置")
    sec_configs = {
        "JWT Algorithm": os.getenv("JWT_ALGORITHM", "HS256"),
        "JWT Expiration": f"{os.getenv('JWT_EXPIRATION_HOURS', '24')} 小时",
        "CORS Origins": os.getenv("CORS_ORIGINS", '["http://localhost:8501"]'),
        "Log Level": os.getenv("LOG_LEVEL", "INFO"),
    }
    for k, v in sec_configs.items():
        st.markdown(f"- **{k}:** `{v}`")


if __name__ == "__main__":
    main()