import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional, Iterable, Sequence, List

from .build_config import (
    BuildConfig,
    BuildConfigItem,
    find_python_packages_build_config_items,
)
from .utils import open_modifiable_json, find_js_module_exports

from idom.cli import console


APP_DIR = Path(__file__).parent / "app"
BUILD_DIR = APP_DIR / "build"
_BUILD_CONFIG: Optional[BuildConfig] = None


def build_config() -> BuildConfig:
    global _BUILD_CONFIG
    if _BUILD_CONFIG is None:
        _BUILD_CONFIG = BuildConfig(BUILD_DIR)
    return _BUILD_CONFIG


def web_module_exports(source_name: str, package_name: str) -> List[str]:
    dep_alias = build_config().get_js_dependency_alias(source_name, package_name)
    if dep_alias is None:
        return []
    module_file = find_client_build_path(f"web_modules/{dep_alias}.js")
    if module_file is None:
        return []
    return find_js_module_exports(module_file)


def web_module_url(source_name: str, package_name: str) -> Optional[str]:
    dep_alias = build_config().get_js_dependency_alias(source_name, package_name)
    if dep_alias is None:
        return None
    if find_client_build_path(f"web_modules/{dep_alias}.js") is None:
        return None
    # need to go back a level since the JS that import this is in `core_components`
    return f"../web_modules/{dep_alias}.js"


def find_client_build_path(rel_path: str) -> Optional[Path]:
    if rel_path.startswith("/"):
        raise ValueError(f"{rel_path!r} is not a relative path")
    builtin_path = BUILD_DIR.joinpath(*rel_path.split("/"))
    if builtin_path.exists():
        return builtin_path
    else:
        return None


def build(config_items: Iterable[BuildConfigItem] = ()) -> None:
    config = build_config()

    with config.transaction():
        config.update_config_items(config_items)

        with console.spinner("Discovering dependencies"):
            configs, errors = find_python_packages_build_config_items()
            for e in errors:
                console.echo(f"{e} because {e.__cause__}", color="red")
            config.update_config_items(configs)

    with TemporaryDirectory() as tempdir:
        tempdir_path = Path(tempdir)
        temp_app_dir = tempdir_path / "app"
        temp_build_dir = temp_app_dir / "build"
        package_json_path = temp_app_dir / "package.json"

        # copy over the whole APP_DIR directory into the temp one
        shutil.copytree(APP_DIR, temp_app_dir, symlinks=True)

        packages_to_install = config.all_aliased_js_dependencies()

        with open_modifiable_json(package_json_path) as package_json:
            snowpack_config = package_json.setdefault("snowpack", {})
            snowpack_config.setdefault("install", []).extend(
                config.all_js_dependency_aliases()
            )

        with console.spinner(
            f"Installing {len(packages_to_install)} dependencies"
            if packages_to_install
            else "Installing dependencies"
        ):
            _npm_install(packages_to_install, temp_app_dir)

        with console.spinner("Building client"):
            _npm_run_build(temp_app_dir)

        if BUILD_DIR.exists():
            shutil.rmtree(BUILD_DIR)

        shutil.copytree(temp_build_dir, BUILD_DIR, symlinks=True)


def restore() -> None:
    with console.spinner("Restoring"):
        shutil.rmtree(BUILD_DIR)
        _run_subprocess(["npm", "install"], APP_DIR)
        _run_subprocess(["npm", "run", "build"], APP_DIR)


def _npm_install(packages: Sequence[str], cwd: Path) -> None:
    _run_subprocess(["npm", "install"] + packages, cwd)


def _npm_run_build(cwd: Path):
    _run_subprocess(["npm", "run", "build"], cwd)


def _run_subprocess(args: List[str], cwd: Path) -> None:
    try:
        subprocess.run(
            args, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as error:
        raise subprocess.SubprocessError(error.stderr.decode()) from error
    return None
