p = r"C:\Users\Administrator\Desktop\简历推荐系统\src\frontend\app.py"
with open(p, "r", encoding="utf-8") as f:
    c = f.read()

# Replace init_session to add debug
old_init = '''    # 从 cookie 恢复 JWT（页面刷新后自动登录）
    if not st.session_state.token:
        try:
            cookies = st.context.cookies
            saved = cookies.get("resume_jwt")
            if saved:
                result = verify_token(saved)
                if result:
                    st.session_state.token = saved
                    st.session_state.user_id = result["user_id"]
                    st.session_state.role = result["role"]
        except Exception:
            pass'''

new_init = '''    # 从 cookie 恢复 JWT（页面刷新后自动登录）
    if not st.session_state.token:
        try:
            cookies = st.context.cookies
            st.write(f"DEBUG: cookies keys = {list(cookies.keys())}")
            saved = cookies.get("resume_jwt")
            st.write(f"DEBUG: resume_jwt = {saved[:20] if saved else 'None'}...")
            if saved:
                result = verify_token(saved)
                st.write(f"DEBUG: verify result = {result}")
                if result:
                    st.session_state.token = saved
                    st.session_state.user_id = result["user_id"]
                    st.session_state.role = result["role"]
            else:
                st.write("DEBUG: no cookie found, showing login")
        except Exception as e:
            st.write(f"DEBUG: cookie error = {e}")'''

c = c.replace(old_init, new_init)
with open(p, "w", encoding="utf-8") as f:
    f.write(c)
print("Added debug output to init_session")