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


def main(show_window: bool, target: str):
    if not os.path.exists(SESSION_FILE):
        print(f"找不到 {SESSION_FILE}，请先运行：python login.py --submit")
        sys.exit(1)

    with open(SESSION_FILE, encoding="utf-8") as f:
        auth = json.load(f)

    # 路由守卫只校验 auth_data；user 里含 token 供 API 鉴权用。两者都应存在。
    if not auth.get("auth_data") and not auth.get("user"):
        print("会话文件里没有 auth_data / user，可能上次登录未成功。请重新登录。")
        sys.exit(1)

    # 构造一段在页面加载最早期执行的脚本：
    #   1) 把登录态写回 localStorage（供路由守卫和 API 鉴权用）
    #   2) 中和站点的 disable-devtool：不管哪个检测器触发，其最终动作都是
    #      把页面导航到 /error-page。在最早期拦掉所有指向 error-page 的跳转，
    #      检测可以继续跑，但“惩罚跳转”被无效化，页面稳定停在目标页。
    #      （这让 --show 有窗口模式也不再出现 error-page → dashboard 的弹跳）
    user_js = json.dumps(auth.get("user") or "")
    authdata_js = json.dumps(auth.get("auth_data") or "")
    init_script = f"""
        try {{
            const u = {user_js};
            const a = {authdata_js};
            if (u) localStorage.setItem('user', u);
            if (a) localStorage.setItem('auth_data', a);
        }} catch (e) {{}}
        try {{
            const isErr = (u) => typeof u === 'string' && u.indexOf('error-page') >= 0;
            const _assign = Location.prototype.assign;
            const _replace = Location.prototype.replace;
            Location.prototype.assign = function(u) {{ if (isErr(u)) return; return _assign.call(this, u); }};
            Location.prototype.replace = function(u) {{ if (isErr(u)) return; return _replace.call(this, u); }};
            const _push = history.pushState, _rep = history.replaceState;
            history.pushState = function(...a) {{ if (isErr(a[2])) return; return _push.apply(this, a); }};
            history.replaceState = function(...a) {{ if (isErr(a[2])) return; return _rep.apply(this, a); }};
            const hd = Object.getOwnPropertyDescriptor(Location.prototype, 'href');
            if (hd && hd.set) {{
                Object.defineProperty(location, 'href', {{
                    get: hd.get.bind(location),
                    set: (v) => {{ if (!isErr(v)) hd.set.call(location, v); }},
                    configurable: true
                }});
            }}
        }} catch (e) {{}}
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not show_window)
        context = browser.new_page().context
        # 关键：init_script 在每个新文档的任何脚本之前运行，
        # 保证路由守卫读 localStorage 时 token 已就位。
        context.add_init_script(init_script)
        page = context.pages[0]

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

        if show_window:
            print("有窗口模式：保持打开，按回车结束。")
            input()

        browser.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    # 目标路径：可用 --target /xxx 指定，或直接把一个以 / 开头的参数当路径；默认 /plan/8
    target = DEFAULT_TARGET
    if "--target" in args:
        i = args.index("--target")
        if i + 1 < len(args):
            target = args[i + 1]
    else:
        for a in args:
            if a.startswith("/"):
                target = a
                break
    main(show_window="--show" in args, target=target)
