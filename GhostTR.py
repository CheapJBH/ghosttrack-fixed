#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import requests
except ImportError:
    sys.exit("缺少依赖 requests，请先执行: pip install requests")

try:
    import phonenumbers
    from phonenumbers import carrier, geocoder
    from phonenumbers import timezone as pn_timezone
except ImportError:
    phonenumbers = None

TIMEOUT = (3.05, 8.0)
USER_AGENT = "ghosttrack-fixed/1.0 (+https://github.com/CheapJBH/ghosttrack-fixed)"
IPWHO_ENDPOINT = "https://ipwho.is/{}"
IP_ECHO_ENDPOINTS = (
    "https://checkip.amazonaws.com",
    "https://icanhazip.com",
    "https://ifconfig.me/ip",
    "https://ident.me",
    "https://api.ipify.org",
    "https://ipinfo.io/ip",
)
IPV6_REGEX = r"^[0-9a-fA-F:]+$"
MAX_WORKERS = 10


def set_timeout(seconds: float) -> None:
    global TIMEOUT
    TIMEOUT = (min(3.05, seconds), seconds)

BANNER = r"""
   ___  _  _    _    ___ _____ ___   _____ _   _
  / _ \| |/ |  / \  | _ \_   _|_ _| |_   _| \ | |
 | | | | ' | / _ \ |  _/| | | | | | | | | |  \| |
 | |_| | | |/ ___ \| |  | | | | | | | | | |\  |
  \___/|_|/_/   \_\_| |_| |_|  |_| |_|  |_| \_\_|
"""


class C:
    on = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    r = "\033[1;31m" if on else ""
    g = "\033[1;32m" if on else ""
    y = "\033[1;33m" if on else ""
    b = "\033[1;34m" if on else ""
    c = "\033[1;36m" if on else ""
    w = "\033[1;37m" if on else ""
    d = "\033[2;37m" if on else ""
    x = "\033[0m" if on else ""


@dataclass(frozen=True)
class Site:
    name: str
    url: str
    status_not_found: tuple = (404, 410)
    present_markers: tuple = ()
    absent_markers: tuple = ()
    verified: bool = False


SITES: tuple = (
    Site("GitHub", "https://api.github.com/users/{}", status_not_found=(404,),
         present_markers=('"login"',), verified=True),
    Site("GitHub Gist", "https://api.github.com/users/{}/gists",
         status_not_found=(404,), present_markers=("[",), verified=True),
    Site("Bitbucket", "https://bitbucket.org/{}/", status_not_found=(404,),
         absent_markers=("not found",), verified=True),
    Site("Dev.to", "https://dev.to/api/users/by_username?url={}",
         status_not_found=(404,), present_markers=('"username"',), verified=True),
    Site("HackerNews", "https://hacker-news.firebaseio.com/v0/user/{}.json",
         present_markers=('"id"',), verified=True),
    Site("Chess", "https://api.chess.com/pub/player/{}", status_not_found=(404,),
         present_markers=('"player_id"',), verified=True),
    Site("Keybase", "https://keybase.io/_/api/1.0/user/lookup.json?username={}",
         present_markers=('"code":0',), verified=True),
    Site("Codecademy", "https://www.codecademy.com/profiles/{}",
         absent_markers=("not found",), verified=True),
    Site("Replit", "https://replit.com/@{}", status_not_found=(404,),
         absent_markers=("not found",), verified=True),
    Site("Pastebin", "https://pastebin.com/u/{}", status_not_found=(404,),
         absent_markers=("not found",), verified=True),
    Site("Dribbble", "https://dribbble.com/{}", status_not_found=(404,),
         absent_markers=("not found",), verified=True),
    Site("VK", "https://vk.com/{}", status_not_found=(404,),
         absent_markers=("page not found",), verified=True),
    Site("GitLab", "https://gitlab.com/api/v4/users?username={}",
         present_markers=('"username"',), verified=True),
    Site("Reddit", "https://www.reddit.com/user/{}/about.json",
         status_not_found=(404,), present_markers=('"name"',)),
    Site("X (Twitter)", "https://x.com/{}",
         absent_markers=("this account doesn't exist",)),
    Site("Instagram", "https://www.instagram.com/{}/",
         absent_markers=("sorry, this page isn't available", "page not found")),
    Site("Medium", "https://medium.com/@{}", absent_markers=("page not found",)),
    Site("Steam", "https://steamcommunity.com/id/{}",
         present_markers=('"steamid"', '"vanity"', '"accountid"')),
    Site("Behance", "https://www.behance.net/{}",
         absent_markers=("we can't find that page",)),
    Site("Pinterest", "https://www.pinterest.com/{}/",
         absent_markers=("user not found",)),
    Site("Roblox", "https://api.roblox.com/users.roblox.com/v1/users:username"
                   "?username={}", status_not_found=(400, 404)),
    Site("Twitch", "https://m.twitch.tv/{}/",
         absent_markers=("content is unavailable", "unless you've got a time machine")),
    Site("SoundCloud", "https://soundcloud.com/{}",
         absent_markers=("we can't find that user",)),
    Site("Vimeo", "https://vimeo.com/{}", absent_markers=("page not found",)),
    Site("TikTok", "https://www.tiktok.com/@{}",
         absent_markers=("couldn't find this account",)),
    Site("Facebook", "https://www.facebook.com/{}",
         absent_markers=("this content isn't available",)),
    Site("Telegram", "https://t.me/{}",
         absent_markers=("if you have telegram", "tgme_page_icon")),
    Site("Quora", "https://www.quora.com/profile/{}",
         absent_markers=("page not found",)),
    Site("npm", "https://www.npmjs.com/~{}",
         absent_markers=("user not found", "cannot find")),
    Site("CodePen", "https://codepen.io/{}", absent_markers=("page not found",)),
    Site("Gravatar", "https://en.gravatar.com/{}", absent_markers=("user not found",)),
    Site("DeviantArt", "https://{}.deviantart.com", absent_markers=("page not found",)),
    Site("Flickr", "https://www.flickr.com/people/{}",
         absent_markers=("page not found",)),
    Site("SlideShare", "https://www.slideshare.net/{}",
         absent_markers=("page not found",)),
    Site("ProductHunt", "https://www.producthunt.com/@{}",
         absent_markers=("page not found",)),
    Site("Wattpad", "https://www.wattpad.com/user/{}",
         absent_markers=("page not found",)),
    Site("LiveJournal", "https://{}.livejournal.com",
         absent_markers=("page not found", "no such journal")),
    Site("Imgur", "https://imgur.com/user/{}", absent_markers=("page not found",)),
    Site("About.me", "https://about.me/{}", absent_markers=("page not found",)),
    Site("Bandcamp", "https://bandcamp.com/{}", absent_markers=("page not found",)),
    Site("Patreon", "https://www.patreon.com/{}", absent_markers=("page not found",)),
)


@dataclass
class Hit:
    site: str
    url: str
    state: str
    detail: str = ""
    verified: bool = True


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    return s


def classify(site: Site, status: int, body: str) -> tuple:
    low = body.lower()
    if status in site.status_not_found:
        return "not_found", "HTTP %d" % status
    if status in (401, 403, 429, 503):
        return "blocked", "HTTP %d (需要登录/被限流)" % status
    if status != 200:
        return "error", "HTTP %d" % status
    for marker in site.absent_markers:
        if marker in low:
            return "not_found", "页面返回 200 但含「不存在」特征"
    if site.present_markers:
        for marker in site.present_markers:
            if marker in low:
                return "found", "命中存在特征"
        return "not_found", "页面返回 200 但无存在特征（疑似登录墙/软 404）"
    return "found", "HTTP 200"


def check_one(site: Site, username: str, session: requests.Session) -> Hit:
    url = site.url.format(username)
    try:
        resp = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        body = ""
        if resp.status_code == 200:
            body = resp.text[:60000].lower()
        state, detail = classify(site, resp.status_code, body)
        return Hit(site.name, url, state, detail, site.verified)
    except requests.exceptions.SSLError as exc:
        return Hit(site.name, url, "error", "TLS 失败: %s" % exc, site.verified)
    except requests.exceptions.Timeout:
        return Hit(site.name, url, "error", "超时", site.verified)
    except requests.exceptions.TooManyRedirects:
        return Hit(site.name, url, "error", "重定向过多", site.verified)
    except requests.exceptions.ConnectionError as exc:
        return Hit(site.name, url, "error", "连接失败: %s" % str(exc)[:60],
                   site.verified)
    except requests.exceptions.RequestException as exc:
        return Hit(site.name, url, "error", "请求异常: %s" % str(exc)[:60],
                   site.verified)


def scan_username(username: str, sites: Optional[tuple] = None,
                  workers: int = MAX_WORKERS, progress: bool = True) -> list:
    targets = sites if sites is not None else SITES
    results: list = []
    session = _session()
    done = 0
    total = len(targets)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(check_one, s, username, session) for s in targets]
        for fut in futures:
            hit = fut.result()
            done += 1
            results.append(hit)
            if progress and sys.stderr.isatty():
                sys.stderr.write("\r%s扫描中 %d/%d" % (C.c, done, total))
                sys.stderr.flush()
    if progress and sys.stderr.isatty():
        sys.stderr.write("\r" + " " * 40 + "\r")
        sys.stderr.flush()
    order = {"found": 0, "blocked": 1, "error": 2, "not_found": 3}
    results.sort(key=lambda h: (order.get(h.state, 9), h.site))
    return results


def print_results(results: list, username: str) -> None:
    found = [r for r in results if r.state == "found"]
    blocked = [r for r in results if r.state == "blocked"]
    errored = [r for r in results if r.state == "error"]
    missing = [r for r in results if r.state == "not_found"]

    print()
    print("%s============ 用户名 %s 扫描结果 ============" % (C.w, C.g))
    print()
    for group, mark, color, title in (
        (found, "+", C.g, "已注册"),
        (blocked, "?", C.y, "被拦截（结果不可信）"),
        (errored, "x", C.r, "请求失败"),
        (missing, "-", C.d, "未注册"),
    ):
        if not group:
            continue
        print("%s[%s %s] %s%s (%d)%s"
              % (C.w, mark, C.x, color, title, len(group), C.x))
        for hit in group:
            note = ""
            if hit.state in ("error", "blocked"):
                note = "  %s(%s)%s" % (C.d, hit.detail, C.x)
            elif not hit.verified:
                note = "  %s(判据未在当前网络实测验证)%s" % (C.d, C.x)
            print("%s[%s %s] %s : %s%s%s"
                  % (C.w, mark, C.x, hit.site, color, hit.url, note))
        print()
    print("%s合计 %d 个目标：已注册 %d / 被拦截 %d / 失败 %d / 未注册 %d%s"
          % (C.w, len(results), len(found), len(blocked), len(errored), len(missing), C.x))
    if found:
        unverified_found = [h for h in found if not h.verified]
        if unverified_found:
            print()
            print("%s注意: 「已注册」中 %s%d 个%s 站点的判据未实测验证，"
                  "可能存在误报（软 404）。"
                  % (C.y, C.x, len(unverified_found), C.y))


def export(results: list, username: str, path: str) -> str:
    payload = [
        {"site": h.site, "url": h.url, "state": h.state, "detail": h.detail}
        for h in results
    ]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"username": username, "results": payload}, fh,
                  ensure_ascii=False, indent=2)
    return path


def ip_info(ip: str, session: Optional[requests.Session] = None) -> dict:
    sess = session or _session()
    try:
        resp = sess.get(IPWHO_ENDPOINT.format(ip), timeout=TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise RuntimeError("请求失败: %s" % exc) from exc
    if resp.status_code != 200:
        raise RuntimeError("API 返回 HTTP %d" % resp.status_code)
    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("API 返回的不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("API 返回结构异常")
    if data.get("success") is False:
        raise RuntimeError("查询失败: %s" % (data.get("message") or "未知原因"))
    return data


def show_ip(ip: str, data: dict) -> None:
    def g(path, default="N/A"):
        cur = data
        for key in path.split("."):
            if not isinstance(cur, dict):
                return default
            cur = cur.get(key)
        return default if cur in (None, "") else cur

    conn = data.get("connection") or {}
    tz = data.get("timezone") or {}
    flag = (data.get("flag") or {}).get("emoji", "N/A")

    lat = g("latitude")
    lon = g("longitude")
    maps = "N/A"
    try:
        maps = "https://www.google.com/maps/@%.4f,%.4f,8z" % (float(lat), float(lon))
    except (TypeError, ValueError):
        pass

    rows = [
        ("IP 目标", ip),
        ("IP 类型", g("type")),
        ("是否 IPv6", "是" if g("type") == "IPv6" else "否"),
        ("国家", g("country")),
        ("国家代码", g("country_code")),
        ("旗帜", flag),
        ("城市", g("city")),
        ("地区", g("region")),
        ("地区代码", g("region_code")),
        ("洲", g("continent")),
        ("经纬度", "%s, %s" % (lat, lon)),
        ("地图", maps),
        ("邮编", g("postal")),
        ("国际区号", g("calling_code")),
        ("首都", g("capital")),
        ("邻国", g("borders")),
        ("是否欧盟", g("is_eu")),
        ("ASN", conn.get("asn", "N/A")),
        ("运营商", conn.get("isp", "N/A")),
        ("组织", conn.get("org", "N/A")),
        ("域名", conn.get("domain", "N/A")),
        ("时区", tz.get("id", "N/A")),
        ("时区缩写", tz.get("abbr", "N/A")),
        ("夏令时", tz.get("is_dst", "N/A")),
        ("UTC 偏移", tz.get("offset", "N/A")),
        ("UTC", tz.get("utc", "N/A")),
    ]
    print()
    print("%s============ IP 信息 ============" % (C.w))
    print()
    for label, value in rows:
        print("%s%-16s:%s %s" % (C.w, label, C.x, value))


def looks_like_ip(text: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def own_ip(session: Optional[requests.Session] = None) -> dict:
    sess = session or _session()
    failures = []
    for endpoint in IP_ECHO_ENDPOINTS:
        try:
            resp = sess.get(endpoint, timeout=TIMEOUT)
        except requests.exceptions.RequestException as exc:
            failures.append("%s (%s)" % (endpoint, type(exc).__name__))
            continue
        if resp.status_code != 200:
            failures.append("%s (HTTP %d)" % (endpoint, resp.status_code))
            continue
        candidate = resp.text.strip()
        if not candidate:
            failures.append("%s (返回为空)" % endpoint)
            continue
        if looks_like_ip(candidate):
            version = 6 if ":" in candidate else 4
            return {"ip": candidate, "version": version, "source": endpoint}
        failures.append("%s (返回非 IP)" % endpoint)
    raise RuntimeError("全部查询端点均失败:\n  " + "\n  ".join(failures))


def phone_info(number: str, region: Optional[str]) -> dict:
    if phonenumbers is None:
        raise RuntimeError("缺少依赖 phonenumbers，请执行: pip install phonenumbers")
    raw = number.strip()
    try:
        parsed = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException as exc:
        raise RuntimeError("号码格式无法解析（%s）；不带 + 时可用 --region 指定国家，如 --region CN" % exc) from exc
    if not phonenumbers.is_possible_number(parsed):
        raise RuntimeError("该号码不可能是有效号码，请检查是否缺少国家码")

    ntype = phonenumbers.number_type(parsed)
    type_name = {
        phonenumbers.PhoneNumberType.MOBILE: "手机号",
        phonenumbers.PhoneNumberType.FIXED_LINE: "固定电话",
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "固话或手机",
        phonenumbers.PhoneNumberType.TOLL_FREE: "免费电话",
        phonenumbers.PhoneNumberType.PREMIUM_RATE: "付费电话",
        phonenumbers.PhoneNumberType.VOIP: "网络电话 (VoIP)",
        phonenumbers.PhoneNumberType.UNKNOWN: "未知",
    }.get(ntype, str(ntype))

    zones = pn_timezone.time_zones_for_number(parsed) or ()
    return {
        "e164": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
        "international": phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
        "national": str(parsed.national_number),
        "country_code": parsed.country_code,
        "region_code": phonenumbers.region_code_for_number(parsed) or "未知",
        "carrier": carrier.name_for_number(parsed, "zh") or "未知",
        "location": geocoder.description_for_number(parsed, "zh") or "未知",
        "timezones": list(zones),
        "valid": phonenumbers.is_valid_number(parsed),
        "possible": phonenumbers.is_possible_number(parsed),
        "type": type_name,
    }


def show_phone(info: dict) -> None:
    rows = [
        ("国际格式", info["international"]),
        ("E.164 格式", info["e164"]),
        ("国家码", info["country_code"]),
        ("地区代码", info["region_code"]),
        ("号码归属地", info["location"]),
        ("运营商", info["carrier"]),
        ("号码类型", info["type"]),
        ("是否有效", "是" if info["valid"] else "否"),
        ("是否可能有效", "是" if info["possible"] else "否"),
        ("时区", ", ".join(info["timezones"]) or "未知"),
    ]
    print()
    print("%s============ 号码信息 ============" % (C.w))
    print()
    for label, value in rows:
        print("%s%-14s:%s %s" % (C.w, label, C.x, value))
    print()
    print("%s说明：以上来自本地号码段数据库，仅代表号段注册地与运营商，%s" % (C.d, C.x))
    print("%s不代表持有者的实时位置。%s" % (C.d, C.x))


def valid_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text.strip())
        return True
    except ValueError:
        return False


def cmd_ip(args: argparse.Namespace) -> int:
    ip = args.target.strip()
    if not valid_ip(ip):
        print("%s不是合法 IP 地址: %s%s" % (C.r, ip, C.x))
        return 1
    try:
        show_ip(ip, ip_info(ip))
    except RuntimeError as exc:
        print("%s查询失败: %s%s" % (C.r, exc, C.x))
        return 1
    return 0


def cmd_self_ip(args: argparse.Namespace) -> int:
    try:
        info = own_ip()
    except RuntimeError as exc:
        print("%s%s%s" % (C.r, exc, C.x))
        return 1
    kind = "IPv6" if info["version"] == 6 else "IPv4"
    print()
    print("%s============ 本机公网 IP ============" % C.w)
    print()
    print("%s地址   : %s%s" % (C.w, C.g, info["ip"]))
    print("%s版本   : %s%s" % (C.w, C.x, kind))
    print("%s来源   : %s%s" % (C.d, info["source"], C.x))
    if info["version"] == 6:
        print()
        print("%s提示: 运营商网络下这是 IPv6 出口地址，%s" % (C.d, C.x))
        print("%s网站看到的通常也是这个地址。%s" % (C.d, C.x))
    return 0


def cmd_phone(args: argparse.Namespace) -> int:
    try:
        show_phone(phone_info(args.target, args.region))
    except RuntimeError as exc:
        print("%s%s%s" % (C.r, exc, C.x))
        return 1
    return 0


def cmd_user(args: argparse.Namespace) -> int:
    username = args.target.strip()
    sites = None
    if args.only:
        wanted = {s.strip().lower() for s in args.only.split(",") if s.strip()}
        sites = tuple(s for s in SITES if s.name.lower() in wanted)
        if not sites:
            print("%s没有匹配的目标，可用名称: %s%s"
                  % (C.r, ", ".join(s.name for s in SITES), C.x))
            return 1
    results = scan_username(username, sites=sites,
                            progress=not args.no_progress)
    print_results(results, username)
    if args.out:
        path = export(results, username, args.out)
        print("%s已导出: %s%s" % (C.g, os.path.abspath(path), C.x))
    return 0


def list_sites() -> None:
    print("%s============ 可用目标 (%d) ============" % (C.w, len(SITES)))
    print()
    for site in SITES:
        print("%s%-16s%s %s" % (C.c, site.name, C.x, site.url.format("<username>")))


MENU = (
    ("1", "IP 追踪", cmd_ip),
    ("2", "本机公网 IP", cmd_self_ip),
    ("3", "号码信息查询", cmd_phone),
    ("4", "用户名注册地扫描", cmd_user),
    ("5", "列出全部目标站点", lambda a: (list_sites(), 0)[1]),
    ("0", "退出", None),
)


def interactive() -> int:
    while True:
        if C.on:
            sys.stderr.write("\033[2J\033[H")
        sys.stderr.write(BANNER)
        sys.stderr.write("  ghosttrack-fixed  |  IP / 号码 / 用户名 侦察工具\n\n")
        for key, title, _ in MENU:
            sys.stderr.write("  %s[%s]%s %s\n" % (C.c, key, C.x, title))
        sys.stderr.write("\n")
        try:
            choice = input("%s选择:%s " % (C.g, C.x)).strip()
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\n%s退出%s\n" % (C.d, C.x))
            return 0
        if choice == "0":
            return 0
        picked = next((m for m in MENU if m[0] == choice), None)
        if picked is None:
            sys.stderr.write("%s无效选项，请输入菜单里的数字%s\n" % (C.r, C.x))
            time.sleep(0.6)
            continue
        _, _, handler = picked
        try:
            args = prompt_args(choice)
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\n%s已取消%s\n" % (C.d, C.x))
            time.sleep(0.6)
            continue
        if args is None or isinstance(args, _Done):
            time.sleep(0.6)
            continue
        try:
            handler(args)
        except Exception as exc:
            sys.stderr.write("%s执行出错: %s%s\n" % (C.r, exc, C.x))
        try:
            input("\n%s按回车返回菜单...%s" % (C.d, C.x))
        except (EOFError, KeyboardInterrupt):
            return 0


class _Done:
    pass


_DONE = _Done()


def prompt_args(choice: str):
    ns = argparse.Namespace()
    if choice == "1":
        ns.target = input("输入目标 IP: ").strip()
        if not valid_ip(ns.target):
            print("%s不是合法 IP 地址%s" % (C.r, C.x))
            return None
    elif choice == "2":
        cmd_self_ip(ns)
        return _DONE
    elif choice == "3":
        ns.target = input("输入号码（如 +8613800138000）: ").strip()
        region = input("国家码（大写，可留空，如 CN/ID）: ").strip().upper() or None
        ns.region = region
    elif choice == "4":
        ns.target = input("输入目标用户名: ").strip()
        if not ns.target:
            print("%s用户名不能为空%s" % (C.r, C.x))
            return None
        only = input("只扫指定站点（逗号分隔，可留空）: ").strip()
        ns.only = only or None
        ns.out = None
        if input("是否导出 JSON 到文件? y/N: ").strip().lower() in ("y", "yes"):
            ns.out = input("导出路径: ").strip() or "ghosttrack-results.json"
        ns.no_progress = False
    else:
        list_sites()
        return _DONE
    return ns


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--timeout", type=float, default=8.0,
                        help="单次请求读超时秒数，默认 8")

    p = argparse.ArgumentParser(
        prog="ghosttrack",
        description="IP / 手机号段 / 用户名注册地 侦察工具（OSINT，合法用途）")
    p.add_argument("--timeout", type=float, default=8.0,
                   help="单次请求读超时秒数，默认 8")
    sub = p.add_subparsers(dest="command")

    a = sub.add_parser("ip", help="查询指定 IP 的归属信息", parents=[common])
    a.add_argument("target", help="目标 IP，例如 8.8.8.8")
    a.set_defaults(func=cmd_ip)

    a = sub.add_parser("selfip", help="显示本机公网 IP", parents=[common])
    a.set_defaults(func=cmd_self_ip)

    a = sub.add_parser("phone", help="查询号码段归属地与运营商", parents=[common])
    a.add_argument("target", help="号码，强烈建议带国际区号，如 +8613800138000")
    a.add_argument("--region", help="号码不带 + 时的默认国家码，如 CN")
    a.set_defaults(func=cmd_phone)

    a = sub.add_parser("user", help="扫描用户名在各平台的注册情况", parents=[common])
    a.add_argument("target", help="目标用户名")
    a.add_argument("--only", help="只扫指定站点，逗号分隔，如 GitHub,Reddit")
    a.add_argument("--out", help="把结果导出为 JSON 文件")
    a.add_argument("--no-progress", action="store_true", help="不显示进度条")
    a.set_defaults(func=cmd_user)

    a = sub.add_parser("sites", help="列出全部目标站点")
    a.set_defaults(func=lambda args: (list_sites(), 0)[1])

    return p


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("ip", "selfip", "phone", "user", "sites"):
        parser = build_parser()
        args = parser.parse_args(argv)
        if args.timeout and args.timeout > 0:
            set_timeout(args.timeout)
        try:
            return args.func(args) or 0
        except KeyboardInterrupt:
            print("\n%s已中断%s" % (C.d, C.x))
            return 130
    if argv and argv[0] in ("-h", "--help"):
        build_parser().print_help()
        return 0
    for i, token in enumerate(argv):
        if token == "--timeout" and i + 1 < len(argv):
            try:
                set_timeout(float(argv[i + 1]))
            except ValueError:
                pass
    return interactive()


if __name__ == "__main__":
    sys.exit(main())
