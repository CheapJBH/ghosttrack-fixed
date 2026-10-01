# ghosttrack-fixed

IP 归属地、手机号段信息、用户名注册地侦察工具。

基于 [HunxByts/GhostTrack](https://github.com/HunxByts/GhostTrack) 重写。原项目已 4 年未更新，存在请求无超时、明文 HTTP、装饰器漏 `return`、无限递归、以及靠 `status_code == 200` 判定导致的高误报等问题。本版本逐项修复，并按实测数据重建了站点判据表。

---

## 安装

```bash
git clone https://github.com/CheapJBH/ghosttrack-fixed.git
cd ghosttrack-fixed
pip install -r requirements.txt
```

依赖只有两个：`requests`（网络请求）和 `phonenumbers`（号码段数据库）。

## 使用

不带参数进入交互菜单：

```bash
python3 GhostTR.py
```

也可以直接用命令行，适合写脚本：

```bash
# IP 归属地
python3 GhostTR.py ip 8.8.8.8

# 本机公网 IP
python3 GhostTR.py selfip

# 号码段信息（强烈建议带国际区号）
python3 GhostTR.py phone +8613800138000
python3 GhostTR.py phone 13800138000 --region CN

# 用户名注册地扫描
python3 GhostTR.py user sindresorhus

# 只扫指定站点
python3 GhostTR.py user torvalds --only GitHub,GitLab,Chess

# 导出 JSON
python3 GhostTR.py user torvalds --out result.json

# 网络较差时缩短超时（放在子命令前面）
python3 GhostTR.py --timeout 6 user torvalds

# 查看全部目标站点
python3 GhostTR.py sites
```

## 三个功能说明

**IP 追踪** 走 `ipwho.is` 公开 API，返回国家、城市、坐标、ASN、ISP、时区等信息。原版用的是明文 `http://`，手机网络下容易被中间人改包，本版改为 HTTPS 并对响应结构做校验。

**号码查询不追踪位置**。它读的是本地号码段数据库（`phonenumbers`），告诉你号段注册地、运营商、号码类型和时区，不联网查询任何实时定位数据，也不代表号码持有者的当前位置。原版默认地区写死为印尼（`ID`），本版可用 `--region` 指定。

**用户名注册地扫描** 会向 41 个平台查询用户名是否存在。

## 关于准确率

这类工具最容易出的问题是**误报**：很多网站对不存在的用户名也返回 HTTP 200（软 404 或登录墙），只看状态码会把一堆不存在的账号报成「已注册」。

本版为此做了两件事：

一是站点表里区分了判据类型。可靠的站点优先用官方 API（GitHub、GitLab、Dev.to、Chess、Keybase 等返回 404 即不存在）；网页类站点则在页面里匹配「不存在时才会出现的特征串」。

二是每个站点的判据都经过实测 A/B 对照：拿真实存在的用户名和不存在的随机用户名各请求一次，比较响应差异，确认能区分才启用。

实测发现并移除了 5 个无法可靠判定的站点：

| 站点 | 移除原因 |
|------|----------|
| PyPI | 存在与不存在的用户页面返回完全相同的响应，无法区分 |
| Trello | 同上，SPA 对任何用户名都返回同一页面 |
| Kaggle | 同上，页面长度仅差几十字节且无稳定特征 |
| Spotify | 该接口需要 OAuth 认证，永远返回 401 |
| Coder | 域名无法解析 |

扫描结果里，`已注册` 分类中如果包含未实测验证的站点，会额外提示可能存在误报。

需要说明的是，判据是站点方的实现细节，可能随对方改版失效。某一类结果全为空或全为已注册时，通常意味着对方改了页面结构，而不是目标真的注册了所有平台。

**网络可达性**：部分平台（Facebook、Instagram、Telegram、X 等）在部分网络环境下无法访问，会显示为超时而非误判。扫描结果里的 `请求失败` 就是这类情况，不影响其他站点的判定。

## 测试

```bash
python3 -m unittest test_ghosttrack -v
```

87 个测试，全部离线运行，不发起真实网络请求（用 mock 替换 HTTP 层），覆盖分类判定逻辑、请求异常处理、站点表完整性、号码解析、命令分发，以及一道检查源码中不存在 `eval`/`exec`/`subprocess` 等危险调用的测试。

## 安全说明

- 不收集、不上传任何数据。输入的 IP、号码、用户名只用于发起查询请求，本工具不落库、不回传、不含任何遥测。
- 只向公开的第三方查询接口和各平台的公开主页发 GET 请求，无任何写操作。
- 除导出功能外不写任何文件；不删除任何文件。
- 网络请求全部走 HTTPS。

## 法律与用途

本工具仅用于安全研究、授权测试，以及查询你自己拥有的账号。

对不属于自己的账号或身份进行侦察可能违反平台服务条款，在部分司法辖区也可能违法。请勿用于骚扰、跟踪或侵犯他人隐私。

## 原项目与许可

原作者：[HunxByts/GhostTrack](https://github.com/HunxByts/GhostTrack)（原仓库未附 LICENSE 文件）。

本仓库代码为重写版本，以 MIT 许可发布，详见 [LICENSE](LICENSE)。
