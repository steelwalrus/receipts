import tempfile
import unittest
from pathlib import Path

from receipts.portable import export_json, export_markdown, import_json
from receipts.store import Store


class PortableTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = Store(Path(self.tmp.name) / "a.db")
        self.source.add_role("Developer", "2016", organisation="Example Ltd", ended="2018")
        self.source.add_role("Director", "2019", organisation="Example Ltd")
        self.source.add_competency("fundraising", "Fundraising", "Business")
        self.source.add_entry("Raised money", happened_from="2020", competencies=["fundraising"], tags=["seed"],
                              action="Pitched", impact="£2m")
        self.source.add_entry("Undated", role_id=None, summary="No date yet")

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_is_idempotent(self):
        data = export_json(self.source)
        target = Store(Path(self.tmp.name) / "b.db")
        self.assertEqual(import_json(target, data), {"roles_added": 2, "entries_added": 2, "entries_skipped": 0})
        self.assertEqual(import_json(target, data), {"roles_added": 0, "entries_added": 0, "entries_skipped": 2})
        raised = target.entries("raised")[0]
        self.assertEqual((raised["role"]["title"], raised["competencies"], raised["impact"]),
                         ("Director", ["fundraising"], "£2m"))
        self.assertIsNone(target.entries("undated")[0]["role"])

    def test_rejects_other_formats(self):
        with self.assertRaises(ValueError):
            import_json(self.source, {"format": "something-else"})

    def test_markdown(self):
        text = export_markdown(self.source)
        self.assertIn("## Director, Example Ltd", text)
        self.assertIn("**Impact:** £2m", text)
        self.assertIn("## Not yet placed on the timeline", text)
        self.assertLess(text.index("## Director"), text.index("## Developer"))


if __name__ == "__main__":
    unittest.main()
