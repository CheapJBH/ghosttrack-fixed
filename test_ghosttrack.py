import json
import os
import tempfile
import unittest
from unittest import mock

import requests

import GhostTR as g


def fake_response(status=200, body="", url="https://example.com/"):
    resp = mock.Mock()
    resp.status_code = status
    resp.text = body
    resp.url = url
    return resp


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.handler(url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def update(self, *a, **kw):
        pass


class TimeoutSetting(unittest.TestCase):
    def test_default_timeout_has_connect_and_read(self):
        g.set_timeout(8.0)
        connect, read = g.TIMEOUT
        self.assertEqual(read, 8.0)
        self.assertLessEqual(connect, 3.05)
        self.assertGreater(connect, 0)

    def test_small_timeout_clamps_connect(self):
        g.set_timeout(2.0)
        self.assertEqual(g.TIMEOUT, (2.0, 2.0))

    def test_timeout_actually_reaches_session(self):
        g.set_timeout(4.5)
        seen = {}

        class S(FakeSession):
            def get(self, url, **kwargs):
                seen.update(kwargs)
                return fake_response(200, "")

        site = g.Site("T", "https://t.example/{}")
        g.check_one(site, "bob", S(lambda u: fake_response()))
        self.assertEqual(seen["timeout"], (3.05, 4.5))


class IpValidation(unittest.TestCase):
    def test_valid_ipv4(self):
        self.assertTrue(g.valid_ip("8.8.8.8"))

    def test_invalid_ipv4(self):
        self.assertFalse(g.valid_ip("999.1.1.1"))

    def test_invalid_text(self):
        self.assertFalse(g.valid_ip("not-an-ip"))

    def test_empty(self):
        self.assertFalse(g.valid_ip("  "))

    def test_ipv6(self):
        self.assertTrue(g.valid_ip("2001:4860:4860::8888"))

    def test_trims_whitespace(self):
        self.assertTrue(g.valid_ip("  1.1.1.1  "))


class Classify(unittest.TestCase):
    def test_404_is_not_found(self):
        site = g.Site("X", "u{}")
        state, _ = g.classify(site, 404, "")
        self.assertEqual(state, "not_found")

    def test_410_is_not_found(self):
        site = g.Site("X", "u{}")
        state, _ = g.classify(site, 410, "")
        self.assertEqual(state, "not_found")

    def test_200_is_found(self):
        site = g.Site("X", "u{}")
        state, _ = g.classify(site, 200, "hello")
        self.assertEqual(state, "found")

    def test_403_is_blocked(self):
        site = g.Site("X", "u{}")
        state, _ = g.classify(site, 403, "")
        self.assertEqual(state, "blocked")

    def test_429_is_blocked(self):
        site = g.Site("X", "u{}")
        state, _ = g.classify(site, 429, "")
        self.assertEqual(state, "blocked")

    def test_500_is_error(self):
        site = g.Site("X", "u{}")
        state, _ = g.classify(site, 500, "")
        self.assertEqual(state, "error")

    def test_absent_marker_on_200_is_not_found(self):
        site = g.Site("X", "u{}", absent_markers=("page not found",))
        state, _ = g.classify(site, 200, "Sorry, Page Not Found here")
        self.assertEqual(state, "not_found")

    def test_absent_marker_case_insensitive(self):
        site = g.Site("X", "u{}", absent_markers=("page not found",))
        state, _ = g.classify(site, 200, "PAGE NOT FOUND")
        self.assertEqual(state, "not_found")

    def test_present_marker_present_is_found(self):
        site = g.Site("X", "u{}", present_markers=('"username"',))
        state, _ = g.classify(site, 200, '{"username":"bob"}')
        self.assertEqual(state, "found")

    def test_present_marker_missing_soft404_detected(self):
        site = g.Site("X", "u{}", present_markers=('"username"',))
        state, _ = g.classify(site, 200, "<html>please log in</html>")
        self.assertEqual(state, "not_found")

    def test_status_takes_priority_over_markers(self):
        site = g.Site("X", "u{}", present_markers=('"username"',))
        state, _ = g.classify(site, 404, '{"username":"bob"}')
        self.assertEqual(state, "not_found")


class CheckOne(unittest.TestCase):
    def test_timeout_returns_error_not_crash(self):
        class S(FakeSession):
            def get(self, url, **kw):
                raise requests.exceptions.ConnectTimeout("slow")

        hit = g.check_one(g.Site("T", "u{}"), "bob", S(None))
        self.assertEqual(hit.state, "error")
        self.assertIn("超时", hit.detail)

    def test_ssl_error_is_reported(self):
        class S(FakeSession):
            def get(self, url, **kw):
                raise requests.exceptions.SSLError("bad cert")

        hit = g.check_one(g.Site("T", "u{}"), "bob", S(None))
        self.assertEqual(hit.state, "error")
        self.assertIn("TLS", hit.detail)

    def test_connection_error_is_reported(self):
        class S(FakeSession):
            def get(self, url, **kw):
                raise requests.exceptions.ConnectionError("refused")

        hit = g.check_one(g.Site("T", "u{}"), "bob", S(None))
        self.assertEqual(hit.state, "error")

    def test_too_many_redirects(self):
        class S(FakeSession):
            def get(self, url, **kw):
                raise requests.exceptions.TooManyRedirects("loop")

        hit = g.check_one(g.Site("T", "u{}"), "bob", S(None))
        self.assertEqual(hit.state, "error")

    def test_generic_request_exception(self):
        class S(FakeSession):
            def get(self, url, **kw):
                raise requests.exceptions.RequestException("weird")

        hit = g.check_one(g.Site("T", "u{}"), "bob", S(None))
        self.assertEqual(hit.state, "error")

    def test_url_is_formatted_with_username(self):
        sess = FakeSession(lambda u: fake_response(200, "ok"))
        hit = g.check_one(g.Site("T", "https://t.example/{}"), "bob", sess)
        self.assertEqual(hit.url, "https://t.example/bob")


class Scan(unittest.TestCase):
    def test_scan_returns_all_hits(self):
        sites = (
            g.Site("A", "https://a/{}"),
            g.Site("B", "https://b/{}"),
            g.Site("C", "https://c/{}"),
        )
        sess = FakeSession(lambda u: fake_response(200, "hi"))
        with mock.patch.object(g, "_session", return_value=sess):
            res = g.scan_username("bob", sites=sites, progress=False)
        self.assertEqual(len(res), 3)

    def test_scan_mixed_states_sorted(self):
        sites = (
            g.Site("Z_found", "https://z/{}"),
            g.Site("A_missing", "https://a/{}"),
            g.Site("M_blocked", "https://m/{}"),
        )

        def handler(url):
            if url.startswith("https://z"):
                return fake_response(200, "ok")
            if url.startswith("https://m"):
                return fake_response(403, "")
            return fake_response(404, "")

        sess = FakeSession(handler)
        with mock.patch.object(g, "_session", return_value=sess):
            res = g.scan_username("bob", sites=sites, progress=False)
        self.assertEqual([r.site for r in res],
                         ["Z_found", "M_blocked", "A_missing"])

    def test_scan_survives_per_site_exceptions(self):
        sites = (g.Site("boom", "https://boom/{}"), g.Site("ok", "https://ok/{}"))

        def handler(url):
            if "boom" in url:
                raise requests.exceptions.ConnectionError("down")
            return fake_response(200, "ok")

        sess = FakeSession(handler)
        with mock.patch.object(g, "_session", return_value=sess):
            res = g.scan_username("bob", sites=sites, progress=False)
        states = {r.site: r.state for r in res}
        self.assertEqual(states["boom"], "error")
        self.assertEqual(states["ok"], "found")

    def test_every_builtin_site_is_probed(self):
        sess = FakeSession(lambda u: fake_response(404, ""))
        with mock.patch.object(g, "_session", return_value=sess):
            res = g.scan_username("bob", progress=False)
        self.assertEqual(len(res), len(g.SITES))


class SiteTable(unittest.TestCase):
    def test_no_duplicate_names(self):
        names = [s.name for s in g.SITES]
        dupes = {n for n in names if names.count(n) > 1}
        self.assertEqual(dupes, set(), "重复站点名: %s" % dupes)

    def test_every_url_has_placeholder(self):
        for s in g.SITES:
            self.assertIn("{}", s.url, "%s 的 URL 缺少 {} 占位符" % s.name)

    def test_every_url_is_https(self):
        for s in g.SITES:
            self.assertTrue(s.url.startswith("https://"),
                            "%s 未使用 HTTPS: %s" % (s.name, s.url))

    def test_no_empty_markers(self):
        for s in g.SITES:
            for m in s.absent_markers:
                self.assertTrue(m.strip(), "%s 含空特征串" % s.name)
            for m in s.present_markers:
                self.assertTrue(m.strip(), "%s 含空特征串" % s.name)

    def test_no_braces_inside_markers(self):
        for s in g.SITES:
            for m in list(s.absent_markers) + list(s.present_markers):
                self.assertNotIn("{", m, "%s 特征串含花括号" % s.name)

    def test_verified_sites_have_a_reliable_signal(self):
        for s in g.SITES:
            if not s.verified:
                continue
            has_signal = bool(s.present_markers or s.absent_markers)
            self.assertTrue(has_signal,
                            "%s 标为已验证却没有任何判据特征" % s.name)

    def test_no_known_unreliable_sites(self):
        banned = {"PyPI", "Trello", "Kaggle", "Spotify", "Coder"}
        names = {s.name for s in g.SITES}
        self.assertEqual(names & banned, set(),
                         "存在无法可靠判定的站点: %s" % (names & banned))

    def test_bitbucket_uses_web_not_api(self):
        bt = next(s for s in g.SITES if s.name == "Bitbucket")
        self.assertIn("bitbucket.org/{}/", bt.url)
        self.assertTrue(bt.verified)

    def test_unverified_sites_still_have_a_signal(self):
        for s in g.SITES:
            if not s.verified:
                self.assertTrue(
                    s.absent_markers or s.present_markers
                    or s.status_not_found != (404, 410),
                    "%s 未验证却也无任何判据特征" % s.name)

    def test_site_count_is_sane(self):
        self.assertGreaterEqual(len(g.SITES), 30)
        self.assertLessEqual(len(g.SITES), 60)


class VerifiedConfidence(unittest.TestCase):
    def test_hit_carries_verified_flag(self):
        sess = FakeSession(lambda u: fake_response(200, '{"login":"bob"}'))
        site = g.Site("T", "https://t/{}", present_markers=('"login"',),
                      verified=True)
        self.assertTrue(g.check_one(site, "bob", sess).verified)

    def test_unverified_site_flag_propagates(self):
        sess = FakeSession(lambda u: fake_response(200, "ok"))
        site = g.Site("T", "https://t/{}", verified=False)
        self.assertFalse(g.check_one(site, "bob", sess).verified)

    def test_print_results_flags_unverified_hits(self):
        hits = [g.Hit("Zeta", "https://z/bob", "found", "", False)]
        g.print_results(hits, "bob")

    def test_print_results_with_all_states(self):
        hits = [
            g.Hit("A", "https://a/bob", "found", "", True),
            g.Hit("B", "https://b/bob", "blocked", "HTTP 403", False),
            g.Hit("C", "https://c/bob", "error", "超时", False),
            g.Hit("D", "https://d/bob", "not_found", "", True),
        ]
        g.print_results(hits, "bob")

    def test_print_results_empty_list(self):
        g.print_results([], "bob")

    def test_print_results_only_unverified_found(self):
        g.print_results([g.Hit("Z", "https://z/bob", "found", "", False)], "bob")

    def test_print_results_no_warning_when_all_verified(self):
        g.print_results([g.Hit("Z", "https://z/bob", "found", "", True)], "bob")


class PhoneInfo(unittest.TestCase):
    def test_raises_when_library_missing(self):
        with mock.patch.object(g, "phonenumbers", None):
            with self.assertRaises(RuntimeError):
                g.phone_info("+8613800138000", None)

    def test_e164_cn_number(self):
        info = g.phone_info("+8613800138000", None)
        self.assertEqual(info["country_code"], 86)
        self.assertEqual(info["e164"], "+8613800138000")
        self.assertTrue(info["possible"])

    def test_us_number(self):
        info = g.phone_info("+14155552671", None)
        self.assertEqual(info["country_code"], 1)

    def test_invalid_number_raises(self):
        with self.assertRaises(RuntimeError):
            g.phone_info("+1234", None)

    def test_garbage_raises(self):
        with self.assertRaises(RuntimeError):
            g.phone_info("not-a-number", "CN")

    def test_region_fallback_used(self):
        info = g.phone_info("13800138000", "CN")
        self.assertEqual(info["country_code"], 86)

    def test_carrier_and_location_present(self):
        info = g.phone_info("+8613800138000", None)
        self.assertTrue(info["carrier"])
        self.assertTrue(info["location"])


class IpInfo(unittest.TestCase):
    def test_non_200_raises(self):
        sess = FakeSession(lambda u: fake_response(500, ""))
        with self.assertRaises(RuntimeError):
            g.ip_info("8.8.8.8", sess)

    def test_invalid_json_raises(self):
        resp = fake_response(200, "not json")
        resp.json.side_effect = ValueError("bad")
        sess = FakeSession(lambda u: resp)
        with self.assertRaises(RuntimeError):
            g.ip_info("8.8.8.8", sess)

    def test_success_false_raises(self):
        resp = fake_response(200, "{}")
        resp.json.return_value = {"success": False, "message": "quota"}
        sess = FakeSession(lambda u: resp)
        with self.assertRaises(RuntimeError):
            g.ip_info("8.8.8.8", sess)

    def test_missing_fields_do_not_crash_display(self):
        resp = fake_response(200, "{}")
        resp.json.return_value = {"success": True}
        sess = FakeSession(lambda u: resp)
        data = g.ip_info("8.8.8.8", sess)
        g.show_ip("8.8.8.8", data)

    def test_https_endpoint_used(self):
        seen = []

        class S(FakeSession):
            def get(self, url, **kw):
                seen.append(url)
                resp = fake_response(200, "{}")
                resp.json.return_value = {"success": True}
                return resp

        g.ip_info("8.8.8.8", S(None))
        self.assertTrue(seen[0].startswith("https://"), "IP 查询未走 HTTPS")
        self.assertNotIn("http://", seen[0])


class OwnIp(unittest.TestCase):
    def test_returns_stripped_ipv4(self):
        class S(FakeSession):
            def get(self, url, **kw):
                return fake_response(200, " 1.2.3.4\n")

        info = g.own_ip(S(None))
        self.assertEqual(info["ip"], "1.2.3.4")
        self.assertEqual(info["version"], 4)

    def test_detects_ipv6(self):
        class S(FakeSession):
            def get(self, url, **kw):
                return fake_response(200, "2409:8a3c::1\n")

        info = g.own_ip(S(None))
        self.assertEqual(info["version"], 6)
        self.assertEqual(info["ip"], "2409:8a3c::1")

    def test_falls_back_to_next_endpoint(self):
        tried = []

        class S(FakeSession):
            def get(self, url, **kw):
                tried.append(url)
                if len(tried) == 1:
                    raise requests.exceptions.ConnectionError("down")
                return fake_response(200, "1.2.3.4")

        info = g.own_ip(S(None))
        self.assertEqual(info["ip"], "1.2.3.4")
        self.assertEqual(info["source"], g.IP_ECHO_ENDPOINTS[1])

    def test_skips_non_ip_response(self):
        tried = []

        class S(FakeSession):
            def get(self, url, **kw):
                tried.append(url)
                if len(tried) == 1:
                    return fake_response(200, "<html>ads</html>")
                return fake_response(200, "1.2.3.4")

        info = g.own_ip(S(None))
        self.assertEqual(info["ip"], "1.2.3.4")

    def test_skips_empty_response(self):
        tried = []

        class S(FakeSession):
            def get(self, url, **kw):
                tried.append(url)
                if len(tried) == 1:
                    return fake_response(200, "   ")
                return fake_response(200, "1.2.3.4")

        self.assertEqual(g.own_ip(S(None))["ip"], "1.2.3.4")

    def test_skips_non_200(self):
        tried = []

        class S(FakeSession):
            def get(self, url, **kw):
                tried.append(url)
                if len(tried) == 1:
                    return fake_response(500, "1.2.3.4")
                return fake_response(200, "1.2.3.4")

        self.assertEqual(g.own_ip(S(None))["ip"], "1.2.3.4")

    def test_all_endpoints_fail_raises_with_detail(self):
        class S(FakeSession):
            def get(self, url, **kw):
                raise requests.exceptions.ConnectionError("down")

        with self.assertRaises(RuntimeError) as ctx:
            g.own_ip(S(None))
        self.assertIn("全部查询端点均失败", str(ctx.exception))

    def test_all_endpoints_fail_lists_every_endpoint(self):
        seen = []

        class S(FakeSession):
            def get(self, url, **kw):
                seen.append(url)
                return fake_response(200, "not an ip")

        with self.assertRaises(RuntimeError) as ctx:
            g.own_ip(S(None))
        self.assertEqual(len(seen), len(g.IP_ECHO_ENDPOINTS))
        self.assertIn("返回非 IP", str(ctx.exception))

    def test_every_endpoint_is_https(self):
        for url in g.IP_ECHO_ENDPOINTS:
            self.assertTrue(url.startswith("https://"), url)

    def test_looks_like_ip(self):
        self.assertTrue(g.looks_like_ip("1.2.3.4"))
        self.assertTrue(g.looks_like_ip("::1"))
        self.assertFalse(g.looks_like_ip("hello"))
        self.assertFalse(g.looks_like_ip("999.1.1.1"))
        self.assertFalse(g.looks_like_ip(""))

    def test_uses_https(self):
        seen = []

        class S(FakeSession):
            def get(self, url, **kw):
                seen.append(url)
                return fake_response(200, "1.2.3.4")

        g.own_ip(S(None))
        self.assertTrue(seen[0].startswith("https://"))


class Export(unittest.TestCase):
    def test_writes_valid_json(self):
        hits = [g.Hit("GitHub", "https://gh/x", "found", "")]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.json")
            g.export(hits, "bob", path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        self.assertEqual(data["username"], "bob")
        self.assertEqual(data["results"][0]["site"], "GitHub")

    def test_utf8_preserved(self):
        hits = [g.Hit("VK", "https://vk/中文", "found", "备注说明")]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.json")
            g.export(hits, "bob", path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        self.assertIn("中文", data["results"][0]["url"])


class NoDangerousCode(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(os.path.dirname(__file__), "GhostTR.py"),
                  encoding="utf-8") as fh:
            self.src = fh.read()

    def test_no_eval_or_exec(self):
        for bad in ("eval(", "exec(", "__import__", "pickle", "marshal",
                    "compile("):
            self.assertNotIn(bad, self.src, "发现危险调用: %s" % bad)

    def test_no_shell_execution(self):
        for bad in ("os.system", "subprocess", "os.popen", "os.execv"):
            self.assertNotIn(bad, self.src, "发现命令执行: %s" % bad)

    def test_no_base64_decode(self):
        self.assertNotIn("b64decode", self.src)

    def test_no_writes_outside_explicit_export(self):
        for bad in ("shutil.rmtree", "os.remove", "os.unlink", "os.rmdir"):
            self.assertNotIn(bad, self.src, "发现删除调用: %s" % bad)


class CommandLine(unittest.TestCase):
    def test_ip_cmd_rejects_bad_input(self):
        ns = argparse_namespace(target="999.999.999.999")
        self.assertEqual(g.cmd_ip(ns), 1)

    def test_ip_cmd_reports_query_failure(self):
        class S(FakeSession):
            def get(self, url, **kw):
                return fake_response(500, "")

        with mock.patch.object(g, "_session", return_value=S(None)):
            self.assertEqual(g.cmd_ip(argparse_namespace(target="8.8.8.8")), 1)

    def test_ip_cmd_success(self):
        resp = fake_response(200, "{}")
        resp.json.return_value = {"success": True, "ip": "8.8.8.8",
                                  "country": "美国"}

        class S(FakeSession):
            def get(self, url, **kw):
                return resp

        with mock.patch.object(g, "_session", return_value=S(None)):
            self.assertEqual(g.cmd_ip(argparse_namespace(target="8.8.8.8")), 0)

    def test_phone_cmd_failure_returns_one(self):
        ns = argparse_namespace(target="+1234", region=None)
        self.assertEqual(g.cmd_phone(ns), 1)

    def test_user_cmd_unknown_site_returns_one(self):
        ns = argparse_namespace(target="bob", only="NoSuchSite",
                                out=None, no_progress=True)
        self.assertEqual(g.cmd_user(ns), 1)

    def test_user_cmd_exports_file(self):
        sess = FakeSession(lambda u: fake_response(404, ""))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.json")
            ns = argparse_namespace(target="bob", only="GitHub",
                                    out=path, no_progress=True)
            with mock.patch.object(g, "_session", return_value=sess):
                rc = g.cmd_user(ns)
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(path))

    def test_self_ip_cmd_success_ipv4(self):
        class S(FakeSession):
            def get(self, url, **kw):
                return fake_response(200, "9.9.9.9")

        with mock.patch.object(g, "_session", return_value=S(None)):
            self.assertEqual(g.cmd_self_ip(argparse_namespace()), 0)

    def test_self_ip_cmd_success_ipv6_prints_hint(self):
        class S(FakeSession):
            def get(self, url, **kw):
                return fake_response(200, "2409:8a3c::1")

        with mock.patch.object(g, "_session", return_value=S(None)):
            self.assertEqual(g.cmd_self_ip(argparse_namespace()), 0)

    def test_self_ip_cmd_all_fail_returns_one(self):
        class S(FakeSession):
            def get(self, url, **kw):
                raise requests.exceptions.ConnectionError("down")

        with mock.patch.object(g, "_session", return_value=S(None)):
            self.assertEqual(g.cmd_self_ip(argparse_namespace()), 1)


class Dispatch(unittest.TestCase):
    def test_help_exits_zero(self):
        self.assertEqual(g.main(["--help"]), 0)

    def test_unknown_subcommand_falls_to_menu(self):
        with mock.patch.object(g, "interactive", return_value=0):
            self.assertEqual(g.main(["bogus"]), 0)


def argparse_namespace(**kw):
    import argparse
    return argparse.Namespace(**kw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
