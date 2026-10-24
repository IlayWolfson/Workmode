import unittest

from focus_guard import allowlist

SITES = ("github.com", "docs.python.org", "claude.ai")


class HostTest(unittest.TestCase):
    def test_exact_and_subdomain_match(self):
        for host in ["github.com", "gist.github.com", "DOCS.PYTHON.ORG", "github.com."]:
            with self.subTest(host=host):
                self.assertTrue(allowlist.host_allowed(host, SITES))

    def test_lookalikes_do_not_match(self):
        for host in ["evilgithub.com", "github.com.evil.example", "notclaude.ai", "python.org", ""]:
            with self.subTest(host=host):
                self.assertFalse(allowlist.host_allowed(host, SITES))


class UrlTest(unittest.TestCase):
    def test_http_and_https_follow_the_host_rule(self):
        self.assertTrue(allowlist.url_allowed("https://github.com/anthropics", SITES))
        self.assertTrue(allowlist.url_allowed("http://docs.python.org/3/", SITES))
        self.assertFalse(allowlist.url_allowed("https://www.youtube.com/watch?v=1", SITES))

    def test_userinfo_trick_uses_the_real_host(self):
        self.assertFalse(allowlist.url_allowed("https://github.com@evil.example/x", SITES))

    def test_browser_internal_pages_are_allowed(self):
        for url in ["chrome://newtab/", "about:blank", "chrome-extension://abc/blocked.html", "file:///C:/notes.txt"]:
            with self.subTest(url=url):
                self.assertTrue(allowlist.url_allowed(url, SITES))

    def test_other_schemes_and_junk_are_blocked(self):
        for url in ["javascript:alert(1)", "data:text/html,hi", "ftp://github.com/x", "", "   ", "not a url"]:
            with self.subTest(url=url):
                self.assertFalse(allowlist.url_allowed(url, SITES))

    def test_a_starred_word_matches_any_host_containing_it(self):
        sites = ["*portfolio*"]
        for host in ["portfolio.github.io", "www.portfolio.com", "my-portfolio.netlify.app", "PORTFOLIO.org"]:
            with self.subTest(host=host):
                self.assertTrue(allowlist.host_allowed(host, sites))
        for host in ["github.io", "example.com", "port.folio.com", ""]:
            with self.subTest(host=host):
                self.assertFalse(allowlist.host_allowed(host, sites))
        self.assertFalse(allowlist.url_allowed("https://example.com/portfolio", sites))  # only the host counts

    def test_empty_site_list_blocks_every_website(self):
        self.assertFalse(allowlist.url_allowed("https://github.com/", ()))


if __name__ == "__main__":
    unittest.main()
