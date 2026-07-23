"""
复用已保存的登录态，直接进入主页（免登录）。

前置：先跑过 `python login.py --submit` 成功登录，生成 session_state.json。

原理：
    该站点的登录态存在 localStorage 的 user / auth_data 两个 key，
    API 靠请求头 Authorization: Bearer <token> 鉴权，路由 /main 需要
    user.token 才放行，否则守卫把你踢回 /login。
    因此这里用 add_init_script 在【页面任何 JS 运行之前】把这两个 key
    写回 localStorage，再访问 /main/dashboard，守卫校验通过即进入主页。

    注意开发者工具检测：本脚本默认 headless（无窗口），不会触发站点的
    刷新循环。加 --show 可看窗口（调试用，可能触发跳转）。

用法：
    python use_session.py                  # 无窗口，复用会话直达 /plan/8
    python use_session.py --show           # 有窗口查看（调试用）
    python use_session.py /order           # 直达其它受保护页（传路径即可）
    python use_session.py --target /plan/8 # 同上，显式指定目标

订购流程（在 /plan/8 上执行）：
    python use_session.py --order                      # 选“每月付款”，走到“立即订购”前停下（不真正下单）
    python use_session.py --order --coupon ABC123      # 同上，并填入优惠码 ABC123 后点“使用”
    python use_session.py --order --cycle 季度付款      # 改选付款周期（每月/季度/半年/年度付款）
    python use_session.py --order --coupon ABC123 --confirm  # 真正点击“立即订购”下单
    #   ↑ 安全阀：默认不点“立即订购”，只把表单准备好；加 --confirm 才真正下单。
"""

import os
import sys
import json
from playwright.sync_api import sync_playwright

BASE = "https://web1.52pokemon66.cc"
# 复用会话后要直达的目标页。默认 /plan/8（套餐详情页）。
# 路由守卫只校验 localStorage 里的 auth_data 是否存在：有就放行、没有踢回 /login
# （已从站点路由守卫代码确认）。/plan/8 属受保护页，需 auth_data 才能进。
DEFAULT_TARGET = "/plan/8"
SESSION_FILE = "session_state.json"

# 订购页选择器（已从 /plan/8 实测确认）：
#   付款周期行：.price-option-row（用文本“每月付款/季度付款/…”过滤定位）
#   优惠码输入框：input[placeholder=输入优惠码]
#   优惠码“使用”按钮：.coupon-card__submit
#   “立即订购”按钮：.order-action-btn（未选周期时 disabled，选中后变可用）
CYCLE_ROW = ".price-option-row"
COUPON_INPUT = "input[placeholder='输入优惠码']"
COUPON_SUBMIT = ".coupon-card__submit"
ORDER_BTN = ".order-action-btn"


def do_order(page, cycle: str, coupon: str, confirm: bool):
    """在 /plan/8 上：选付款周期 → （可选）填优惠码并点“使用” → 走到/点击“立即订购”。"""
    # 1) 选择付款周期（点击整行，整行 cursor:pointer）
    row = page.locator(CYCLE_ROW).filter(has_text=cycle).first
    try:
        row.wait_for(state="visible", timeout=8000)
    except Exception:
        print(f"未找到付款周期“{cycle}”。可选：每月付款/季度付款/半年付款/年度付款。")
        return
    row.click()
    print(f"已选择付款周期：{cycle}")
    page.wait_for_timeout(600)

    # 2) 优惠码（可选）：填入后点“使用”，让站点校验适用周期
    if coupon:
        field = page.locator(COUPON_INPUT)
        field.wait_for(state="visible", timeout=8000)
        field.click()
        field.fill("")
        field.type(coupon, delay=40)   # 真实键盘输入，避开 isTrusted 检测
        page.locator(COUPON_SUBMIT).click()
        print(f"已填入优惠码并点击“使用”：{coupon}")
        page.wait_for_timeout(1200)    # 等待后端校验返回

    # 3) 立即订购
    order = page.locator(ORDER_BTN)
    try:
        order.wait_for(state="visible", timeout=8000)
    except Exception:
        print("未找到“立即订购”按钮，流程终止。")
        return
    if order.is_disabled():
        print("“立即订购”仍不可用（可能周期未选中或优惠码校验未通过），未下单。")
        return

    if confirm:
        order.click()
        print("已点击“立即订购”，正在提交订单……")
        page.wait_for_timeout(2500)
        print(f"点击后当前页面：{page.url}")
    else:
        print("表单已就绪，“立即订购”可点击。安全阀生效：未真正下单。")
        print("如需真正提交，请加 --confirm 参数。")


def main(show_window: bool, target: str,
         do_order_flow: bool = False, cycle: str = "每月付款",
         coupon: str = "", confirm: bool = False):
    if not os.path.exists(SESSION_FILE):
        print(f"找不到 {SESSION_FILE}，请先运行：python login.py --submit")
        sys.exit(1)

    with open(SESSION_FILE, encoding="utf-8") as f:
        auth = json.load(f)

    # 路由守卫只校验 auth_data；user 里含 token 供 API 鉴权用。两者都应存在。
    if not auth.get("auth_data") and not auth.get("user"):
        print("会话文件里没有 auth_data / user，可能上次登录未成功。请重新登录。")
        sys.exit(1)

    # 在页面加载最早期把登录态写回 localStorage（供路由守卫和 API 鉴权用）
    user_js = json.dumps(auth.get("user") or "")
    authdata_js = json.dumps(auth.get("auth_data") or "")
    init_script = f"""
        try {{
            const u = {user_js};
            const a = {authdata_js};
            if (u) localStorage.setItem('user', u);
            if (a) localStorage.setItem('auth_data', a);
        }} catch (e) {{}}
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not show_window)
        # 用搜索引擎(Googlebot) UA：站点的 disable-devtool 配置了 seo:true，
        # 检测到搜索引擎爬虫会直接放行、根本不启动检测器（库源码里的
        # `if (seo && seoBot) return "seobot"` 白名单通道）。这样即便 --show
        # 有窗口模式也不会再被弹到 /error-page。比拦跳转/爆破 token 都干净可靠。
        context = browser.new_context(
            user_agent="Mozilla/5.0 (compatible; Googlebot/2.1; "
                       "+http://www.google.com/bot.html)"
        )
        # 关键：init_script 在每个新文档的任何脚本之前运行，
        # 保证路由守卫读 localStorage 时 token 已就位。
        context.add_init_script(init_script)
        page = context.new_page()

        target_url = BASE + target
        page.goto(target_url, wait_until="domcontentloaded")
        # 前端路由守卫/数据请求是异步的：先给它机会稳定到目标页。
        # 若能在超时内停在目标路径就提前结束等待，否则等满兜底时间。
        try:
            page.wait_for_url(lambda u: target.strip("/") in u, timeout=6000)
        except Exception:
            page.wait_for_timeout(2000)

        current = page.url
        if "/login" in current:
            print(f"会话已失效（被踢回登录页：{current}）。请重新运行 login.py --submit。")
        elif "/error-page" in current:
            print(f"被开发者工具检测拦截（{current}）。请用默认无窗口模式，勿加 --show。")
        else:
            # 停在目标页或其它已登录页 = 会话有效
            print(f"会话有效，已进入目标页：{current}")
            print(f"页面标题：{page.title()}")
            if target.strip("/") not in current:
                print(f"提示：期望进入 {target}，实际停在上面地址，可能该路径已变化。")

            # 会话有效且请求了订购流程时执行（需在 /plan/8 这类订购页上）
            if do_order_flow:
                if "/plan/" not in current:
                    print(f"当前页 {current} 不是套餐订购页，订购流程需在 /plan/8 上执行。")
                else:
                    do_order(page, cycle=cycle, coupon=coupon, confirm=confirm)

        if show_window:
            print("有窗口模式：保持打开，按回车结束。")
            input()

        browser.close()


def _opt_value(args, name, default=None):
    """取 `--name value` 形式的参数值，没有则返回 default。"""
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return default


if __name__ == "__main__":
    args = sys.argv[1:]
    # 目标路径：可用 --target /xxx 指定，或直接把一个以 / 开头的参数当路径；默认 /plan/8
    target = _opt_value(args, "--target")
    if target is None:
        target = next((a for a in args if a.startswith("/")), DEFAULT_TARGET)

    main(
        show_window="--show" in args,
        target=target,
        do_order_flow="--order" in args,
        cycle=_opt_value(args, "--cycle", "每月付款"),
        coupon=_opt_value(args, "--coupon", ""),
        confirm="--confirm" in args,
    )
