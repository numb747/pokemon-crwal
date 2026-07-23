# 宝可梦加速器 —— 本地自动登录

在你本机运行的自动登录脚本。用 Playwright 启动真实浏览器，自动填入账号密码。
全部代码本地可读、可审，凭证只存本地。

## 安装（首次运行一次）

```powershell
pip install playwright
python -m playwright install chromium
```

## 配置账号密码

复制模板，填入你自己的账号密码：

```powershell
copy credentials.example.py credentials.py
```

然后编辑 `credentials.py`。该文件已被 `.gitignore` 忽略，不会外泄。

## 运行

第一次（或会话过期后）真正登录一次，生成会话文件：

```powershell
python login.py --submit
```

之后每次免登录，直接进套餐页 /plan/8：

```powershell
python use_session.py                  # 复用会话直达 /plan/8
python use_session.py /order           # 直达其它受保护页（传路径即可）
python use_session.py --show           # 有窗口查看（调试用）
```

## 工作原理（都已实测确认）

- **填值**：页面是 Vue(Vuetify) 单页应用，且会检测事件的 `isTrusted`。
  所以脚本用 Playwright 的真实鼠标点击 + 键盘输入（isTrusted:true），
  而不是 JS 注入 value（isTrusted:false 会被判为非法、清空表单）。
- **无窗口(headless)**：站点内置开发者工具检测器（disable-devtool，每秒检测），
  在有窗口模式下会误判并把页面在 /login ↔ /error-page 反复弹跳。
  headless 模式无窗口装饰、不触发检测，因此脚本默认 headless。
  `--show` 仅供调试，可能重现刷新循环。
- **会话复用**：登录态存在 localStorage 的 `user`(含 token) / `auth_data`，
  不是 cookie。`login.py` 成功后导出到 `session_state.json`；
  `use_session.py` 在页面 JS 运行前用 add_init_script 写回这两个 key，
  路由守卫校验 `auth_data` 通过后即进入受保护页。
- **登录接口**：POST `api123.136470.xyz/api/v1/passport/auth/login`，
  multipart 提交 email/password，响应是 Base64+字符替换的两层编码，
  由前端自动解码（对应“正在验证账号信息并建立安全会话”的等待提示）。

## 安全提醒

- 凭证以明文存在 `credentials.py`，会话 token 存在 `session_state.json`，
  两者都已被 `.gitignore` 忽略。仅限个人电脑使用，别发给别人或传公开仓库。
- token 会过期。`use_session.py` 检测到被踢回登录页时会提示重新运行 `login.py --submit`。
