import unittest

from jarvis import browser


class SearchUrlTests(unittest.TestCase):
    def test_google_url_encodes_the_query(self):
        url = browser.build_search_url("futebol de hoje")
        self.assertTrue(url.startswith("https://www.google.com/search?q="))
        self.assertIn("futebol", url)
        self.assertNotIn(" ", url)

    def test_supported_engines(self):
        self.assertIn("bing.com", browser.build_search_url("x", "bing"))
        self.assertIn("duckduckgo.com", browser.build_search_url("x", "duckduckgo"))

    def test_invalid_engine_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Mecanismo"):
            browser.build_search_url("x", "askjeeves")

    def test_empty_query_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "vazia"):
            browser.build_search_url("   ")


class ValidationTests(unittest.TestCase):
    def test_open_page_rejects_non_http(self):
        with self.assertRaisesRegex(ValueError, "http"):
            browser.open_page("file:///etc/passwd")

    def test_click_requires_target(self):
        with self.assertRaisesRegex(ValueError, "elemento"):
            browser.click("  ")

    def test_type_requires_selector(self):
        with self.assertRaisesRegex(ValueError, "seletor"):
            browser.type_into("", "texto")


if __name__ == "__main__":
    unittest.main()
