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
import os
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
        output_path=None,
        workdir=None,
        run_from=None,
        base_dir=None,
    ):
        self.name = name
        self.run_command = run_command
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        # Resolve all paths to absolute ones (relative to the run config's
        # directory) up-front, since stages are executed with their cwd set
        # to their own workdir, which would otherwise break relative paths.
        self.executable_path = str((self.base_dir / executable_path).resolve())
        self.config_path = (
            str((self.base_dir / config_path).resolve()) if config_path else None
        )
        # input_files entries are interpreted as file names inside the previous
        # stage output directory unless absolute paths are provided.
        self.input_file_specs = [str(f) for f in input_files] if input_files else []
        self.input_files = []
        self.workdir = Path(workdir).resolve() if workdir else Path.cwd()
        self.output_path = str((self.workdir / output_path).resolve()) if output_path else None
        self.run_from = self._resolve_run_from(run_from)

    @classmethod
    def from_dict(cls, name, data, workdir, base_dir=None):
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
            output_path=data.get("output_path"),
            workdir=workdir,
            run_from=data.get("run_from"),
            base_dir=base_dir,
        )

    def _resolve_run_from(self, run_from):
        if run_from in (None, "", "workdir"):
            return self.workdir
        if run_from == "executable_dir":
            return Path(self.executable_path).resolve().parent
        return (self.base_dir / run_from).resolve()

    def resolve_inputs(self, previous_output_dir):
        """Resolve stage inputs using previous stage output directory."""
        if previous_output_dir is None:
            self.input_files = [
                str((self.base_dir / Path(spec)).resolve())
                if not Path(spec).is_absolute()
                else str(Path(spec))
                for spec in self.input_file_specs
            ]
            return

        if not self.input_file_specs:
            self.input_files = [str(previous_output_dir)]
            return

        resolved_inputs = []
        for spec in self.input_file_specs:
            input_path = Path(spec)
            if input_path.is_absolute():
                resolved_inputs.append(str(input_path))
            else:
                resolved_inputs.append(str((previous_output_dir / input_path).resolve()))
        self.input_files = resolved_inputs

    def build_command(self):
        """Fill the run_command template with the stage's paths."""
        inputs = " ".join(str(f) for f in self.input_files)
        placeholders = {
            "executable": self.executable_path,
            "config": self.config_path or "",
            "input": inputs,
            "output_path": self.output_path or "",
            "workdir": self.base_dir,
        }
        print(self.base_dir)
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
        print(command)
        result = subprocess.run(command, cwd=self.run_from)
        if result.returncode != 0:
            raise RuntimeError(
                f"Stage '{self.name}' failed with exit code {result.returncode}"
            )
        logger.info("Stage '%s' finished successfully", self.name)


class Pipeline:
    """A sequence of stages, run one after another."""

    def __init__(self, stages, workdir):
        self.stages = stages
        self.workdir = workdir

    @classmethod
    def from_config(cls, config_path, run_id=None):
        config_path = Path(config_path)
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}

        stages_config = config.get("stages", config)
        if not stages_config:
            raise ValueError(f"No stages found in run config '{config_path}'")

        base_dir = config_path.parent.resolve()
        pipeline_workdir = (base_dir / config.get("workdir", "work")).resolve()
        if run_id:
            pipeline_workdir = pipeline_workdir / str(run_id)
        stages = []
        for name, data in stages_config.items():
            if not data:
                raise ValueError(f"Stage '{name}' has no configuration")
            stages.append(
                Stage.from_dict(name, data, workdir=pipeline_workdir, base_dir=base_dir)
            )
        return cls(stages, pipeline_workdir)

    def run(self):
        self.workdir.mkdir(parents=True, exist_ok=True)
        previous_output_dir = None
        for stage in self.stages:
            stage.resolve_inputs(previous_output_dir)
            stage.run()
            previous_output_dir = Path(stage.output_path).resolve() if stage.output_path else None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a chain of heavy-ion collision hybrid simulation stages."
    )
    parser.add_argument(
        "--run_config",
        nargs="?",
        default="run_config.yaml",
        help="Path to the run configuration YAML file (default: run_config.yaml)",
    )
    parser.add_argument("--run_id",
        default="0",
        help="Run ID (default: 0). All stage files and subdirectories are "
        "placed inside a subfolder named after this ID within the "
        "configured workdir.",
    )

    
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        pipeline = Pipeline.from_config(args.run_config, run_id=args.run_id)
        pipeline.run()
    except (ValueError, RuntimeError, OSError) as exc:
        logger.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
