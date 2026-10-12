import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from receipts.store import Store

try:
    from receipts.mcp_server import build
except ImportError:  # the mcp package is optional for the web UI
    build = None


def text(result):
    # mcp 2.x returns a CallToolResult; 1.x returns (content, structured) or a content list.
    content = getattr(result, "content", None)
    if content is None:
        content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text) if content and content[0].text.strip()[:1] in "[{" else content[0].text


@unittest.skipIf(build is None, "mcp package not installed")
class McpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "r.db")
        self.server = build(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, tool, **args):
        return asyncio.run(self.server.call_tool(tool, args))

    def test_tools_and_prompts_are_registered(self):
        tools = {t.name for t in asyncio.run(self.server.list_tools())}
        self.assertTrue({"overview", "add_entry", "update_entry", "search_entries", "coverage", "set_profile"} <= tools)
        prompts = {p.name for p in asyncio.run(self.server.list_prompts())}
        self.assertEqual(prompts, {"capture", "prep", "review"})

    def test_capture_flow(self):
        role = text(self.call("add_role", title="Head of Engineering", started="2022-09", organisation="Example"))
        entry = text(self.call("add_entry", title="Closed a team", summary="Did it well", happened_from="2023",
                               approximate=True, competencies=["change"], follow_ups="Exact date?"))
        self.assertEqual(entry["role"], "Head of Engineering, Example")
        self.assertEqual(entry["when"], "c. 2023")
        updated = text(self.call("update_entry", entry_id=entry["id"], result="Shipped", role_id=0))
        self.assertIsNone(updated["role"])
        self.assertEqual(updated["summary"], "Did it well")
        found = text(self.call("search_entries", query="closed"))
        self.assertEqual([e["id"] for e in found["entries"]], [entry["id"]])
        overview = text(self.call("overview"))
        self.assertEqual(overview["roles"][0]["id"], role["id"])

    def test_gap_analysis_from_a_job_description(self):
        self.call("add_entry", title="Hiring", summary="s", happened_from="2020", competencies=["hiring"],
                  situation="s", action="a", result="r", impact="i")
        self.call("set_profile", slug="acme", name="Acme EM", core=["hiring", "coaching"])
        gaps = text(self.call("coverage", profile="acme"))
        status = {c["slug"]: c["status"] for c in gaps["competencies"]}
        self.assertEqual(status, {"hiring": "covered", "coaching": "missing"})

    def test_bad_input_reports_an_error(self):
        result = asyncio.run(self._call_safely("add_entry", title="x", summary="y", competencies=["juggling"]))
        self.assertIn("Unknown competency", result)

    async def _call_safely(self, tool, **args):
        try:
            result = await self.server.call_tool(tool, args)
        except Exception as error:  # 1.x raises ToolError
            return str(error)
        return str(getattr(result, "content", result))


if __name__ == "__main__":
    unittest.main()
