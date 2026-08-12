from scripts.github_failure_review import build_failure_review, classify_failure


def test_classify_failure_categories() -> None:
    assert classify_failure("SyntaxError: unterminated string literal") == "syntax_error"
    assert classify_failure("ModuleNotFoundError: No module named pandas") == "dependency_or_import"
    assert classify_failure("HTTP 401 Unauthorized bad credentials token") == "secret_or_auth"
    assert classify_failure("failed to push some refs non-fast-forward") == "git_push_conflict"
    assert classify_failure("deploy pages artifact failed") == "pages_deploy"
    assert classify_failure("Too Many Requests 429 rate limit") == "rate_limit"
    assert classify_failure("The operation timed out") == "timeout_or_cancelled"


def test_build_failure_review_extracts_annotations() -> None:
    runs = [
        {
            "databaseId": 321,
            "workflowName": "Taiwan Stock AI Daily",
            "displayTitle": "update dashboard",
            "status": "completed",
            "conclusion": "failure",
            "createdAt": "2026-08-12T00:30:00Z",
            "url": "https://github.com/example/runs/321",
        }
    ]
    details = {
        321: {
            "annotations": [
                {
                    "annotation_level": "failure",
                    "path": "scripts/weekly_review.py",
                    "start_line": 88,
                    "title": "SyntaxError",
                    "message": "unterminated string literal",
                }
            ],
            "jobs": [],
        }
    }

    review = build_failure_review(runs, details)

    assert review["status"] == "ok"
    assert review["summary"]["failed_run_count"] == 1
    assert review["summary"]["categories"] == {"syntax_error": 1}
    failure = review["recent_failures"][0]
    assert failure["run_id"] == 321
    assert failure["root_cause"] == "syntax_error"
    assert failure["annotation_count"] == 1
    assert failure["annotation_categories"] == {"syntax_error": 1}
    assert "annotations" not in failure
