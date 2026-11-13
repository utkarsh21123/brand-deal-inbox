"""Tests for CLI and failed model call visibility."""
import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dealdesk import cli, llm
from dealdesk.models import EmailResult, Extraction


def test_warn_fallback_prints_summary_on_failures(capsys):
    results = [
        EmailResult(id="E-01", received_at="2026-11-01 10:00", sender="a@b.com", subject="Test 1",
                    category="deal_offer", category_reason="test", rules_category="deal_offer",
                    source="rules (llm failed)", extraction=Extraction()),
        EmailResult(id="E-02", received_at="2026-11-01 10:00", sender="a@b.com", subject="Test 2",
                    category="deal_offer", category_reason="test", rules_category="deal_offer",
                    source="llm+rules", extraction=Extraction()),
        EmailResult(id="E-03", received_at="2026-11-01 10:00", sender="a@b.com", subject="Test 3",
                    category="deal_offer", category_reason="test", rules_category="deal_offer",
                    source="rules (llm failed)", extraction=Extraction()),
    ]
    cli._warn_fallback(results)
    captured = capsys.readouterr()
    assert "WARNING: 2 of 3 emails used rules because the model failed." in captured.err


def test_warn_fallback_silent_when_no_failures(capsys):
    results = [
        EmailResult(id="E-01", received_at="2026-11-01 10:00", sender="a@b.com", subject="Test 1",
                    category="deal_offer", category_reason="test", rules_category="deal_offer",
                    source="llm+rules", extraction=Extraction()),
        EmailResult(id="E-02", received_at="2026-11-01 10:00", sender="a@b.com", subject="Test 2",
                    category="deal_offer", category_reason="test", rules_category="deal_offer",
                    source="rules", extraction=Extraction()),
    ]
    cli._warn_fallback(results)
    captured = capsys.readouterr()
    assert "WARNING" not in captured.err


def test_cli_warns_on_failing_llm(tmp_path, capsys):
    failing_client = llm.Client("test", "m", "http://fake.local/v1", "key")
    failing_client.complete_json = MagicMock(side_effect=llm.LLMError("mocked connection failure"))
    with patch("dealdesk.cli._client", return_value=failing_client):
        args = argparse.Namespace(data="data", out=str(tmp_path), mode="auto", no_cache=True)
        cli.cmd_eval(args)
    captured = capsys.readouterr()
    # E-07 is quarantined as injection; the other 14 emails attempt the model and fail
    assert "WARNING: 14 of 15 emails used rules because the model failed." in captured.err
