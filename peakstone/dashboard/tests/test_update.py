def test_update_check_reports_install(capsys):
    from peakstone.dashboard.update import update_main, _install_kind
    assert update_main(["--check"]) == 0            # --check never runs an upgrade
    out = capsys.readouterr().out
    assert "peakstone" in out and _install_kind() in out
