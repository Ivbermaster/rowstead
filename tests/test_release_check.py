"""Publication guard regressions: avoid reading private files or leaking findings."""

from pathlib import Path

from scripts import check_release as release


def credential_line(value):
    return "".join(("PASS", "WORD", " = ", repr(value)))


def test_private_paths_are_never_read(tmp_path, monkeypatch):
    for name in (".env", "data/input.csv", "artifacts/backup.dump", "outputs/export.xlsx"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private", encoding="utf-8")
    (tmp_path / "README.md").write_text("Public synthetic demo", encoding="utf-8")
    original = Path.read_bytes

    def guarded_read(path):
        assert path.name == "README.md", "Private contents must never be opened"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    findings, count, _ = release.check(tmp_path)
    assert not findings and count == 1


def test_credential_is_found_without_printing_value():
    value = "synthetic-" + "credential-value-for-regression"
    text = "# public\n" + credential_line(value) + "\n"
    findings = release.secret_findings("app/config.py", text)
    assert len(findings) == 1 and findings[0].line == 2
    assert value not in str(findings[0])


def test_provider_token_and_private_key_are_detected():
    values = ["ghp_" + "a" * 36, "-----BEGIN " + "PRIVATE KEY-----"]
    for value in values:
        assert release.secret_findings("app/config.py", value)


def test_unquoted_env_example_value_is_blocked():
    text = "".join(("SESSION_", "SECRET", "=", "synthetic-example-must-stay-empty"))
    assert release.secret_findings(".env.example", text)
    assert not release.secret_findings(".env.example", "SESSION_SECRET=\nPOSTGRES_PASSWORD=\n")


def test_test_exceptions_are_exact_and_scoped():
    value = next(iter(release.KNOWN_TEST_VALUES["tests/test_api.py"]))
    text = credential_line(value)
    assert not release.secret_findings("tests/test_api.py", text)
    assert release.secret_findings("app/config.py", text)
    assert release.secret_findings("tests/test_other.py", text)
    assert release.secret_findings("tests/test_api.py", text[:-1] + "extra'")


def test_forbidden_path_is_rejected_before_reading(tmp_path, monkeypatch):
    def no_read(path):
        raise AssertionError("Forbidden file was read")

    monkeypatch.setattr(Path, "read_bytes", no_read)
    for path in (".env", "data/import.csv", "app/../../outside.py", "docs/secret.pem"):
        assert release.inspect_file(tmp_path, path)


def test_oversized_and_disguised_binary_are_blocked(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_bytes(b"\x00binary")
    assert release.inspect_file(tmp_path, "README.md")[0].code == "binary source file"
    monkeypatch.setattr(release, "MAX_TEXT_BYTES", 2)
    assert "size limit" in release.inspect_file(tmp_path, "README.md")[0].code


def test_junction_or_symlink_is_not_followed(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "external").mkdir()
    (tmp_path / "docs" / "external" / "private.md").write_text("not public", encoding="utf-8")
    original = release.reparse_point
    monkeypatch.setattr(
        release, "reparse_point", lambda path: path.name == "external" or original(path)
    )
    files = list(release.source_files(tmp_path))
    assert files == [("docs/external", "link")]


def test_index_and_head_are_checked_independently_of_working_tree(tmp_path):
    assert release.git(tmp_path, "init", "--quiet").returncode == 0
    (tmp_path / ".gitignore").write_text("\n".join(release.IGNORE_PROBES), encoding="utf-8")
    path = tmp_path / "README.md"
    marker = credential_line("synthetic-" + "index-only-value")
    path.write_text(marker, encoding="utf-8")
    assert release.git(tmp_path, "add", "--", "README.md", ".gitignore").returncode == 0
    path.write_text("clean working copy", encoding="utf-8")
    findings, _ = release.git_findings(tmp_path, True)
    assert any(issue.path == "README.md" and issue.line == 1 for issue in findings)
    assert (
        release.git(
            tmp_path,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Synthetic staged fixture",
        ).returncode
        == 0
    )
    assert release.git(tmp_path, "add", "--", "README.md").returncode == 0
    findings, _ = release.git_findings(tmp_path, True)
    assert any(issue.path == "README.md" and issue.line == 1 for issue in findings)


def test_private_index_path_is_rejected_without_blob_read(tmp_path, monkeypatch):
    assert release.git(tmp_path, "init", "--quiet").returncode == 0
    (tmp_path / ".env").write_text("not-read", encoding="utf-8")
    assert release.git(tmp_path, "add", "--", ".env").returncode == 0
    monkeypatch.setattr(
        release,
        "inspect_blob",
        lambda *args: (_ for _ in ()).throw(AssertionError("Private Git blob must not be read")),
    )
    findings, _ = release.git_findings(tmp_path, True)
    assert any(issue.path == ".env" and "index" in issue.code for issue in findings)
