import tempfile
import unittest
from pathlib import Path

from app.core.protocol import extract_latest_user_text, resolve_project_path, text_from_acp_update


class TextContentBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class AgentMessageChunk:
    def __init__(self, text: str) -> None:
        self.content = TextContentBlock(text)


class ToolCallStart:
    content = TextContentBlock("not chat text")


class ProtocolTests(unittest.TestCase):
    def test_extracts_latest_user_text(self) -> None:
        payload = {"text": "  hello world  "}
        self.assertEqual(extract_latest_user_text(payload), "hello world")

    def test_rejects_missing_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expected a 'text' field"):
            extract_latest_user_text({})

    def test_rejects_empty_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expected a 'text' field"):
            extract_latest_user_text({"text": "   "})

    def test_resolves_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(resolve_project_path(folder), Path(folder).resolve())

    def test_rejects_missing_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not exist"):
            resolve_project_path("/definitely/not/a/real/poc/path")

    def test_rejects_blank_string(self) -> None:
        with self.assertRaisesRegex(ValueError, "project_folder_not_provided"):
            resolve_project_path("")

    def test_rejects_whitespace_only(self) -> None:
        with self.assertRaisesRegex(ValueError, "project_folder_not_provided"):
            resolve_project_path("   ")

    def test_rejects_none(self) -> None:
        with self.assertRaisesRegex(ValueError, "project_folder_not_provided"):
            resolve_project_path(None)

    def test_extracts_only_agent_message_chunks(self) -> None:
        self.assertEqual(text_from_acp_update(AgentMessageChunk("hello")), "hello")
        self.assertIsNone(text_from_acp_update(ToolCallStart()))


if __name__ == "__main__":
    unittest.main()
