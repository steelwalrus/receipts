import sqlite3
import tempfile
import unittest
from pathlib import Path

from receipts import dates
from receipts.store import Store


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "receipts.db")
        self.dev = self.store.add_role("Developer", "2016", organisation="Example Ltd", ended="2018-05")
        self.lead = self.store.add_role("Team Lead", "2018-06", organisation="Example Ltd", ended="2020-12")
        self.head = self.store.add_role("Head of Engineering", "2021-01", organisation="Other Co")

    def tearDown(self):
        self.tmp.cleanup()


class DatesTest(unittest.TestCase):
    def test_normalise(self):
        self.assertEqual(dates.normalise("2019"), "2019")
        self.assertEqual(dates.normalise(" 2019-06 "), "2019-06")
        self.assertEqual(dates.normalise("2021-Q3"), "2021-07")
        self.assertIsNone(dates.normalise(""))
        self.assertIsNone(dates.normalise("present"))
        for bad in ("spring 2019", "2019-13", "2019-02-30", "19"):
            with self.assertRaises(ValueError):
                dates.normalise(bad)

    def test_bounds_and_labels(self):
        self.assertEqual(dates.lower_bound("2019"), "2019-01-01")
        self.assertEqual(dates.upper_bound("2020-02"), "2020-02-29")
        self.assertEqual(dates.span_label("2018-06", "2019-01"), "Jun 2018 – Jan 2019")
        self.assertEqual(dates.span_label("2021", None, approximate=True), "c. 2021")
        self.assertEqual(dates.span_label("2022-09", None, open_ended="present"), "Sep 2022 – present")


class EntryTest(StoreTestCase):
    def test_role_is_inferred_from_date(self):
        entry = self.store.add_entry("Hired a team", happened_from="2019-03")
        self.assertEqual(entry["role"]["title"], "Team Lead")
        current = self.store.add_entry("Recent thing", happened_from="2024")
        self.assertEqual(current["role"]["title"], "Head of Engineering")

    def test_explicit_role_and_no_role(self):
        entry = self.store.add_entry("Thing", happened_from="2019", role_id=self.dev["id"])
        self.assertEqual(entry["role_id"], self.dev["id"])
        loose = self.store.add_entry("Undated thing", role_id=None)
        self.assertIsNone(loose["role"])

    def test_competencies_accept_slugs_or_names_and_reject_unknown(self):
        entry = self.store.add_entry("Thing", competencies=["hiring", "Coaching & mentoring"])
        self.assertEqual(entry["competencies"], ["hiring", "coaching"])
        with self.assertRaisesRegex(ValueError, "Unknown competency: juggling"):
            self.store.add_entry("Bad", competencies=["juggling"])
        self.assertEqual(self.store.stats()["entries"], 1, "a failed add must not leave a half-written entry")

    def test_update_changes_only_given_fields(self):
        entry = self.store.add_entry("Thing", summary="First", competencies=["delivery"], tags=["Alpha"])
        updated = self.store.update_entry(entry["id"], result="It shipped")
        self.assertEqual(updated["summary"], "First")
        self.assertEqual(updated["competencies"], ["delivery"])
        self.assertEqual(updated["tags"], ["alpha"])
        self.assertEqual(updated["result"], "It shipped")
        cleared = self.store.update_entry(entry["id"], tags=[])
        self.assertEqual(cleared["tags"], [])

    def test_completeness_and_missing(self):
        bare = self.store.add_entry("Bare")
        self.assertEqual(bare["completeness"], 0.0)
        full = self.store.add_entry("Full", happened_from="2019", competencies=["delivery"], situation="s",
                                    action="a", result="r", impact="£1m")
        self.assertEqual(full["missing"], [])
        self.assertEqual(full["completeness"], 1.0)

    def test_date_validation(self):
        with self.assertRaises(ValueError):
            self.store.add_entry("Backwards", happened_from="2020", happened_to="2019")
        with self.assertRaises(ValueError):
            self.store.add_entry("No start", happened_to="2019")
        with self.assertRaises(ValueError):
            self.store.add_entry("", happened_from="2019")

    def test_delete_entry(self):
        entry = self.store.add_entry("Gone soon", summary="unique words here")
        self.store.delete_entry(entry["id"])
        with self.assertRaises(KeyError):
            self.store.entry(entry["id"])
        self.assertEqual(self.store.entries("unique"), [])


class SearchTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.pdf = self.store.add_entry("Delivered the PDF service", summary="Replaced an expensive vendor",
                                        happened_from="2023", competencies=["commercial"], tags=["pdf-service"])
        self.coach = self.store.add_entry("Coached a new manager", summary="Weekly one-to-ones",
                                          happened_from="2019", competencies=["coaching"])

    def test_text_search_uses_stemming_and_falls_back_to_any_word(self):
        self.assertEqual([e["id"] for e in self.store.entries("delivering")], [self.pdf["id"]])
        both = self.store.entries("vendor coaching")
        self.assertEqual({e["id"] for e in both}, {self.pdf["id"], self.coach["id"]})

    def test_search_covers_competency_names_and_role(self):
        self.assertEqual([e["id"] for e in self.store.entries("commercial")], [self.pdf["id"]])
        self.assertEqual([e["id"] for e in self.store.entries("team lead")], [self.coach["id"]])

    def test_index_follows_role_rename(self):
        self.store.update_role(self.lead["id"], title="Engineering Manager")
        self.assertEqual([e["id"] for e in self.store.entries("engineering manager")], [self.coach["id"]])

    def test_filters(self):
        self.assertEqual([e["id"] for e in self.store.entries(competency="coaching")], [self.coach["id"]])
        self.assertEqual([e["id"] for e in self.store.entries(tag="PDF-Service")], [self.pdf["id"]])
        self.assertEqual([e["id"] for e in self.store.entries(role_id=self.head["id"])], [self.pdf["id"]])
        self.assertEqual([e["id"] for e in self.store.entries(date_from="2022", date_to="2024")], [self.pdf["id"]])

    def test_awkward_query_text_is_safe(self):
        self.assertEqual(self.store.entries('"unbalanced AND OR NEAR('), [])
        self.assertEqual(len(self.store.entries("")), 2)


class RolesAndViewsTest(StoreTestCase):
    def test_deleting_a_role_keeps_its_entries(self):
        entry = self.store.add_entry("Thing", happened_from="2017")
        self.store.delete_role(self.dev["id"])
        self.assertIsNone(self.store.entry(entry["id"])["role"])
        self.assertEqual([e["id"] for e in self.store.timeline()["unplaced"]], [entry["id"]])

    def test_timeline_orders_roles_and_entries(self):
        later = self.store.add_entry("Later", happened_from="2020")
        earlier = self.store.add_entry("Earlier", happened_from="2018-07")
        timeline = self.store.timeline()
        self.assertEqual([r["title"] for r in timeline["roles"]], ["Developer", "Team Lead", "Head of Engineering"])
        self.assertEqual([e["id"] for e in timeline["roles"][1]["entries"]], [earlier["id"], later["id"]])
        self.assertEqual(timeline["roles"][0]["label"], "2016 – May 2018")

    def test_coverage_against_a_profile(self):
        self.store.add_entry("Org redesign", happened_from="2022", competencies=["org-design"],
                             situation="s", action="a", result="r", impact="i")
        self.store.add_entry("Vague change thing", happened_from="2022", competencies=["change"], strength=1)
        data = self.store.coverage("head-of-engineering")
        status = {c["slug"]: c["status"] for c in data["profile"]["competencies"]}
        self.assertEqual(status["org-design"], "covered")
        self.assertEqual(status["change"], "thin")
        self.assertEqual(status["scaling"], "missing")
        org = next(c for c in data["competencies"] if c["slug"] == "org-design")
        self.assertEqual(org["by_role"], {str(self.head["id"]): 1})

    def test_custom_profile_and_competency(self):
        self.store.add_competency("fundraising", "Fundraising", "Business")
        profile = self.store.set_profile("acme-cto", "Acme CTO", ["architecture", "fundraising"], ["hiring"])
        self.assertEqual(profile["core"], ["architecture", "fundraising"])
        self.assertIn("acme-cto", [p["slug"] for p in self.store.profiles()])
        with self.assertRaises(ValueError):
            self.store.set_profile("bad", "Bad", ["nonsense"])


class MigrationTest(unittest.TestCase):
    def test_reopening_is_idempotent_and_newer_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.db"
            Store(path).add_role("Dev", "2016")
            self.assertEqual(Store(path).stats()["roles"], 1)
            db = sqlite3.connect(path)
            db.execute("PRAGMA user_version = 99")
            db.close()
            with self.assertRaises(RuntimeError):
                Store(path)

    def test_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "r.db")
            store.add_role("Dev", "2016")
            copy = store.backup(Path(tmp) / "backup.db")
            self.assertEqual(Store(copy).stats()["roles"], 1)
            with self.assertRaises(ValueError):
                store.backup(copy)


if __name__ == "__main__":
    unittest.main()
