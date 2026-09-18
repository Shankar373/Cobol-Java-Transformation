"""Tests for execution abstractions."""

import pytest

from engine.execution.abstractions import (
    ExecutionCommand,
    ExecutionEngine,
    ExecutionEnvironment,
    ExecutionPolicy,
    ExecutionResult,
    FilesystemPolicy,
    NetworkPolicy,
    ResourceLimits,
    StagedSource,
)

# ---------------------------------------------------------------------------
# ResourceLimits tests
# ---------------------------------------------------------------------------

class TestResourceLimits:
    def test_valid_limits(self):
        limits = ResourceLimits(memory="512m", cpu="1.0", pids=256, timeout_seconds=30)
        assert limits.memory == "512m"
        assert limits.timeout_seconds == 30

    def test_invalid_timeout(self):
        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            ResourceLimits(timeout_seconds=0)

    def test_invalid_pids(self):
        with pytest.raises(ValueError, match="pids must be positive"):
            ResourceLimits(pids=0)


# ---------------------------------------------------------------------------
# FilesystemPolicy tests
# ---------------------------------------------------------------------------

class TestFilesystemPolicy:
    def test_valid_policy(self):
        policy = FilesystemPolicy(
            read_only_paths=("/workspace",),
            no_write_paths=("/source",),
        )
        assert "/workspace" in policy.read_only_paths

    def test_validate_root_read_only(self):
        policy = FilesystemPolicy(no_write_paths=("/",))
        with pytest.raises(ValueError, match="Cannot make root read-only"):
            policy.validate()


# ---------------------------------------------------------------------------
# NetworkPolicy tests
# ---------------------------------------------------------------------------

class TestNetworkPolicy:
    def test_disabled_network(self):
        policy = NetworkPolicy(enabled=False)
        assert not policy.enabled

    def test_enabled_without_hosts(self):
        with pytest.raises(ValueError, match="no allowed hosts"):
            NetworkPolicy(enabled=True, allowed_hosts=())

    def test_enabled_with_hosts(self):
        policy = NetworkPolicy(enabled=True, allowed_hosts=("example.com",))
        assert policy.enabled


# ---------------------------------------------------------------------------
# ExecutionCommand tests
# ---------------------------------------------------------------------------

class TestExecutionCommand:
    def test_simple_command(self):
        cmd = ExecutionCommand(command="echo", arguments=("hello",))
        assert cmd.to_string() == "echo hello"

    def test_working_directory(self):
        cmd = ExecutionCommand(command="ls", working_directory="/tmp")
        assert cmd.working_directory == "/tmp"


# ---------------------------------------------------------------------------
# ExecutionResult tests
# ---------------------------------------------------------------------------

class TestExecutionResult:
    def test_successful_execution(self):
        cmd = ExecutionCommand(command="echo", arguments=("hello",))
        result = ExecutionResult(
            command=cmd,
            exit_code=0,
            stdout=b"hello\n",
            stderr=b"",
            start_time="2026-09-14T00:00:00Z",
            end_time="2026-09-14T00:00:01Z",
            termination_status="normal",
            timeout_applied=False,
        )
        assert result.succeeded
        assert not result.failed
        assert not result.timed_out

    def test_failed_execution(self):
        cmd = ExecutionCommand(command="false")
        result = ExecutionResult(
            command=cmd,
            exit_code=1,
            stdout=b"",
            stderr=b"error",
            start_time="2026-09-14T00:00:00Z",
            end_time="2026-09-14T00:00:01Z",
            termination_status="nonzero_exit",
            timeout_applied=False,
        )
        assert not result.succeeded
        assert result.failed

    def test_timeout_execution(self):
        cmd = ExecutionCommand(command="sleep", arguments=("100",), timeout_seconds=1)
        result = ExecutionResult(
            command=cmd,
            exit_code=None,
            stdout=b"",
            stderr=b"timeout",
            start_time="2026-09-14T00:00:00Z",
            end_time="2026-09-14T00:00:01Z",
            termination_status="timeout",
            timeout_applied=True,
            timeout_duration=1,
        )
        assert result.timed_out
        assert not result.succeeded


# ---------------------------------------------------------------------------
# StagedSource tests
# ---------------------------------------------------------------------------

class TestStagedSource:
    def test_valid_staged_source(self):
        staged = StagedSource(
            source_id="src-001",
            original_path="/source",
            staged_path="/workspace/source",
            original_hash="abc123",
            staged_hash="abc123",
        )
        assert staged.verify_integrity()

    def test_integrity_mismatch(self):
        staged = StagedSource(
            source_id="src-001",
            original_path="/source",
            staged_path="/workspace/source",
            original_hash="abc123",
            staged_hash="def456",
        )
        assert not staged.verify_integrity()


# ---------------------------------------------------------------------------
# ExecutionEnvironment tests
# ---------------------------------------------------------------------------

class TestExecutionEnvironment:
    def test_valid_environment(self):
        env = ExecutionEnvironment(
            policies=frozenset({
                ExecutionPolicy.CONTAINER_PER_EXECUTION,
                ExecutionPolicy.READ_ONLY_SOURCE,
                ExecutionPolicy.NO_NETWORK,
                ExecutionPolicy.RESOURCE_LIMITS,
            }),
            resource_limits=ResourceLimits(),
            filesystem_policy=FilesystemPolicy(),
            network_policy=NetworkPolicy(enabled=False),
        )
        violations = env.validate()
        assert len(violations) == 0

    def test_invalid_network_enabled(self):
        env = ExecutionEnvironment(
            policies=frozenset({
                ExecutionPolicy.CONTAINER_PER_EXECUTION,
                ExecutionPolicy.READ_ONLY_SOURCE,
                ExecutionPolicy.NO_NETWORK,
                ExecutionPolicy.RESOURCE_LIMITS,
            }),
            resource_limits=ResourceLimits(),
            filesystem_policy=FilesystemPolicy(),
            network_policy=NetworkPolicy(enabled=True, allowed_hosts=("example.com",)),
        )
        violations = env.validate()
        assert len(violations) > 0


# ---------------------------------------------------------------------------
# ExecutionEngine tests
# ---------------------------------------------------------------------------

class TestExecutionEngine:
    def test_valid_engine(self):
        env = ExecutionEnvironment(
            policies=frozenset({
                ExecutionPolicy.CONTAINER_PER_EXECUTION,
                ExecutionPolicy.READ_ONLY_SOURCE,
                ExecutionPolicy.NO_NETWORK,
                ExecutionPolicy.RESOURCE_LIMITS,
            }),
            resource_limits=ResourceLimits(),
            filesystem_policy=FilesystemPolicy(),
            network_policy=NetworkPolicy(enabled=False),
        )
        engine = ExecutionEngine(environment=env)
        assert engine.validate_environment()

    def test_record_execution(self):
        env = ExecutionEnvironment(
            policies=frozenset({
                ExecutionPolicy.CONTAINER_PER_EXECUTION,
                ExecutionPolicy.READ_ONLY_SOURCE,
                ExecutionPolicy.NO_NETWORK,
                ExecutionPolicy.RESOURCE_LIMITS,
            }),
            resource_limits=ResourceLimits(),
            filesystem_policy=FilesystemPolicy(),
            network_policy=NetworkPolicy(enabled=False),
        )
        engine = ExecutionEngine(environment=env)
        cmd = ExecutionCommand(command="echo", arguments=("test",))
        result = ExecutionResult(
            command=cmd,
            exit_code=0,
            stdout=b"test\n",
            stderr=b"",
            start_time="2026-09-14T00:00:00Z",
            end_time="2026-09-14T00:00:01Z",
            termination_status="normal",
            timeout_applied=False,
        )
        engine.record_execution(result)
        assert len(engine.get_executions()) == 1

    def test_clear_executions(self):
        env = ExecutionEnvironment(
            policies=frozenset({
                ExecutionPolicy.CONTAINER_PER_EXECUTION,
                ExecutionPolicy.READ_ONLY_SOURCE,
                ExecutionPolicy.NO_NETWORK,
                ExecutionPolicy.RESOURCE_LIMITS,
            }),
            resource_limits=ResourceLimits(),
            filesystem_policy=FilesystemPolicy(),
            network_policy=NetworkPolicy(enabled=False),
        )
        engine = ExecutionEngine(environment=env)
        cmd = ExecutionCommand(command="echo", arguments=("test",))
        result = ExecutionResult(
            command=cmd,
            exit_code=0,
            stdout=b"test\n",
            stderr=b"",
            start_time="2026-09-14T00:00:00Z",
            end_time="2026-09-14T00:00:01Z",
            termination_status="normal",
            timeout_applied=False,
        )
        engine.record_execution(result)
        engine.clear_executions()
        assert len(engine.get_executions()) == 0
