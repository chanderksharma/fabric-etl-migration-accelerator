"""Static and PowerShell contracts for modular GitLab Fabric CI pipelines."""

import hashlib
import json
import os
import shutil
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


def test_gitlab_revision_check_blocks_deployment_on_mismatch(tmp_path: Path) -> None:
    git_env = os.environ | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run(
        ["git", "-c", "init.templateDir=", "init", "-q", str(tmp_path)],
        env=git_env,
        check=True,
        timeout=30,
    )
    subprocess.run(
        [
            "git", "-c", "user.name=Synthetic Test", "-c", "user.email=test@example.invalid",
            "commit", "--allow-empty", "-q", "-m", "Synthetic test",
        ],
        cwd=tmp_path,
        env=git_env,
        check=True,
        timeout=30,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=tmp_path,
        env=git_env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(
        ROOT / "scripts" / "Assert-DeploymentRevision.ps1",
        scripts / "Assert-DeploymentRevision.ps1",
    )
    shutil.copyfile(
        ROOT / "scripts" / "Assert-DeploymentPublication.ps1",
        scripts / "Assert-DeploymentPublication.ps1",
    )
    (scripts / "Deploy-FabricArtifacts.ps1").write_text(
        "Set-Content -Path $env:MARKER -Value 'deployed'", encoding="utf-8"
    )
    marker = tmp_path / "deployed.txt"
    other = "0" * 40 if commit != "0" * 40 else "1" * 40
    block = _script_blocks(CI_ROOT / "deploy-fabric-artifacts.yml")[0]
    for expected, source, success in [
        (commit, commit, True),
        (commit, other, False),
        (other, other, False),
        ("main", commit, False),
    ]:
        marker.unlink(missing_ok=True)
        result = subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", block],
            cwd=tmp_path,
            env=os.environ | {
                "FABRIC_EXPECTED_COMMIT": expected,
                "FABRIC_PUBLICATION_MANIFEST_SHA256": "",
                "CI_COMMIT_SHA": source,
                "FABRIC_WORKSPACE_ID": "synthetic-workspace",
                "TARGET": "Notebook",
                "CONFLICT_BEHAVIOR": "Fail",
                "DRY_RUN": "false",
                "ARTIFACT_ROOT": "artifacts",
                "WORKFLOW_FILTER": "*",
                "MARKER": str(marker),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert (result.returncode == 0) is success, result.stdout + result.stderr
        assert marker.exists() is success


def test_gitlab_publication_guard_runs_before_deployment(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("Assert-DeploymentRevision.ps1", "Assert-DeploymentPublication.ps1"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    (scripts / "Deploy-FabricArtifacts.ps1").write_text(
        "Set-Content -Path $env:MARKER -Value 'deployed'", encoding="utf-8"
    )
    git_env = os.environ | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run(
        ["git", "-c", "init.templateDir=", "init", "-q", str(tmp_path)],
        env=git_env, check=True, timeout=30,
    )
    subprocess.run(
        [
            "git", "-c", "user.name=Synthetic Test", "-c", "user.email=test@example.invalid",
            "commit", "--allow-empty", "-q", "-m", "Synthetic test",
        ],
        cwd=tmp_path, env=git_env, check=True, timeout=30,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=tmp_path, env=git_env,
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout.strip()
    run_id, digest = "1" * 32, "2" * 64
    artifact_root = f"published-fabric-workflows/{run_id}/{digest}"
    root = tmp_path / "published-fabric-workflows" / run_id / digest
    root.mkdir(parents=True)
    artifact = root / "item.json"
    artifact.write_bytes(b"synthetic-definition")
    manifest = {
        "version": 1,
        "run_id": run_id,
        "files": [{
            "path": "item.json",
            "size_bytes": len(artifact.read_bytes()),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }],
    }
    manifest_path = root / "publication-manifest.json"
    manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    marker = tmp_path / "deployed.txt"
    block = _script_blocks(CI_ROOT / "deploy-fabric-artifacts.yml")[0]
    environment = git_env | {
        "FABRIC_EXPECTED_COMMIT": commit,
        "FABRIC_PUBLICATION_MANIFEST_SHA256": manifest_hash,
        "CI_COMMIT_SHA": commit,
        "FABRIC_WORKSPACE_ID": "synthetic-workspace",
        "TARGET": "Notebook",
        "CONFLICT_BEHAVIOR": "Fail",
        "DRY_RUN": "false",
        "ARTIFACT_ROOT": artifact_root,
        "WORKFLOW_FILTER": "*",
        "MARKER": str(marker),
    }

    def run_job(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        marker.unlink(missing_ok=True)
        return subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", block],
            cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=30,
        )

    result = run_job(environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.exists()
    artifact.write_bytes(b"synthetic-definitioN")
    assert run_job(environment).returncode != 0
    assert not marker.exists()
    assert run_job(environment | {"FABRIC_EXPECTED_COMMIT": ""}).returncode != 0
    assert not marker.exists()


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
