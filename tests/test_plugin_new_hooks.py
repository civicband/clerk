"""Tests for new plugin hooks added in PR #101."""

import click
import pluggy

from clerk.hookspecs import ClerkSpec, hookimpl


class TestNewPluginHooks:
    """Tests for the new plugin hooks."""

    def test_register_cli_commands(self):
        """Test registering CLI commands through plugins."""

        class CliPlugin:
            @hookimpl
            def register_cli_commands(self):
                @click.command(name="test-command")
                @click.option("--name", default="world")
                def test_cmd(name):
                    """Test command."""
                    click.echo(f"Hello {name}")

                return test_cmd

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(CliPlugin())

        results = pm.hook.register_cli_commands()
        assert len(results) == 1

        # Check that the result is a Click command
        cmd = results[0]
        assert isinstance(cmd, click.Command)
        assert cmd.name == "test-command"

    def test_register_cli_group(self):
        """Test registering CLI command groups through plugins."""

        class CliGroupPlugin:
            @hookimpl
            def register_cli_commands(self):
                @click.group(name="finance")
                def finance_group():
                    """Finance commands."""
                    pass

                @finance_group.command(name="import")
                @click.argument("source")
                def import_cmd(source):
                    """Import finance data."""
                    click.echo(f"Importing from {source}")

                return finance_group

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(CliGroupPlugin())

        results = pm.hook.register_cli_commands()
        assert len(results) == 1

        # Check that the result is a Click group
        group = results[0]
        assert isinstance(group, click.Group)
        assert group.name == "finance"

    def test_register_job_types(self):
        """Test registering job types through plugins."""

        def finance_etl_job(job_data):
            """Process finance ETL job."""
            return f"Processing finance data for {job_data['site']}"

        def finance_report_job(job_data):
            """Generate finance report."""
            return f"Generating report for {job_data['period']}"

        class JobTypePlugin:
            @hookimpl
            def register_job_types(self):
                return {
                    "finance-etl": finance_etl_job,
                    "finance-report": finance_report_job,
                }

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(JobTypePlugin())

        results = pm.hook.register_job_types()
        assert len(results) == 1

        job_types = results[0]
        assert "finance-etl" in job_types
        assert "finance-report" in job_types
        assert callable(job_types["finance-etl"])
        assert callable(job_types["finance-report"])

    def test_multiple_plugins_register_job_types(self):
        """Test multiple plugins registering job types."""

        class FinancePlugin:
            @hookimpl
            def register_job_types(self):
                return {"finance-etl": lambda x: "finance"}

        class ElectionPlugin:
            @hookimpl
            def register_job_types(self):
                return {"election-import": lambda x: "election"}

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(FinancePlugin())
        pm.register(ElectionPlugin())

        results = pm.hook.register_job_types()
        assert len(results) == 2

        # Merge all job types
        all_job_types = {}
        for job_types in results:
            all_job_types.update(job_types)

        assert "finance-etl" in all_job_types
        assert "election-import" in all_job_types

    def test_get_data_processors(self):
        """Test getting data processors for different data types."""

        class FinanceProcessor:
            def process(self, data):
                return f"Processing finance: {data}"

        class ElectionProcessor:
            def process(self, data):
                return f"Processing election: {data}"

        class ProcessorPlugin:
            @hookimpl
            def get_data_processors(self, data_type):
                if data_type == "finance":
                    return FinanceProcessor
                elif data_type == "election":
                    return ElectionProcessor
                return None

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(ProcessorPlugin())

        # Test getting finance processor
        results = pm.hook.get_data_processors(data_type="finance")
        assert len(results) == 1
        assert results[0] == FinanceProcessor

        # Test getting election processor
        results = pm.hook.get_data_processors(data_type="election")
        assert len(results) == 1
        assert results[0] == ElectionProcessor

        # Test unknown data type - pluggy filters out None results
        results = pm.hook.get_data_processors(data_type="unknown")
        assert results == []  # Pluggy filters out None results

    def test_compilation_hooks(self):
        """Test pre and post compilation hooks."""

        class CompilationTracker:
            def __init__(self):
                self.events = []

        tracker = CompilationTracker()

        class CompilationPlugin:
            @hookimpl
            def pre_compilation(self, subdomain, run_id):
                tracker.events.append(("pre", subdomain, run_id))

            @hookimpl
            def post_compilation(self, subdomain, database_path, run_id):
                tracker.events.append(("post", subdomain, database_path, run_id))

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(CompilationPlugin())

        # Simulate compilation workflow
        pm.hook.pre_compilation(subdomain="oakland", run_id="run-123")
        pm.hook.post_compilation(
            subdomain="oakland", database_path="/data/oakland.db", run_id="run-123"
        )

        assert len(tracker.events) == 2
        assert tracker.events[0] == ("pre", "oakland", "run-123")
        assert tracker.events[1] == ("post", "oakland", "/data/oakland.db", "run-123")

    def test_register_worker_functions(self):
        """Test registering worker functions through plugins."""

        def finance_worker(queue_name):
            """Finance worker function."""
            return f"Finance worker for {queue_name}"

        def election_worker(queue_name):
            """Election worker function."""
            return f"Election worker for {queue_name}"

        class WorkerPlugin:
            @hookimpl
            def register_worker_functions(self):
                return {
                    "finance": {
                        "function": finance_worker,
                        "queues": ["finance-high", "finance-low"],
                    },
                    "election": {
                        "function": election_worker,
                        "queues": ["election"],
                    },
                }

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(WorkerPlugin())

        results = pm.hook.register_worker_functions()
        assert len(results) == 1

        worker_funcs = results[0]
        assert "finance" in worker_funcs
        assert "election" in worker_funcs
        assert callable(worker_funcs["finance"]["function"])
        assert worker_funcs["finance"]["queues"] == ["finance-high", "finance-low"]

    def test_empty_plugin_returns(self):
        """Test that plugins can return None or empty values."""

        class EmptyPlugin:
            @hookimpl
            def register_cli_commands(self):
                return None

            @hookimpl
            def register_job_types(self):
                return {}

            @hookimpl
            def get_data_processors(self, data_type):
                return None

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(EmptyPlugin())

        # Should not raise any errors - pluggy filters out None results
        assert pm.hook.register_cli_commands() == []  # None is filtered
        assert pm.hook.register_job_types() == [{}]
        assert pm.hook.get_data_processors(data_type="any") == []  # None is filtered

    def test_multiple_compilation_plugins(self):
        """Test multiple plugins handling compilation hooks."""

        events = []

        class LoggingPlugin:
            @hookimpl
            def pre_compilation(self, subdomain, run_id):
                events.append(f"Logging: Starting {subdomain}")

            @hookimpl
            def post_compilation(self, subdomain, database_path, run_id):
                events.append(f"Logging: Completed {subdomain}")

        class MetricsPlugin:
            @hookimpl
            def pre_compilation(self, subdomain, run_id):
                events.append(f"Metrics: Recording start for {subdomain}")

            @hookimpl
            def post_compilation(self, subdomain, database_path, run_id):
                events.append(f"Metrics: Recording completion for {subdomain}")

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(LoggingPlugin())
        pm.register(MetricsPlugin())

        pm.hook.pre_compilation(subdomain="berkeley", run_id="run-456")
        pm.hook.post_compilation(
            subdomain="berkeley", database_path="/data/berkeley.db", run_id="run-456"
        )

        # Both plugins should have been called
        assert len(events) == 4
        assert "Logging: Starting berkeley" in events
        assert "Metrics: Recording start for berkeley" in events
        assert "Logging: Completed berkeley" in events
        assert "Metrics: Recording completion for berkeley" in events
