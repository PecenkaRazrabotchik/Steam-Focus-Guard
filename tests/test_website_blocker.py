import unittest
from src.website_blocker import normalise_domain, normalise_domains, _without_managed_section


class WebsiteRuleTests(unittest.TestCase):
    def test_normalise_domain_accepts_url_and_deduplicates(self):
        self.assertEqual(normalise_domain("https://YouTube.com/watch?v=1"), "youtube.com")
        self.assertEqual(normalise_domains(["youtube.com", "https://youtube.com/"]), ["youtube.com"])

    def test_invalid_domains_are_rejected(self):
        for value in ("", "*.example.com", "localhost", "not a domain"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalise_domain(value)

    def test_managed_hosts_section_can_be_removed_without_touching_other_lines(self):
        text = "127.0.0.1 localhost\n# >>> FOCUS GUARD MANAGED WEBSITE BLOCKS >>>\n0.0.0.0 example.com\n# <<< FOCUS GUARD MANAGED WEBSITE BLOCKS <<<\n192.168.1.1 router\n"
        cleaned = _without_managed_section(text)
        self.assertIn("127.0.0.1 localhost", cleaned)
        self.assertIn("192.168.1.1 router", cleaned)
        self.assertNotIn("example.com", cleaned)


if __name__ == "__main__":
    unittest.main()
