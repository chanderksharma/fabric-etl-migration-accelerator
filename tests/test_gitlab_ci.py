"""Static and PowerShell contracts for modular GitLab Fabric CI pipelines."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
CI_ROOT = ROOT / ".gitlab" / "ci"


def _script_blocks(path: Path) -> list[str]:
    """Extract literal PowerShell blocks under GitLab script/before_script lists."""
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() == "- |":
            indent = len(lines[index]) - len(lines[index].lstrip()) + 2
            index += 1
            block: list[str] = []
            while index < len(lines):
                line = lines[index]
                if line.strip() and len(line) - len(line.lstrip()) < indent:
                    break
                block.append(line[indent:] if len(line) >= indent else "")
                index += 1
            blocks.append("\n".join(block))
            continue
        index += 1
    return blocks


def test_gitlab_includes_have_valid_powershell_blocks() -> None:
    paths = [
        ROOT / ".gitlab-ci.yml",
        CI_ROOT / "deploy-fabric-artifacts.yml",
        CI_ROOT / "create-fabric-deployment-pipeline.yml",
        CI_ROOT / "promote-fabric-alm.yml",
    ]
    for path in paths:
        blocks = _script_blocks(path)
        assert blocks, f"No PowerShell blocks found in {path}"
        for block in blocks:
            command = (
                "$tokens=$null; $errors=$null; "
                "[System.Management.Automation.Language.Parser]::ParseInput("
                "$env:SCRIPT,[ref]$tokens,[ref]$errors)|Out-Null; "
                "if($errors.Count){$errors|ForEach-Object{$_.Message};exit 1}"
            )
            result = subprocess.run(
                ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=ROOT,
                env=os.environ | {"SCRIPT": block},
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            assert result.returncode == 0, f"{path}: {result.stdout} {result.stderr}"


def test_gitlab_promotion_is_planned_then_manually_promoted() -> None:
    content = (CI_ROOT / "promote-fabric-alm.yml").read_text(encoding="utf-8")

    assert content.index("plan_fabric_alm_promotion:") < content.index("promote_fabric_alm:")
    assert "needs:" in content
    assert "artifacts: true" in content
    assert "action: verify" in content
    assert "when: manual" in content
    assert "allow_failure: false" in content
    assert "SelectedItemsJson = $env:SELECTED_ITEMS" in content
    assert "DependenciesReviewed = $env:DEPENDENCIES_REVIEWED -eq \"true\"" in content
    assert "ReviewedPlanJson = $ReviewedPlanJson" in content
