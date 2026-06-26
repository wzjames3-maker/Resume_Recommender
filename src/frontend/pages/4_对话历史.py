"""
智能招聘 RAG 推荐系统 - 对话历史页面

查看、管理历史对话记录
"""

import streamlit as st
from src.frontend.api_client import list_conversations, get_conversation, delete_conversation

st.set_page_config(page_title="对话历史", page_icon="🕐", layout="wide")


def format_time(iso_str):
    if not iso_str:
        return "-"
    return iso_str[:19].replace("T", " ")


def main():
    if not st.session_state.get("token"):
        st.warning("⚠️ 请先登录")
        st.stop()

    st.title("🕐 对话历史")
    st.caption("查看和管理您的历史对话记录")

    if "conv_page" not in st.session_state:
        st.session_state.conv_page = 1

    # 获取对话列表
    data = list_conversations(page=st.session_state.conv_page, size=10)

    if not data:
        st.info("📭 暂无对话记录")
        return

    items = data.get("items", [])
    total = data.get("total", 0)

    # 统计
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📝 对话总数", total)
    with col2:
        active = sum(1 for i in items if i.get("status") == "active")
        st.metric("🟢 活跃对话", active)
    with col3:
        total_turns = sum(i.get("turn_count", 0) for i in items)
        st.metric("💬 总对话轮次", total_turns)

    st.markdown("---")

    # 分页控制
    page_size = 10
    total_pages = max(1, (total + page_size - 1) // page_size)
    col1, col2, col3 = st.columns([1, 3, 1])
    with col1:
        if st.button("⬅️ 上一页") and st.session_state.conv_page > 1:
            st.session_state.conv_page -= 1
            st.rerun()
    with col2:
        st.markdown(f"<center>第 {st.session_state.conv_page}/{total_pages} 页</center>", unsafe_allow_html=True)
    with col3:
        if st.button("下一页 ➡️") and st.session_state.conv_page < total_pages:
            st.session_state.conv_page += 1
            st.rerun()

    # 对话列表
    if not items:
        st.info("📭 暂无对话记录")
        return

    for item in items:
        sid = item.get("session_id", "")
        status = item.get("status", "-")
        created = format_time(item.get("created_at"))
        last_active = format_time(item.get("last_active_at"))
        turns = item.get("turn_count", 0)
        status_icon = "🟢" if status == "active" else "⚪"

        with st.expander(f"{status_icon} 对话 {sid[:12]}...  |  {turns} 轮  |  {created}"):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**会话 ID:** `{sid}`")
                st.markdown(f"**状态:** {status}")
                st.markdown(f"**创建时间:** {created}")
            with col2:
                st.markdown(f"**对话轮次:** {turns}")
                st.markdown(f"**最后活跃:** {last_active}")

            # 查看详情
            if st.button("📜 查看对话内容", key=f"view_{sid}"):
                detail = get_conversation(sid)
                if detail:
                    messages = detail.get("messages", [])
                    if messages:
                        for msg in messages:
                            role = msg.get("role", "-")
                            content = msg.get("content", "")
                            icon = "👤" if role == "user" else "🤖"
                            st.markdown(f"**{icon} {role}:**")
                            st.markdown(content)
                            st.markdown("---")
                    else:
                        st.info("暂无消息记录")
                else:
                    st.error("获取对话详情失败")

            # 删除
            st.markdown("---")
            if st.button("🗑️ 删除此对话", key=f"del_{sid}", type="secondary"):
                st.session_state[f"confirm_del_conv_{sid}"] = True

            if st.session_state.get(f"confirm_del_conv_{sid}"):
                st.warning("确定删除此对话？")
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("✅ 确认", key=f"yes_{sid}", type="primary"):
                        if delete_conversation(sid):
                            st.success("✅ 已删除")
                            st.session_state[f"confirm_del_conv_{sid}"] = False
                            st.rerun()
                        else:
                            st.error("删除失败")
                with cc2:
                    if st.button("❌ 取消", key=f"no_{sid}"):
                        st.session_state[f"confirm_del_conv_{sid}"] = False
                        st.rerun()


if __name__ == "__main__":
    main()
