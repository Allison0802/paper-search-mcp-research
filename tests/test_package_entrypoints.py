import json
import importlib.metadata as metadata
import sys
import unittest
from unittest.mock import AsyncMock

import pytest

from paper_search_mcp import cli, server


class TestPackageEntrypoints(unittest.TestCase):
    def test_console_scripts_are_exposed(self):
        dist = metadata.distribution("paper-search-mcp-research")
        console_scripts = {
            entry_point.name: entry_point.value
            for entry_point in dist.entry_points
            if entry_point.group == "console_scripts"
        }

        self.assertEqual(
            console_scripts.get("paper-search-mcp"),
            "paper_search_mcp.server:main",
        )
        self.assertEqual(
            console_scripts.get("paper-search"),
            "paper_search_mcp.cli:main",
        )


if __name__ == "__main__":
    unittest.main()


def _run_cli(monkeypatch, arguments):
    monkeypatch.setattr(sys, "argv", ["paper-search", *arguments])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    return exit_info.value.code


def test_issue_list_cli_delegates_and_prints_json(monkeypatch, capsys):
    result = {
        "journal": "Biometrika",
        "volume": "113",
        "issue": "3",
        "total": 1,
        "papers": [],
    }
    tool = AsyncMock(return_value=result)
    monkeypatch.setattr(server, "list_journal_issue", tool)

    exit_code = _run_cli(monkeypatch, ["issue-list", "Biometrika", "113", "3"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == result
    tool.assert_awaited_once_with("Biometrika", "113", "3")


def test_issue_download_cli_delegates_options_and_prints_json(monkeypatch, capsys):
    result = {
        "journal": "Biometrika",
        "volume": "113",
        "issue": "3",
        "downloaded": 1,
        "papers": [],
    }
    tool = AsyncMock(return_value=result)
    monkeypatch.setattr(server, "download_journal_issue", tool)

    exit_code = _run_cli(
        monkeypatch,
        ["issue-download", "Biometrika", "113", "3", "-o", "./papers", "--concurrency", "4", "--overwrite"],
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == result
    tool.assert_awaited_once_with(
        "Biometrika",
        "113",
        "3",
        save_path="./papers",
        max_concurrency=4,
        overwrite=True,
    )


@pytest.mark.parametrize(
    ("arguments", "tool_name"),
    [
        (["issue-list", "Biometrika", "113", "3"], "list_journal_issue"),
        (["issue-download", "Biometrika", "113", "3"], "download_journal_issue"),
    ],
)
def test_issue_cli_reports_discovery_errors_with_nonzero_exit(monkeypatch, capsys, arguments, tool_name):
    result = {"discovery_status": "error", "error": "Crossref request failed"}
    monkeypatch.setattr(server, tool_name, AsyncMock(return_value=result))

    exit_code = _run_cli(monkeypatch, arguments)

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out) == result
