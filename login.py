"""
宝可梦加速器 —— 本地自动登录脚本

原理：用 Playwright 在你本机启动一个真实浏览器，打开登录页，
用【真实的鼠标点击 + 键盘输入】填写账号密码。

为什么不用 JS 注入 value：
    该站点（Vuetify/Vue）会检测事件的 isTrusted 标记。JS 合成的
    input/change 事件是 isTrusted:false，会被判为非法输入，导致表单
    被重置、账号字段被清空。而 Playwright 的 click()/type() 走的是浏览器
    层面的真实输入，事件 isTrusted:true，和真人打字完全一致，可正常通过。

全过程可见、代码可审，凭证只从本地 credentials.py 读取，不外传。

关于“页面反复刷新”的真相（已实测确认）：
    该站点内置“开发者工具检测器”。它按窗口内外尺寸差判断 DevTools 是否打开，
    一旦判定为打开，就强制把页面在 /login <-> /error-page 之间反复弹跳。
    - 有窗口(headful)模式会误触发 → 反复刷新（就是你遇到的现象）。
    - 无窗口(headless)模式无窗口装饰、尺寸差为 0 → 不触发，实测 0 跳转、稳定。
    因此本脚本默认用 headless 完成登录。

用法：
    python login.py            # 无窗口，填好账号密码并校验（不提交）
    python login.py --submit   # 无窗口，填好后自动点“登录”，成功则保存会话
    python login.py --submit --show   # 有窗口（调试用；可能触发上述刷新）
"""

import sys
import json
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://web1.52pokemon66.cc/login"

# 从本地凭证文件读取（该文件不纳入版本控制，见 .gitignore）
try:
    from credentials import EMAIL, PASSWORD
except ImportError:
    print("找不到 credentials.py，请先复制 credentials.example.py 为 credentials.py 并填入账号密码。")
    sys.exit(1)

# 逐字输入时每个字符之间的延迟(毫秒)，模拟真人打字节奏
TYPE_DELAY = 40


def fill_like_human(page, selector, value):
    """点击输入框获得焦点，清空后逐字键入 —— 真实键盘事件(isTrusted:true)。"""
    field = page.locator(selector)
    field.click()
    field.fill("")            # 先清空，避免残留
    field.type(value, delay=TYPE_DELAY)


def run(auto_submit: bool, show_window: bool):
    with sync_playwright() as p:
        # 默认 headless=True（无窗口）。原因见文件顶部说明：
        # 该站点的“开发者工具检测器”在【有窗口】模式下会误判，
        # 反复把页面在 /login <-> /error-page 之间弹跳（就是你看到的“多次刷新”）；
        # headless 模式无窗口装饰、尺寸差为 0，不触发检测，实测 0 跳转、稳定。
        browser = p.chromium.launch(headless=not show_window)
        if show_window:
            print("警告：有窗口(--show)模式下，站点的 DevTools 检测可能导致页面反复跳转。")
            print("      如遇刷新循环，请去掉 --show 用默认无窗口模式。")
        page = browser.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        # 这是 Vue SPA，等表单真正渲染出来再操作
        page.wait_for_selector("input[type=text]", timeout=15000)
        page.wait_for_selector("input[type=password]", timeout=15000)

        # 用真实键盘输入填写，避开 isTrusted 检测导致的重置
        fill_like_human(page, "input[type=text]", EMAIL)
        fill_like_human(page, "input[type=password]", PASSWORD)

        # 校验是否真的填进去了（防止被站点重置）
        email_val = page.locator("input[type=text]").input_value()
        pwd_val = page.locator("input[type=password]").input_value()
        if email_val != EMAIL or not pwd_val:
            print(f"填充校验未通过：账号框='{email_val}'，密码是否有值={bool(pwd_val)}")
            print("站点可能重置了表单。若你用了 --show，请改用默认无窗口模式重试。")
            browser.close()
            return

        print("账号密码已填入并校验通过。")

        if auto_submit:
            page.get_by_role("button", name="登录").click()
            print("已点击登录。登录接口会返回加密响应，前端需要几秒解码并建立会话，")
            print("对应页面上“正在验证账号信息并建立安全会话”的提示，正在等待……")
            # 登录成功信号：跳转到既不是 /login 也不是 /error-page 的页面。
            def logged_in(url):
                return "/login" not in url and "/error-page" not in url
            try:
                page.wait_for_url(logged_in, timeout=15000)
                print(f"登录成功，已跳转到：{page.url}")
                # 该站点把登录态存在 localStorage（key: user 内含 token、auth_data），
                # 不是 cookie，所以要专门导出这两项供 use_session.py 复用。
                auth = page.evaluate(
                    "() => ({ user: localStorage.getItem('user'),"
                    " auth_data: localStorage.getItem('auth_data') })"
                )
                with open("session_state.json", "w", encoding="utf-8") as f:
                    json.dump(auth, f, ensure_ascii=False, indent=2)
                print("登录态已保存到 session_state.json，可用 use_session.py 免登录复用。")
            except Exception:
                print(f"未在预期时间内跳转，当前仍在：{page.url}")
                print("可能是账号密码有误，或需要额外验证。")
        else:
            print("已按填充模式完成（未提交）。加 --submit 可自动点击登录并保存会话。")
            if show_window:
                print("有窗口模式：保持打开，按回车结束。")
                input()

        browser.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    run(
        auto_submit="--submit" in args,
        show_window="--show" in args,
    )
