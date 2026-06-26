"""
智能招聘 RAG 推荐系统 - Streamlit 主入口 v2.0
JWT 通过 JS document.cookie 持久化，刷新页面自动恢复登录
"""

import streamlit as st
import streamlit.components.v1 as components
import json as _json
from src.frontend.api_client import login, logout, health_check, verify_token

st.set_page_config(
    page_title="智能招聘 RAG 推荐系统",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp { max-width: 100%; }
    [data-testid="stSidebar"] { background-color: #f8f9fa; }
    .main .block-container { padding-top: 1rem; }
</style>
""", unsafe_allow_html=True)


def init_session():
    defaults = {
        "token": None, "user_id": None, "role": None,
        "conversation_id": None, "messages": [], "last_candidates": [],
        "compare_candidates": [], "search_filters": {}, "current_resume_id": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if not st.session_state.token:
        token = _try_read_jwt()
        if token:
            result = verify_token(token)
            if result:
                st.session_state.token = token
                st.session_state.user_id = result["user_id"]
                st.session_state.role = result["role"]


def _try_read_jwt():
    # Mechanism 1: st.context.cookies (HTTP request cookies on refresh)
    try:
        saved = st.context.cookies.get("resume_jwt")
        if saved:
            return saved
    except Exception:
        pass

    # Mechanism 2: JS document.cookie bridge via components.html
    js_token = components.html("""
    <script>
    (function() {
        var cookies = document.cookie.split('; ');
        var token = '';
        for (var i = 0; i < cookies.length; i++) {
            var eq = cookies[i].indexOf('=');
            if (eq === -1) continue;
            if (cookies[i].substring(0, eq).trim() === 'resume_jwt') {
                token = decodeURIComponent(cookies[i].substring(eq + 1));
                break;
            }
        }
        if (window.Streamlit) {
            window.Streamlit.setComponentValue(token || null);
        }
    })();
    </script>
    """, height=0)

    if js_token:
        return js_token

    return None


def save_jwt_cookie():
    token = st.session_state.token or ""
    # Mechanism 1: st.context.cookies
    try:
        st.context.cookies["resume_jwt"] = token
    except Exception:
        pass
    # Mechanism 2: JS document.cookie with path=/ and 7-day expiry
    safe_token = _json.dumps(token)
    components.html("""
    <script>
    (function() {
        var d = new Date();
        d.setTime(d.getTime() + (7 * 24 * 60 * 60 * 1000));
        var token = JSON_PLACEHOLDER;
        document.cookie = 'resume_jwt=' + encodeURIComponent(token) +
            '; path=/; expires=' + d.toUTCString() + '; SameSite=Lax';
    })();
    </script>
    """.replace("JSON_PLACEHOLDER", safe_token), height=0)


def clear_jwt_cookie():
    try:
        st.context.cookies["resume_jwt"] = ""
    except Exception:
        pass
    components.html("""
    <script>
    document.cookie = 'resume_jwt=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax';
    </script>
    """, height=0)


def render_login():
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 🎯 智能招聘 RAG 推荐系统")
        st.markdown("基于 RAG 的企业智能招聘助手")
        st.markdown("---")
        with st.form("login_form"):
            username = st.text_input("👤 用户名", placeholder="请输入用户名")
            password = st.text_input("🔑 密码", type="password", placeholder="请输入密码")
            submitted = st.form_submit_button("登 录", use_container_width=True, type="primary")
            if submitted:
                if login(username, password):
                    save_jwt_cookie()
                    st.success("✅ 登录成功！")
                    st.rerun()
                else:
                    st.error("❌ 用户名或密码错误")
        st.markdown("---")
        st.markdown("### 📋 测试账号")
        for uname, pwd, role, desc in [
            ("admin", "admin123", "管理员", "全部权限"),
            ("hr", "hr123", "HR 用户", "搜索、上传、查看"),
            ("viewer", "viewer123", "只读用户", "仅查看推荐结果"),
        ]:
            st.markdown(f"- **{uname}** / `{pwd}` — {role} ({desc})")
        st.markdown("---")
        health = health_check()
        if health:
            ver = health.get("version", "-")
            st.success(f"🟢 系统正常 | 版本 {ver}")
        else:
            st.error("🔴 系统异常，请检查服务状态")


def render_sidebar():
    with st.sidebar:
        st.markdown("## 🎯 智能招聘助手")
        st.markdown("---")
        st.markdown(f"**👤 {st.session_state.user_id}**")
        st.markdown(f"**🏷️ {st.session_state.role}**")
        st.markdown("---")
        st.markdown("### 📌 核心功能")
        st.page_link("pages/1_智能搜索.py", label="💬 智能搜索", icon="🔍")
        st.page_link("pages/2_简历上传.py", label="📄 简历上传", icon="📤")
        st.page_link("pages/4_对话历史.py", label="🕐 对话历史", icon="📝")
        n = len(st.session_state.get("compare_candidates", []))
        label = f"📊 候选人对比 ({n})" if n else "📊 候选人对比"
        st.page_link("pages/7_候选人对比.py", label=label, icon="⚖️")
        st.markdown("---")
        st.markdown("### 📋 数据管理")
        st.page_link("pages/6_简历详情.py", label="📋 简历详情", icon="📑")
        if st.session_state.get("role") == "admin":
            st.page_link("pages/3_简历管理.py", label="🗂️ 简历管理", icon="⚙️")
        st.markdown("---")
        st.markdown("### 📊 系统")
        st.page_link("pages/5_系统仪表盘.py", label="📊 系统仪表盘", icon="📈")
        if st.session_state.get("role") == "admin":
            st.page_link("pages/8_用户管理.py", label="👥 用户管理", icon="🔑")
        st.markdown("---")
        if st.button("🚪 退出登录", use_container_width=True):
            logout()
            clear_jwt_cookie()
            st.rerun()
        st.markdown("---")
        health = health_check()
        if health:
            st.success("🟢 系统正常")
        else:
            st.error("🔴 系统异常")


def main():
    init_session()
    if not st.session_state.token:
        render_login()
    else:
        render_sidebar()
        st.markdown("## 👋 欢迎使用智能招聘 RAG 推荐系统")
        st.markdown("请从左侧导航栏选择功能页面。")
        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info("**💬 智能搜索**\n\n输入自然语言描述招聘需求，AI 智能匹配候选人。")
        with col2:
            st.info("**📄 简历上传**\n\n上传 PDF/DOCX/JSON 简历，自动解析入库。")
        with col3:
            st.info("**📊 系统仪表盘**\n\n查看系统运行状态和数据统计。")
        st.markdown("---")
        st.markdown("### 🚀 快速入口")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.page_link("pages/1_智能搜索.py", label="💬 开始搜索")
        with col2:
            st.page_link("pages/2_简历上传.py", label="📄 上传简历")
        with col3:
            st.page_link("pages/5_系统仪表盘.py", label="📊 查看仪表盘")
        with col4:
            if st.session_state.get("compare_candidates"):
                st.page_link("pages/7_候选人对比.py", label="📊 候选人对比")


if __name__ == "__main__":
    main()
