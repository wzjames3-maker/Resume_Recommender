from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    # 1. Login page
    page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
    time.sleep(4)
    page.screenshot(path="/app/screenshot_login_new.png")
    print("1. Login page captured")

    # 2. Fill login form and submit
    inputs = page.query_selector_all("input")
    for inp in inputs:
        input_type = inp.get_attribute("type") or ""
        label = inp.get_attribute("aria-label") or ""
        placeholder = inp.get_attribute("placeholder") or ""
        print(f"  Input: type={input_type}, label={label}, placeholder={placeholder}")

    # Try filling by index
    text_inputs = page.query_selector_all("input[type='text']")
    pwd_inputs = page.query_selector_all("input[type='password']")
    if text_inputs:
        text_inputs[0].fill("admin")
    if pwd_inputs:
        pwd_inputs[0].fill("admin123")

    # Click login button
    buttons = page.query_selector_all("button")
    for btn in buttons:
        txt = btn.inner_text()
        print(f"  Button: {txt}")
        if "登录" in txt or "登" in txt:
            btn.click()
            print("  Clicked login button")
            break

    time.sleep(6)
    page.screenshot(path="/app/screenshot_dashboard.png")
    print("2. Dashboard captured")

    # 3. Navigate to search page via sidebar
    try:
        page.click("text=智能搜索", timeout=5000)
        time.sleep(4)
        page.screenshot(path="/app/screenshot_search_page.png")
        print("3. Search page captured")
    except Exception as e:
        print(f"3. Sidebar click failed: {e}")

    # 4. Navigate to upload page
    try:
        page.click("text=简历上传", timeout=5000)
        time.sleep(4)
        page.screenshot(path="/app/screenshot_upload_page.png")
        print("4. Upload page captured")
    except Exception as e:
        print(f"4. Upload page click failed: {e}")

    # 5. Navigate to resume management
    try:
        page.click("text=简历管理", timeout=5000)
        time.sleep(4)
        page.screenshot(path="/app/screenshot_manage_page.png")
        print("5. Manage page captured")
    except Exception as e:
        print(f"5. Manage page click failed: {e}")

    # 6. Navigate to system dashboard
    try:
        page.click("text=系统仪表盘", timeout=5000)
        time.sleep(4)
        page.screenshot(path="/app/screenshot_sys_dashboard.png")
        print("6. System dashboard captured")
    except Exception as e:
        print(f"6. Dashboard click failed: {e}")

    browser.close()
    print("All screenshots done!")
