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
    该站点用开源库 disable-devtool 做开发者工具检测。有窗口模式会被误判为
    “DevTools 打开”，从而把页面弹到 /error-page（在登录页表现为反复刷新）。
    解法：用搜索引擎(Googlebot) 的 User-Agent，命中该库的 seo 白名单
    （源码 `if (seo && seoBot) return "seobot"`），检测器根本不启动。
    因此本脚本无论 headless 还是 --show 有窗口，都不会再刷新。

用法：
    python login.py            # 无窗口，填好账号密码并校验（不提交）
    python login.py --submit   # 无窗口，填好后自动点“登录”，成功则保存会话
    python login.py --submit --show   # 有窗口查看过程（已用 UA 白名单，不会刷新）
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
        # 默认 headless=True（无窗口）；--show 时开窗口便于观察。
        # 站点用 disable-devtool 做开发者工具检测：有窗口模式会被误判，
        # 把页面弹到 /error-page（登录页则表现为反复刷新）。
        # 用搜索引擎(Googlebot) UA 命中该库的 seo 白名单，使检测器根本不启动，
        # 因此有窗口模式也不会再刷新。（详见 use_session.py 里的同款说明）
        browser = p.chromium.launch(headless=not show_window)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (compatible; Googlebot/2.1; "
                       "+http://www.google.com/bot.html)"
        )
        page = context.new_page()
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
            print("站点可能重置了表单，请重试；若仍失败，检查账号密码是否正确。")
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
