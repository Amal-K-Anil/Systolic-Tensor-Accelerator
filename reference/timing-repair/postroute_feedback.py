import fnmatch
import os
import pathlib
import shutil
import subprocess
from typing import Optional, Tuple

from ..common import Path as LLPath
from ..common import DRC as DRCObject
from ..common import get_script_dir
from ..config import Variable
from ..state import DesignFormat, State
from ..logging import info, warn

from .openroad import DetailedRouting, RCX
from .common_variables import dpl_variables
from .step import (
    MetricsUpdate,
    Step,
    StepError,
    ViewsUpdate,
)


def _merge_config_vars(*groups):
    result = []
    seen = set()

    for group in groups:
        for var in group:
            if var.name in seen:
                continue

            seen.add(var.name)
            result.append(var)

    return result


def _find_env_file(directory: pathlib.Path) -> pathlib.Path:
    exact = directory / "_env.tcl"

    if exact.is_file():
        return exact

    candidates = sorted(directory.glob("_env*.tcl"))

    if not candidates:
        raise StepError(
            f"No LibreLane environment file found in '{directory}'."
        )

    return candidates[0]


def _write_list_file(path: pathlib.Path, values):
    with path.open("w", encoding="utf8") as f:
        for value in values:
            f.write(f"{value}\n")


@Step.factory.register()
class DetailedRoutingWithSlewFeedback(DetailedRouting):
    """
    Detailed routing followed by an extracted-RC max-slew feedback loop.

    The feedback algorithm does not contain synthesized instance names.
    Repair decisions are generated dynamically from the routed design.
    """

    id = "OpenROAD.DetailedRoutingWithSlewFeedback"
    name = "Detailed Routing + Extracted-RC Slew Feedback"

    config_vars = _merge_config_vars(
        DetailedRouting.config_vars,
        RCX.config_vars,
        dpl_variables,
        [
            Variable(
                "POST_ROUTE_SLEW_FEEDBACK",
                bool,
                "Enable extracted-RC post-route slew feedback.",
                default=True,
            ),
            Variable(
                "POST_ROUTE_SLEW_CORNER",
                Optional[str],
                "STA corner used by the extracted-RC slew feedback loop.",
                default=None,
            ),
            Variable(
                "POST_ROUTE_SLEW_MAX_ITERATIONS",
                int,
                "Maximum number of post-route repair/reroute iterations.",
                default=8,
            ),
            Variable(
                "POST_ROUTE_SLEW_SDC_FILE",
                Optional[LLPath],
                "Optional SDC used by the feedback STA. "
                "If unset, PNR_SDC_FILE/FALLBACK_SDC is used.",
                default=None,
            ),
        ],
    )

    def _get_corner_libs(self, corner: str):
        _, libs, _, _ = self.toolbox.get_timing_files_categorized(
            self.config,
            timing_corner=corner,
        )

        return [str(lib) for lib in libs]

    def _find_rcx_configuration(self, target_corner: str):
        rulesets = self.config["RCX_RULESETS"]

        matched_pattern = None
        matched_ruleset = None

        # Prefer an exact match if one exists.
        if target_corner in rulesets:
            matched_pattern = target_corner
            matched_ruleset = rulesets[target_corner]
        else:
            for pattern, ruleset in rulesets.items():
                if fnmatch.fnmatchcase(target_corner, pattern):
                    matched_pattern = pattern
                    matched_ruleset = ruleset
                    break

        if matched_pattern is None or matched_ruleset is None:
            raise StepError(
                f"No RCX ruleset matches feedback corner "
                f"'{target_corner}'."
            )

        tech_lefs = self.toolbox.filter_views(
            self.config,
            self.config["TECH_LEFS"],
            matched_pattern,
        )

        if len(tech_lefs) < 1:
            raise StepError(
                f"No technology LEF matches RCX corner "
                f"'{matched_pattern}'."
            )

        return (
            matched_pattern,
            str(matched_ruleset),
            str(tech_lefs[0]),
        )

    def _run_seed_rcx(
        self,
        drt_env: pathlib.Path,
        seed_def: pathlib.Path,
        feedback_dir: pathlib.Path,
        rcx_ruleset: str,
        rcx_lef: str,
        timing_corner: str,
        timing_libs,
    ) -> Tuple[pathlib.Path, pathlib.Path]:
        rcx_dir = feedback_dir / "seed_rcx_max"
        rcx_dir.mkdir(parents=True, exist_ok=True)

        scripts_dir = pathlib.Path(get_script_dir())

        base_env = feedback_dir / "max_rcx_base_env.tcl"

        with base_env.open("w", encoding="utf8") as f:
            f.write(f'source {{{drt_env}}}\n')
            f.write(f'set ::env(RCX_LEF) {{{rcx_lef}}}\n')
            f.write(f'set ::env(RCX_RULESET) {{{rcx_ruleset}}}\n')

            f.write(
                'set ::env(_LIB_CORNER_0) [list '
                f'{{{timing_corner}}}'
            )
            for lib in timing_libs:
                f.write(f' {{{lib}}}')
            f.write(']\n')

            f.write(
                "set ::env(RCX_MERGE_VIA_WIRE_RES) "
                f"{1 if self.config['RCX_MERGE_VIA_WIRE_RES'] else 0}\n"
            )

        seed_spef = rcx_dir / (
            f"{self.config['DESIGN_NAME']}.max.spef"
        )

        seed_env = rcx_dir / "env.tcl"

        with seed_env.open("w", encoding="utf8") as f:
            f.write(f'source {{{base_env}}}\n')
            f.write(f'set ::env(CURRENT_DEF) {{{seed_def}}}\n')
            f.write(f'set ::env(STEP_DIR) {{{rcx_dir}}}\n')
            f.write(
                'unset -nocomplain ::env(SAVE_ODB)\n'
            )
            f.write(
                'unset -nocomplain ::env(SAVE_DEF)\n'
            )
            f.write(
                'unset -nocomplain ::env(SAVE_NL)\n'
            )
            f.write(
                'unset -nocomplain ::env(SAVE_PNL)\n'
            )
            f.write(
                'unset -nocomplain ::env(SAVE_LOGICAL_NL)\n'
            )
            f.write(
                'unset -nocomplain ::env(SAVE_LOGICAL_PNL)\n'
            )
            f.write(
                'unset -nocomplain ::env(SAVE_SDC)\n'
            )
            f.write(
                'unset -nocomplain ::env(SAVE_SDF)\n'
            )
            f.write(
                'unset -nocomplain ::env(SAVE_SDF_PNL)\n'
            )
            f.write(
                'unset -nocomplain ::env(SAVE_OPENROAD_LEF)\n'
            )
            f.write(
                'unset -nocomplain ::env(SAVE_GUIDE)\n'
            )
            f.write(
                f'set ::env(SAVE_SPEF) {{{seed_spef}}}\n'
            )

        runner = rcx_dir / "run.tcl"

        with runner.open("w", encoding="utf8") as f:
            f.write(
                f'set ::env(SCRIPTS_DIR) {{{scripts_dir}}}\n'
            )
            f.write(
                f'set ::env(_TCL_ENV_IN) {{{seed_env}}}\n'
            )
            f.write(
                f'source {{{scripts_dir / "openroad" / "rcx.tcl"}}}\n'
            )

        log_path = rcx_dir / "rcx.log"

        with log_path.open("w", encoding="utf8") as log:
            result = subprocess.run(
                [
                    "openroad",
                    "-exit",
                    "-no_splash",
                    str(runner),
                ],
                cwd=str(rcx_dir),
                env=os.environ.copy(),
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )

        if result.returncode != 0:
            raise StepError(
                "Initial MAX RC extraction for post-route slew "
                f"feedback failed. See '{log_path}'."
            )

        if not seed_spef.is_file():
            raise StepError(
                f"MAX RCX completed but SPEF was not produced: "
                f"'{seed_spef}'."
            )

        return seed_spef, base_env

    def run(
        self,
        state_in: State,
        **kwargs,
    ) -> Tuple[ViewsUpdate, MetricsUpdate]:
        # The incoming ODB is our clean pre-DRT replay checkpoint.
        base_odb_raw = state_in[DesignFormat.ODB]

        if base_odb_raw is None:
            raise StepError(
                "Detailed-routing feedback requires an incoming ODB."
            )

        base_odb = pathlib.Path(str(base_odb_raw))
        base_env = _find_env_file(base_odb.parent)

        #
        # 1. Run the normal LibreLane DetailedRouting step first.
        #
        views_updates, metrics_updates = super().run(
            state_in,
            **kwargs,
        )

        if not self.config["POST_ROUTE_SLEW_FEEDBACK"]:
            return views_updates, metrics_updates

        target_corner = self.config[
            "POST_ROUTE_SLEW_CORNER"
        ]

        if target_corner is None:
            raise StepError(
                "POST_ROUTE_SLEW_FEEDBACK is enabled but "
                "POST_ROUTE_SLEW_CORNER is not set."
            )

        seed_odb_raw = views_updates.get(DesignFormat.ODB)
        seed_def_raw = views_updates.get(DesignFormat.DEF)

        if seed_odb_raw is None or seed_def_raw is None:
            raise StepError(
                "Normal DetailedRouting did not produce both "
                "ODB and DEF outputs."
            )

        seed_odb = pathlib.Path(str(seed_odb_raw))
        seed_def = pathlib.Path(str(seed_def_raw))

        drt_env = _find_env_file(
            pathlib.Path(self.step_dir)
        )

        feedback_dir = (
            pathlib.Path(self.step_dir) / "slew_feedback"
        )

        if feedback_dir.exists():
            shutil.rmtree(feedback_dir)

        feedback_dir.mkdir(parents=True)

        #
        # 2. Resolve PNR and feedback corner libraries dynamically.
        #
        pnr_corners = self.config["PNR_CORNERS"]

        if pnr_corners:
            pnr_corner = pnr_corners[0]
        else:
            pnr_corner = self.config["DEFAULT_CORNER"]

        pnr_libs = self._get_corner_libs(pnr_corner)
        target_libs = self._get_corner_libs(target_corner)

        if not pnr_libs:
            raise StepError(
                f"No libraries found for PNR corner "
                f"'{pnr_corner}'."
            )

        if not target_libs:
            raise StepError(
                f"No libraries found for feedback corner "
                f"'{target_corner}'."
            )

        pnr_libs_file = feedback_dir / "pnr_libs.txt"
        target_libs_file = (
            feedback_dir / "feedback_corner_libs.txt"
        )

        _write_list_file(pnr_libs_file, pnr_libs)
        _write_list_file(target_libs_file, target_libs)

        #
        # 3. Determine which RCX ruleset corresponds to the
        #    selected timing corner.
        #
        (
            rcx_pattern,
            rcx_ruleset,
            rcx_lef,
        ) = self._find_rcx_configuration(target_corner)

        info(
            f"Post-route slew feedback corner: {target_corner}; "
            f"RCX pattern: {rcx_pattern}"
        )

        #
        # 4. Produce the initial MAX extracted SPEF from the
        #    normal DetailedRouting output.
        #
        seed_spef, max_rcx_base_env = self._run_seed_rcx(
            drt_env,
            seed_def,
            feedback_dir,
            rcx_ruleset,
            rcx_lef,
            target_corner,
            target_libs,
        )

        #
        # 5. Build a signoff-style STA base environment.
        #
        scripts_dir = pathlib.Path(get_script_dir())

        feedback_sdc = (
            self.config["POST_ROUTE_SLEW_SDC_FILE"]
            or self.config["PNR_SDC_FILE"]
            or self.config["FALLBACK_SDC"]
        )

        maxss_base_env = (
            feedback_dir / "feedback_sta_base_env.tcl"
        )

        with maxss_base_env.open(
            "w",
            encoding="utf8",
        ) as f:
            f.write(f'source {{{drt_env}}}\n')
            f.write(
                'set ::env(OPENLANE_SDC_IDEAL_CLOCKS) 0\n'
            )
            f.write(
                f'set ::env(_SDC_IN) {{{feedback_sdc}}}\n'
            )

        #
        # 6. Invoke the already-proven generic feedback engine.
        #
        controller = (
            scripts_dir
            / "openroad"
            / "postroute_slew_feedback"
            / "run_feedback.sh"
        )

        if not controller.is_file():
            raise StepError(
                f"Feedback controller not found: '{controller}'."
            )

        controller_work = feedback_dir / "iterations"

        controller_env = os.environ.copy()

        controller_env.update(
            {
                "SCRIPTS_DIR": str(scripts_dir),
                "FB_BASE_ODB": str(base_odb),
                "FB_PNR_ENV": str(drt_env),
                "FB_DRT_ENV": str(drt_env),
                "FB_MAX_RCX_ENV": str(
                    max_rcx_base_env
                ),
                "FB_MAXSS_ENV": str(maxss_base_env),
                "FB_PNR_CORNER": str(pnr_corner),
                "FB_CORNER": str(target_corner),
                "FB_PNR_LIBS_FILE": str(
                    pnr_libs_file
                ),
                "FB_MAXSS_LIBS_FILE": str(
                    target_libs_file
                ),
                "FB_SDC": str(feedback_sdc),
                "FB_WORK_DIR": str(controller_work),
                "FB_MAX_ITERATIONS": str(
                    self.config[
                        "POST_ROUTE_SLEW_MAX_ITERATIONS"
                    ]
                ),
                "FB_SEED_DRT_ODB": str(seed_odb),
                "FB_SEED_DRT_DEF": str(seed_def),
                "FB_SEED_MAX_SPEF": str(seed_spef),
            }
        )

        # Forward LibreLane's PNR exclusion list to the generic
        # feedback controller. write_verilog and repair/replay stages
        # expect _PNR_EXCLUDED_CELLS to be populated.
        pnr_excluded_file = self.config.get(
            "PNR_EXCLUDED_CELL_FILE"
        )

        if pnr_excluded_file is not None:
            controller_env[
                "FB_PNR_EXCLUDED_CELLS_FILE"
            ] = str(pnr_excluded_file)

        # Replay performs detailed-placement legalization, so its
        # OpenROAD subprocesses need LibreLane's resolved DPL settings.
        controller_env["DPL_CELL_PADDING"] = str(
            self.config["DPL_CELL_PADDING"]
        )
        controller_env["PL_MAX_DISPLACEMENT_X"] = str(
            self.config["PL_MAX_DISPLACEMENT_X"]
        )
        controller_env["PL_MAX_DISPLACEMENT_Y"] = str(
            self.config["PL_MAX_DISPLACEMENT_Y"]
        )

        controller_log = (
            feedback_dir / "feedback.log"
        )

        info(
            "Starting extracted-RC post-route slew feedback…"
        )

        with controller_log.open(
            "w",
            encoding="utf8",
        ) as log:
            result = subprocess.run(
                [str(controller)],
                cwd=str(feedback_dir),
                env=controller_env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )

        if result.returncode != 0:
            raise StepError(
                "Post-route slew feedback failed with "
                f"exit code {result.returncode}. "
                f"See '{controller_log}'."
            )

        result_env = controller_work / "result.env"

        if not result_env.is_file():
            raise StepError(
                "Feedback controller exited successfully but "
                f"did not produce '{result_env}'."
            )

        feedback_result = {}

        with result_env.open(
            encoding="utf8",
        ) as f:
            for line in f:
                line = line.strip()

                if not line or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                feedback_result[key] = value

        if feedback_result.get("FB_RESULT") != "success":
            raise StepError(
                "Feedback controller did not report success."
            )

        final_odb = pathlib.Path(
            feedback_result["FB_FINAL_ODB"]
        )
        final_def = pathlib.Path(
            feedback_result["FB_FINAL_DEF"]
        )

        if not final_odb.is_file():
            raise StepError(
                f"Final feedback ODB missing: '{final_odb}'."
            )

        if not final_def.is_file():
            raise StepError(
                f"Final feedback DEF missing: '{final_def}'."
            )

        #
        # 7. Replace the original DetailedRouting output views
        #    with the converged versions. Downstream LibreLane
        #    steps therefore see the repaired routed design.
        #
        final_views_dir = feedback_dir / "final"
        final_views_dir.mkdir(parents=True, exist_ok=True)

        final_output_odb = (
            final_views_dir
            / f"{self.config['DESIGN_NAME']}.odb"
        )
        final_output_def = (
            final_views_dir
            / f"{self.config['DESIGN_NAME']}.def"
        )

        shutil.copy2(final_odb, final_output_odb)
        shutil.copy2(final_def, final_output_def)

        views_updates[DesignFormat.ODB] = LLPath(
            str(final_output_odb)
        )
        views_updates[DesignFormat.DEF] = LLPath(
            str(final_output_def)
        )

        #
        # Also replace the final DRT report with the report from
        # the converged routing iteration where available.
        #
        final_drt_dir = final_odb.parent

        for source in final_drt_dir.glob("*.drc"):
            destination = (
                pathlib.Path(self.step_dir) / source.name
            )

            shutil.copy2(source, destination)

            try:
                drc, _ = DRCObject.from_openroad(
                    open(
                        destination,
                        encoding="utf8",
                    ),
                    self.config["DESIGN_NAME"],
                )

                with open(
                    pathlib.Path(str(destination) + ".xml"),
                    "wb",
                ) as xml:
                    drc.to_klayout_xml(xml)

            except Exception as error:
                warn(
                    "Could not regenerate DRC XML from "
                    f"feedback result: {error}"
                )

        info(
            "Post-route slew feedback converged: "
            f"iterations="
            f"{feedback_result.get('FB_ITERATIONS')}, "
            f"slew="
            f"{feedback_result.get('FB_FINAL_SLEW_COUNT')}, "
            f"cap="
            f"{feedback_result.get('FB_FINAL_CAP_COUNT')}, "
            f"setup_ws="
            f"{feedback_result.get('FB_FINAL_SETUP_WS')}, "
            f"hold_ws="
            f"{feedback_result.get('FB_FINAL_HOLD_WS')}."
        )

        return views_updates, metrics_updates
