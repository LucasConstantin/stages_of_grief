#!/usr/bin/env python3
"""stages_of_grief - a minimal hybrid-simulation pipeline runner.

Reads a run configuration (YAML) describing a sequence of stages
(executables/codes) and runs them one after another, feeding the output
of each stage as the input of the next one. This is typically used to
chain together the individual codes of a heavy-ion collision hybrid
simulation (e.g. initial conditions -> hydro -> particlization ->
hadronic transport).
"""

import argparse
import logging
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("stages_of_grief")


class Stage:
    """A single step of the hybrid simulation pipeline."""

    def __init__(
        self,
        name,
        executable_path,
        run_command,
        config_path=None,
        input_files=None,
        output=None,
        workdir=None,
        base_dir=None,
    ):
        self.name = name
        self.run_command = run_command
        base_dir = Path(base_dir) if base_dir else Path.cwd()
        # Resolve all paths to absolute ones (relative to the run config's
        # directory) up-front, since stages are executed with their cwd set
        # to their own workdir, which would otherwise break relative paths.
        self.executable_path = str((base_dir / executable_path).resolve())
        self.config_path = (
            str((base_dir / config_path).resolve()) if config_path else None
        )
        # input_files may be explicitly set in the config, or filled in
        # automatically with the previous stage's output.
        self.input_files = (
            [str((base_dir / f).resolve()) for f in input_files] if input_files else []
        )
        self.workdir = Path(workdir).resolve() if workdir else Path.cwd()
        self.output = str((self.workdir / output).resolve()) if output else None

    @classmethod
    def from_dict(cls, name, data, base_dir=None):
        required = ("executable_path", "run_command")
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(
                f"Stage '{name}' is missing required field(s): {', '.join(missing)}"
            )
        return cls(
            name=name,
            executable_path=data["executable_path"],
            run_command=data["run_command"],
            config_path=data.get("config_path"),
            input_files=data.get("input_files"),
            output=data.get("output"),
            workdir=data.get("workdir"),
            base_dir=base_dir,
        )

    def build_command(self):
        """Fill the run_command template with the stage's paths."""
        inputs = " ".join(str(f) for f in self.input_files)
        placeholders = {
            "executable": self.executable_path,
            "config": self.config_path or "",
            "input": inputs,
            "output": self.output or "",
        }
        try:
            command = self.run_command.format(**placeholders)
        except KeyError as exc:
            raise ValueError(
                f"Stage '{self.name}': unknown placeholder {exc} in run_command"
            ) from exc
        return shlex.split(command)

    def run(self):
        """Execute the stage. Raises RuntimeError on failure."""
        self.workdir.mkdir(parents=True, exist_ok=True)
        command = self.build_command()
        logger.info("Running stage '%s': %s", self.name, " ".join(command))

        result = subprocess.run(command, cwd=self.workdir)
        if result.returncode != 0:
            raise RuntimeError(
                f"Stage '{self.name}' failed with exit code {result.returncode}"
            )
        logger.info("Stage '%s' finished successfully", self.name)


class Pipeline:
    """A sequence of stages, run one after another."""

    def __init__(self, stages):
        self.stages = stages

    @classmethod
    def from_config(cls, config_path):
        config_path = Path(config_path)
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}

        stages_config = config.get("stages", config)
        if not stages_config:
            raise ValueError(f"No stages found in run config '{config_path}'")

        base_dir = config_path.parent.resolve()
        stages = []
        for name, data in stages_config.items():
            if not data:
                raise ValueError(f"Stage '{name}' has no configuration")
            stages.append(Stage.from_dict(name, data, base_dir=base_dir))
        return cls(stages)

    def run(self):
        previous_output = None
        for stage in self.stages:
            if not stage.input_files and previous_output is not None:
                stage.input_files = [previous_output]
            stage.run()
            previous_output = stage.output


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a chain of heavy-ion collision hybrid simulation stages."
    )
    parser.add_argument(
        "run_config",
        nargs="?",
        default="run_config.yaml",
        help="Path to the run configuration YAML file (default: run_config.yaml)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        pipeline = Pipeline.from_config(args.run_config)
        pipeline.run()
    except (ValueError, RuntimeError, OSError) as exc:
        logger.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
