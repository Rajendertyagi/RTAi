"""Content-kind classification for safe observability (Task 1).

Drives the REAL ``classify_content_blocks`` helper from
``app.agents.acp.mapping``. The helper must classify mapped ACP content
blocks into a fixed safe enum (none/text/diff/terminal/other/mixed) plus a
bounded block count, reading ONLY the ``type`` key of each block.

These tests assert on the classification outputs only. They never assert on
text, path, oldText/newText, terminalId, or any other content value, and
they verify the helper never exposes those values through its return tuple.
"""

from __future__ import annotations

import unittest

from app.agents.acp.mapping import classify_content_blocks


class ClassifyContentBlocksTests(unittest.TestCase):
    def test_none_for_empty_list(self) -> None:
        kind, count = classify_content_blocks([])
        self.assertEqual(kind, "none")
        self.assertEqual(count, 0)

    def test_none_for_none_input(self) -> None:
        kind, count = classify_content_blocks(None)
        self.assertEqual(kind, "none")
        self.assertEqual(count, 0)

    def test_text_for_content_blocks(self) -> None:
        blocks = [
            {"type": "content", "text": "a very long secret prompt goes here"},
            {"type": "content", "text": "second chunk"},
        ]
        kind, count = classify_content_blocks(blocks)
        self.assertEqual(kind, "text")
        self.assertEqual(count, 2)

    def test_diff_for_diff_blocks(self) -> None:
        blocks = [
            {
                "type": "diff",
                "path": "/home/secret/file.txt",
                "oldText": "line one\nline two",
                "newText": "line one\nline two modified",
            }
        ]
        kind, count = classify_content_blocks(blocks)
        self.assertEqual(kind, "diff")
        self.assertEqual(count, 1)

    def test_terminal_for_terminal_blocks(self) -> None:
        blocks = [{"type": "terminal", "terminalId": "term-9"}]
        kind, count = classify_content_blocks(blocks)
        self.assertEqual(kind, "terminal")
        self.assertEqual(count, 1)

    def test_other_for_unknown_block_types(self) -> None:
        blocks = [
            {"type": "image", "data": "base64...."},
            {"type": "weird", "payload": "x"},
        ]
        kind, count = classify_content_blocks(blocks)
        self.assertEqual(kind, "other")
        self.assertEqual(count, 2)

    def test_mixed_for_multiple_known_types(self) -> None:
        blocks = [
            {"type": "content", "text": "log line"},
            {"type": "diff", "path": "x", "oldText": "a", "newText": "b"},
            {"type": "terminal", "terminalId": "t"},
        ]
        kind, count = classify_content_blocks(blocks)
        self.assertEqual(kind, "mixed")
        self.assertEqual(count, 3)

    def test_classification_ignores_content_values(self) -> None:
        # Even when blocks carry sensitive-looking values, the helper must
        # report only the type-derived kind and a count — never echo content.
        blocks = [
            {"type": "diff", "path": "/etc/passwd", "oldText": "root:x:0:0", "newText": "root:x:0:1"},
            {"type": "content", "text": "sk-1234567890abcdef"},
        ]
        kind, count = classify_content_blocks(blocks)
        self.assertEqual(kind, "mixed")
        self.assertEqual(count, 2)
        # The return tuple is (str, int) — no nested content is exposed.
        self.assertIsInstance(kind, str)
        self.assertIsInstance(count, int)


if __name__ == "__main__":
    unittest.main()
