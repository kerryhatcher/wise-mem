from typer.testing import CliRunner

from wise_mem import cli


runner = CliRunner()


def test_health_command_outputs_expected_payload() -> None:
    result = runner.invoke(cli, [])

    assert result.exit_code == 0
    assert '{"status":"ok","app":"wise-mem"}' in result.stdout
