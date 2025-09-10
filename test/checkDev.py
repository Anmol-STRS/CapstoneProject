#!/usr/bin/env python3
"""
DevCheck: Enhanced local health test for Python & C++
- Python: venv per project, install requirements.txt, run entry, expect "working"
- C++: find/boot CMake, detect compiler, configure+build (Ninja if present, VS on Windows), run target, expect "Working"

Usage:
  python test/run_dev_check.py
  python test/run_dev_check.py --config devcheck.json --root "C:\\Capstone Project"
  python test/run_dev_check.py --verbose --parallel --timeout 300

Exit code: 0 if all PASS (or SKIP when allowed), 1 if any FAIL.
"""

import argparse
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import stat  # <-- added for Windows read-only fix

# -------------------- Configuration & Data Classes --------------------

@dataclass
class PythonProject:
    path: str
    entry: str = "main.py"
    expect: str = "working"
    requirements: Optional[str] = None
    python_version: Optional[str] = None
    timeout: int = 60

@dataclass
class CppConfig:
    source_dir: str = "scripts"
    build_dir: str = ".devcheck/build"
    target: str = "capstone"
    args: List[str] = None
    force_compiler: Optional[str] = None
    cmake_path: Optional[str] = None
    allow_skip: bool = False
    timeout: int = 300
    build_type: str = "Debug"

    def __post_init__(self):
        if self.args is None:
            self.args = []

@dataclass
class TestResult:
    status: str  # PASS, FAIL, SKIP
    duration: float
    stdout: str = ""
    stderr: str = ""
    error_message: str = ""
    return_code: int = 0

# -------------------- Logging & Output --------------------

class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for different log levels."""
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    def format(self, record):
        if hasattr(record, 'no_color') or not sys.stdout.isatty():
            return super().format(record)
        color = self.COLORS.get(record.levelname, '')
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)

def setup_logging(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger('devcheck')
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = ColoredFormatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

def print_header(title: str, char: str = "=", width: int = 80):
    print(f"\n{char * width}")
    print(f"{title:^{width}}")
    print(f"{char * width}")

# -------------------- Utility Functions --------------------

def which(prog: str) -> Optional[str]:
    result = shutil.which(prog)
    if not result and platform.system() == "Windows" and not prog.endswith('.exe'):
        result = shutil.which(f"{prog}.exe")
    return result

@contextmanager
def timeout_context(seconds: int):
    def timeout_handler():
        raise TimeoutError(f"Operation timed out after {seconds} seconds")
    timer = threading.Timer(seconds, timeout_handler)
    timer.start()
    try:
        yield
    finally:
        timer.cancel()

def run_cmd(args: List[str], cwd: Optional[str] = None, env: Optional[Dict] = None, 
           timeout: int = 300) -> Tuple[int, str, str]:
    logger = logging.getLogger('devcheck')
    logger.debug(f"Running: {' '.join(map(str, args))}")
    if cwd:
        logger.debug(f"Working directory: {cwd}")
    try:
        with timeout_context(timeout):
            p = subprocess.run(
                args, 
                cwd=cwd, 
                env=env, 
                text=True, 
                capture_output=True,
                timeout=timeout
            )
            return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout} seconds"
    except Exception as e:
        return -1, "", str(e)

def load_config(cfg_path: Path) -> Dict:
    if not cfg_path.exists():
        return {}
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            config = json.load(f)
        if 'python_projects' in config:
            projects = []
            for proj in config['python_projects']:
                if isinstance(proj, dict):
                    projects.append(PythonProject(**proj))
                elif isinstance(proj, str):
                    projects.append(PythonProject(path=proj))
                else:
                    projects.append(proj)
            config['python_projects'] = projects
        if 'cpp' in config:
            config['cpp'] = CppConfig(**config['cpp'])
        return config
    except (json.JSONDecodeError, TypeError) as e:
        logging.getLogger('devcheck').error(f"Invalid config file {cfg_path}: {e}")
        return {}

def discover_python_projects(root: Path) -> List[PythonProject]:
    DEFAULT_ENTRY_NAMES = ("main.py", "app.py", "run.py", "__main__.py", "cli.py")
    projects = []
    search_dirs = [root / "src", root / "scripts", root / "python", root]
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for p in search_dir.rglob("*"):
            if not p.is_dir() or p.name.startswith('.'):
                continue
            if any((p / skip).exists() for skip in ['.git', 'venv', '.venv']):
                continue
            for entry_name in DEFAULT_ENTRY_NAMES:
                entry_path = p / entry_name
                if entry_path.exists():
                    try:
                        content = entry_path.read_text(encoding='utf-8', errors='ignore')
                        if 'if __name__' in content or 'def main' in content:
                            projects.append(PythonProject(
                                path=str(p.relative_to(root)).replace("\\", "/"),
                                entry=entry_name
                            ))
                            break
                    except Exception:
                        continue
    return projects

# -------------------- Mandatory Cleanup --------------------

def safe_rmtree(path: Path, logger: Optional[logging.Logger] = None):
    """Robust rmtree that clears read-only bits on Windows and retries."""
    if not path.exists():
        return
    def on_rm_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    for attempt in range(3):
        try:
            if path.is_dir():
                shutil.rmtree(path, onerror=on_rm_error)
            else:
                path.unlink(missing_ok=True)
            return
        except Exception as e:
            if logger:
                logger.debug(f"Retry {attempt+1} deleting {path}: {e}")
            time.sleep(0.5 * (attempt + 1))

def mandatory_cleanup(root: Path, cpp_config: "CppConfig"):
    """Delete build artifacts and any .venv_devcheck* folders before running."""
    logger = logging.getLogger('devcheck')
    print_header("CLEANUP (mandatory)")
    targets: List[Path] = []

    # 1) C++ build directory (from config)
    try:
        build_dir = root / (cpp_config.build_dir if isinstance(cpp_config, CppConfig) else ".devcheck/build")
        targets.append(build_dir)
    except Exception:
        targets.append(root / ".devcheck" / "build")

    # 2) Old-style per-project venvs: .venv_devcheck*
    for p in root.rglob(".venv_devcheck*"):
        if p.is_dir():
            targets.append(p)

    # 3) New-style venv bucket used by this script
    targets.append(root / ".devcheck" / "venvs")

    # De-duplicate & delete
    seen = set()
    for t in targets:
        t = t.resolve()
        if t in seen:
            continue
        seen.add(t)
        if t.exists():
            logger.info(f"Cleaning: {t}")
            safe_rmtree(t, logger=logger)
        else:
            logger.debug(f"Not found (skip): {t}")

# -------------------- Python Environment Management --------------------

class PythonEnvironment:
    def __init__(self, root: Path, logger: logging.Logger):
        self.root = root
        self.logger = logger
        self._venv_cache = {}
    def ensure_venv(self, proj_dir: Path, project: PythonProject) -> Tuple[Path, Path, Path]:
        venv_name = f".venv_devcheck_{hash(str(proj_dir)) % 10000:04d}"
        venv_dir = self.root / ".devcheck" / "venvs" / venv_name
        cache_key = str(venv_dir)
        if cache_key in self._venv_cache:
            return self._venv_cache[cache_key]
        py_exe = self._get_python_executable(project.python_version)
        if not venv_dir.exists():
            self.logger.info(f"Creating virtual environment at {venv_dir}")
            venv_dir.parent.mkdir(parents=True, exist_ok=True)
            rc, out, err = run_cmd([py_exe, "-m", "venv", str(venv_dir)])
            if rc != 0:
                raise RuntimeError(f"Failed to create venv: {err}")
        if platform.system() == "Windows":
            vpy = venv_dir / "Scripts" / "python.exe"
            pip = venv_dir / "Scripts" / "pip.exe"
        else:
            vpy = venv_dir / "bin" / "python"
            pip = venv_dir / "bin" / "pip"
        if not vpy.exists():
            raise RuntimeError(f"Venv python not found at {vpy}")
        result = (venv_dir, vpy, pip)
        self._venv_cache[cache_key] = result
        return result
    def _get_python_executable(self, version: Optional[str] = None) -> str:
        if not version:
            return sys.executable
        candidates = [f"python{version}", f"python{version.split('.')[0]}"]
        for candidate in candidates:
            if which(candidate):
                return candidate
        self.logger.warning(f"Python {version} not found, using {sys.executable}")
        return sys.executable
    def install_requirements(self, proj_dir: Path, pip_path: Path, project: PythonProject):
        req_file = project.requirements or "requirements.txt"
        req_path = proj_dir / req_file
        if not req_path.exists():
            return
        self.logger.info(f"Installing requirements from {req_file}")
        req_hash = hash(req_path.read_text())
        hash_file = proj_dir / ".devcheck_req_hash"
        if hash_file.exists() and hash_file.read_text().strip() == str(req_hash):
            self.logger.debug("Requirements already installed (hash match)")
            return
        rc, out, err = run_cmd([str(pip_path), "install", "-r", str(req_path), "--quiet", "--disable-pip-version-check"], timeout=300)
        if rc != 0:
            raise RuntimeError(f"pip install failed: {err}")
        hash_file.write_text(str(req_hash))

# -------------------- C++ Build System --------------------

class CppBuilder:
    def __init__(self, root: Path, logger: logging.Logger):
        self.root = root
        self.logger = logger
        self._tool_env_cache = None
    def build_and_run(self, config: CppConfig) -> TestResult:
        start_time = time.time()
        try:
            cmake = self._find_cmake(config)
            if not cmake:
                if config.allow_skip:
                    return TestResult("SKIP", time.time() - start_time, error_message="CMake not found")
                else:
                    return TestResult("FAIL", time.time() - start_time, error_message="CMake not found and allow_skip=False")
            source_dir = self._find_source_dir(config)
            if not source_dir:
                msg = f"No CMakeLists.txt found in expected locations"
                status = "SKIP" if config.allow_skip else "FAIL"
                return TestResult(status, time.time() - start_time, error_message=msg)
            build_dir = self.root / config.build_dir
            build_dir.mkdir(parents=True, exist_ok=True)
            env = self._setup_build_environment(config)
            if not self._configure_project(cmake, source_dir, build_dir, config, env):
                return TestResult("FAIL", time.time() - start_time, error_message="CMake configure failed")
            if not self._build_project(cmake, build_dir, config, env):
                return TestResult("FAIL", time.time() - start_time, error_message="Build failed")
            exe_path = self._find_executable(build_dir, config)
            if not exe_path:
                return TestResult("FAIL", time.time() - start_time, error_message=f"Executable '{config.target}' not found")
            return self._run_executable(exe_path, config, env, start_time)
        except Exception as e:
            return TestResult("FAIL", time.time() - start_time, error_message=str(e))
    def _find_cmake(self, config: CppConfig) -> Optional[str]:
        cmake = (config.cmake_path or os.environ.get("CMAKE_BIN") or which("cmake") or self._find_vs_cmake())
        if not cmake:
            try:
                cmake, _, _ = self._ensure_tool_venv()
                self.logger.info("Bootstrapped portable CMake & Ninja")
            except Exception as e:
                self.logger.error(f"CMake bootstrap failed: {e}")
                return None
        return cmake
    def _find_source_dir(self, config: CppConfig) -> Optional[Path]:
        candidates = [self.root / config.source_dir, self.root]
        for candidate in candidates:
            if (candidate / "CMakeLists.txt").exists():
                return candidate
        return None
    def _setup_build_environment(self, config: CppConfig) -> Dict[str, str]:
        base_env = self._get_tool_env() or os.environ.copy()
        if platform.system() == "Windows" and not config.force_compiler:
            msvc_env = self._try_capture_msvc_env()
            if msvc_env:
                base_env.update(msvc_env)
        return base_env
    def _configure_project(self, cmake: str, source_dir: Path, build_dir: Path, config: CppConfig, env: Dict[str, str]) -> bool:
        args = [cmake, "-S", str(source_dir), "-B", str(build_dir)]
        if which("ninja") or self._get_tool_env():
            args.extend(["-G", "Ninja"])
        elif platform.system() == "Windows":
            args.extend(["-G", "Visual Studio 17 2022"])
        args.append(f"-DCMAKE_BUILD_TYPE={config.build_type}")
        if config.force_compiler:
            compiler_map = {"gcc": "g++", "clang": "clang++", "msvc": "cl.exe"}
            if config.force_compiler in compiler_map:
                compiler = compiler_map[config.force_compiler]
                if which(compiler):
                    args.append(f"-DCMAKE_CXX_COMPILER={compiler}")
        self.logger.info(f"Configuring CMake project...")
        rc, out, err = run_cmd(args, env=env, timeout=config.timeout)
        if rc != 0:
            self.logger.error(f"Configure failed: {err}")
            return False
        return True
    def _build_project(self, cmake: str, build_dir: Path, config: CppConfig, env: Dict[str, str]) -> bool:
        args = [cmake, "--build", str(build_dir), "--config", config.build_type]
        if platform.system() != "Windows":
            import multiprocessing
            args.extend(["--parallel", str(multiprocessing.cpu_count())])
        self.logger.info(f"Building project...")
        rc, out, err = run_cmd(args, env=env, timeout=config.timeout)
        if rc != 0:
            self.logger.error(f"Build failed: {err}")
            return False
        return True
    def _find_executable(self, build_dir: Path, config: CppConfig) -> Optional[Path]:
        exe_name = config.target + (".exe" if platform.system() == "Windows" else "")
        candidates = [
            build_dir / exe_name,
            build_dir / config.build_type / exe_name,
            build_dir / "Debug" / exe_name,
            build_dir / "Release" / exe_name,
        ]
        candidates.extend(build_dir.rglob(exe_name))
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        return None
    def _run_executable(self, exe_path: Path, config: CppConfig, env: Dict[str, str], start_time: float) -> TestResult:
        self.logger.info(f"Running: {exe_path}")
        rc, out, err = run_cmd([str(exe_path)] + config.args, cwd=str(exe_path.parent), env=env, timeout=config.timeout)
        combined_output = (out + err).lower()
        success = rc == 0 and "working" in combined_output
        status = "PASS" if success else "FAIL"
        duration = time.time() - start_time
        return TestResult(status, duration, out, err, return_code=rc)
    def _get_tool_env(self) -> Optional[Dict[str, str]]:
        return self._tool_env_cache
    def _ensure_tool_venv(self) -> Tuple[str, Dict[str, str], bool]:
        if self._tool_env_cache:
            toolvenv = self.root / ".devcheck" / "toolvenv"
            bin_dir = toolvenv / ("Scripts" if platform.system() == "Windows" else "bin")
            cmake = bin_dir / ("cmake.exe" if platform.system() == "Windows" else "cmake")
            ninja = bin_dir / ("ninja.exe" if platform.system() == "Windows" else "ninja")
            return str(cmake), self._tool_env_cache, ninja.exists()
        toolvenv = self.root / ".devcheck" / "toolvenv"
        if not toolvenv.exists():
            rc, _, err = run_cmd([sys.executable, "-m", "venv", str(toolvenv)])
            if rc != 0:
                raise RuntimeError(f"Failed to create tool venv: {err}")
        bin_dir = toolvenv / ("Scripts" if platform.system() == "Windows" else "bin")
        pip = bin_dir / ("pip.exe" if platform.system() == "Windows" else "pip")
        rc, _, err = run_cmd([str(pip), "install", "-q", "cmake>=3.26", "ninja"])
        if rc != 0:
            raise RuntimeError(f"Failed to install tools: {err}")
        cmake = bin_dir / ("cmake.exe" if platform.system() == "Windows" else "cmake")
        ninja = bin_dir / ("ninja.exe" if platform.system() == "Windows" else "ninja")
        env = os.environ.copy()
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        self._tool_env_cache = env
        return str(cmake), env, ninja.exists()
    def _find_vs_cmake(self) -> Optional[str]:
        if platform.system() != "Windows":
            return None
        bases = [Path(r"C:\Program Files\Microsoft Visual Studio\2022"),
                 Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022")]
        for base in bases:
            for edition in ["Community", "Professional", "Enterprise", "BuildTools"]:
                cmake_path = (base / edition / "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe")
                if cmake_path.exists():
                    return str(cmake_path)
        return None
    def _try_capture_msvc_env(self) -> Optional[Dict[str, str]]:
        if platform.system() != "Windows":
            return None
        vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
        if not vswhere.exists():
            return None
        rc, out, err = run_cmd([str(vswhere), "-latest", "-products", "*",
                                "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                                "-property", "installationPath"])
        if rc != 0 or not out.strip():
            return None
        vs_root = Path(out.strip())
        batch_files = [vs_root / "VC/Auxiliary/Build/vcvars64.bat", vs_root / "Common7/Tools/VsDevCmd.bat"]
        for batch_file in batch_files:
            if batch_file.exists():
                cmd = f'"{batch_file}" -no_logo && set'
                rc, out, err = run_cmd(["cmd.exe", "/s", "/c", cmd])
                if rc == 0 and out:
                    env = {}
                    for line in out.splitlines():
                        if "=" in line and not line.startswith("="):
                            key, value = line.split("=", 1)
                            env[key] = value
                    return env
        return None

# -------------------- Test Runners --------------------

def run_python_project(project: PythonProject, root: Path, py_env: PythonEnvironment) -> Dict:
    logger = logging.getLogger('devcheck')
    start_time = time.time()
    try:
        proj_dir = root / project.path
        logger.info(f"Testing Python project: {project.path}")
        venv_dir, vpy, pip = py_env.ensure_venv(proj_dir, project)
        py_env.install_requirements(proj_dir, pip, project)
        entry_path = proj_dir / project.entry
        if not entry_path.exists():
            raise FileNotFoundError(f"Entry script not found: {entry_path}")
        logger.debug(f"Running: {entry_path}")
        rc, out, err = run_cmd([str(vpy), str(entry_path)], cwd=str(proj_dir), timeout=project.timeout)
        combined_output = (out + err).lower()
        success = rc == 0 and project.expect.lower() in combined_output
        status = "PASS" if success else "FAIL"
        duration = time.time() - start_time
        result = {
            "path": str(proj_dir),
            "entry": project.entry,
            "status": status,
            "duration": duration,
            "return_code": rc,
            "stdout": out[-4000:],
            "stderr": err[-4000:]
        }
        logger.info(f"Python project {project.path}: {status} ({duration:.2f}s)")
        return result
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Python project {project.path} failed: {e}")
        return {
            "path": str(root / project.path),
            "entry": project.entry,
            "status": "FAIL",
            "duration": duration,
            "return_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

def run_tests_parallel(projects: List[PythonProject], root: Path, 
                      py_env: PythonEnvironment, max_workers: int = 4) -> List[Dict]:
    logger = logging.getLogger('devcheck')
    if not projects:
        return []
    results = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(projects))) as executor:
        future_to_project = {executor.submit(run_python_project, proj, root, py_env): proj for proj in projects}
        for future in as_completed(future_to_project):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                project = future_to_project[future]
                logger.error(f"Failed to run project {project.path}: {e}")
                results.append({
                    "path": str(root / project.path),
                    "entry": project.entry,
                    "status": "FAIL",
                    "duration": 0,
                    "return_code": -1,
                    "stdout": "",
                    "stderr": str(e)
                })
    return sorted(results, key=lambda r: r["path"])

# -------------------- Main Function --------------------

def main():
    parser = argparse.ArgumentParser(
        description="Enhanced local dev checks for Python and C++.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Run with defaults
  %(prog)s --config myconfig.json            # Use custom config
  %(prog)s --verbose --parallel              # Verbose output with parallel execution
  %(prog)s --timeout 600 --max-workers 2     # Custom timeouts and worker count
        """
    )
    parser.add_argument("--config", default="devcheck.json", help="Path to config JSON (default: %(default)s)")
    parser.add_argument("--root", default=".", help="Repository root directory (default: current dir)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--parallel", action="store_true", help="Run Python tests in parallel")
    parser.add_argument("--max-workers", type=int, default=4, help="Maximum parallel workers (default: %(default)s)")
    parser.add_argument("--timeout", type=int, default=300, help="Default timeout for operations (default: %(default)s)")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(args.verbose)
    if args.no_color:
        original_emit = logging.StreamHandler.emit
        def no_color_emit(self, record):
            record.no_color = True
            return original_emit(self, record)
        logging.StreamHandler.emit = no_color_emit

    # Initialize
    root = Path(args.root).resolve()
    logger.info(f"Running DevCheck in: {root}")

    # Load configuration
    config = load_config(root / args.config)

    # Get projects / cpp config
    python_projects = config.get("python_projects") or discover_python_projects(root)
    cpp_config = config.get("cpp") or CppConfig()

    # ---- Mandatory cleanup BEFORE any work ----
    mandatory_cleanup(root, cpp_config)

    # Override timeouts from command line
    if hasattr(cpp_config, 'timeout'):
        cpp_config.timeout = args.timeout
    for proj in python_projects:
        if hasattr(proj, 'timeout'):
            proj.timeout = min(proj.timeout, args.timeout)

    # Results tracking
    results = {
        "python": [],
        "cpp": None,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "root": str(root),
            "parallel": args.parallel,
            "max_workers": args.max_workers,
            "timeout": args.timeout,
        },
        "system_info": {
            "platform": platform.platform(),
            "python_version": sys.version,
            "architecture": platform.architecture()[0],
        }
    }
    overall_success = True

    # Run Python tests
    print_header("PYTHON PROJECT CHECKS")
    if not python_projects:
        logger.info("No Python projects found")
    else:
        py_env = PythonEnvironment(root, logger)
        if args.parallel and len(python_projects) > 1:
            logger.info(f"Running {len(python_projects)} Python projects in parallel (max workers: {args.max_workers})")
            results["python"] = run_tests_parallel(python_projects, root, py_env, args.max_workers)
        else:
            for project in python_projects:
                result = run_python_project(project, root, py_env)
                results["python"].append(result)
        failed_py = [r for r in results["python"] if r["status"] == "FAIL"]
        if failed_py:
            overall_success = False
            logger.error(f"{len(failed_py)} Python project(s) failed")

    # Run C++ tests
    print_header("C++ (CMAKE) CHECK")
    cpp_builder = CppBuilder(root, logger)
    cpp_result = cpp_builder.build_and_run(cpp_config)
    results["cpp"] = {
        "status": cpp_result.status,
        "duration": cpp_result.duration,
        "stdout": cpp_result.stdout[-4000:],
        "stderr": cpp_result.stderr[-4000:],
        "error_message": cpp_result.error_message,
        "return_code": cpp_result.return_code
    }
    if cpp_result.status == "FAIL":
        overall_success = False
        logger.error("C++ project failed")
    logger.info(f"C++ project: {cpp_result.status} ({cpp_result.duration:.2f}s)")

    # Summary
    print_header("SUMMARY")
    total_duration = sum(r.get("duration", 0) for r in results["python"])
    if results["cpp"]:
        total_duration += results["cpp"]["duration"]
    print(f"Total execution time: {total_duration:.2f} seconds")
    print(f"System: {results['system_info']['platform']}")
    print()
    if results["python"]:
        py_counts = {}
        for result in results["python"]:
            status = result["status"]
            py_counts[status] = py_counts.get(status, 0) + 1
        print("Python Projects:")
        for result in results["python"]:
            duration_str = f"({result.get('duration', 0):.1f}s)"
            status_icon = "✓" if result["status"] == "PASS" else "✗" if result["status"] == "FAIL" else "⚠"
            print(f"  {status_icon} {result['path']} :: {result['entry']} -> {result['status']} {duration_str}")
        print(f"\nPython Summary: {py_counts}")
    if results["cpp"]:
        status_icon = "✓" if results["cpp"]["status"] == "PASS" else "✗" if results["cpp"]["status"] == "FAIL" else "⚠"
        duration_str = f"({results['cpp']['duration']:.1f}s)"
        print(f"\nC++ Project:")
        print(f"  {status_icon} CMake build -> {results['cpp']['status']} {duration_str}")
        if results["cpp"]["error_message"]:
            print(f"  Error: {results['cpp']['error_message']}")

    # Save detailed report
    report_dir = root / ".devcheck"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "test_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    html_report_path = report_dir / "test_report.html"
    try:
        generate_html_report(results, output_path= report_dir)
        logger.info(f"HTML report: {html_report_path}")
    except Exception as e:
        logger.warning(f"Failed to generate HTML report: {e}")
    logger.info(f"JSON report: {report_path}")

    if overall_success:
        print(f"\n All tests passed!")
        sys.exit(0)
    else:
        print(f"\n Some tests failed!")
        sys.exit(1)

def generate_html_report(results: Dict, output_path: Path) -> None:
    """Render a nice HTML report to the given output_path."""
    # ---------- summary ----------
    all_results = list(results.get("python", []))
    if results.get("cpp"):
        all_results.append(results["cpp"])

    total_tests = len(all_results)
    passed = sum(1 for r in all_results if (r or {}).get("status") == "PASS")
    failed = sum(1 for r in all_results if (r or {}).get("status") == "FAIL")
    skipped = sum(1 for r in all_results if (r or {}).get("status") == "SKIP")
    total_duration = sum(float((r or {}).get("duration", 0) or 0) for r in all_results)

    # ---------- sections ----------
    sections = []

    # Python tests
    if results.get("python"):
        python_items = []
        for test in results["python"]:
            test = test or {}
            name = str(test.get("path", "(unknown)"))
            entry = str(test.get("entry", "(unknown)"))
            status = str(test.get("status", "UNKNOWN"))
            duration = float(test.get("duration", 0) or 0)
            rc = int(test.get("return_code", 0) or 0)

            stdout_txt = str(test.get("stdout", "") or "")
            stderr_txt = str(test.get("stderr", "") or "")

            status_class = status.lower()
            output_sections = []
            if stdout_txt:
                output_sections.append(
                    f'<div class="test-output">{escape_html(stdout_txt)}</div>'
                )
            if stderr_txt:
                output_sections.append(
                    f'<div class="test-output error">{escape_html(stderr_txt)}</div>'
                )
            outputs = "".join(output_sections)
            collapsible_class = "collapsible" if outputs else ""

            python_items.append(f"""
                <div class="test-item {status_class} {collapsible_class}">
                    <div class="test-header">
                        <div class="test-title">{escape_html(name)} :: {escape_html(entry)}</div>
                        <div class="test-status {status_class}">{escape_html(status)}</div>
                    </div>
                    <div class="test-details">
                        Duration: {duration:.2f}s | Return Code: {rc}
                    </div>
                    {f'<div class="collapsible-content">{outputs}</div>' if outputs else ''}
                </div>
            """)

        sections.append(f"""
            <div class="section">
                <h2>Python Projects ({len(results["python"])} tests)</h2>
                <div class="test-grid">
                    {"".join(python_items)}
                </div>
            </div>
        """)

    # C++ test
    if results.get("cpp"):
        cpp = results["cpp"] or {}
        status = str(cpp.get("status", "UNKNOWN"))
        status_class = status.lower()
        cpp_duration = float(cpp.get("duration", 0) or 0)
        cpp_rc = int(cpp.get("return_code", 0) or 0)

        output_sections = []
        if cpp.get("stdout"):
            output_sections.append(f'<div class="test-output">{escape_html(str(cpp["stdout"]))}</div>')
        if cpp.get("stderr"):
            output_sections.append(f'<div class="test-output error">{escape_html(str(cpp["stderr"]))}</div>')
        if cpp.get("error_message"):
            output_sections.append(f'<div class="test-output error">{escape_html(str(cpp["error_message"]))}</div>')

        outputs = "".join(output_sections)
        collapsible_class = "collapsible" if outputs else ""

        sections.append(f"""
            <div class="section">
                <h2>C++ Project</h2>
                <div class="test-grid">
                    <div class="test-item {status_class} {collapsible_class}">
                        <div class="test-header">
                            <div class="test-title">CMake Build & Run</div>
                            <div class="test-status {status_class}">{escape_html(status)}</div>
                        </div>
                        <div class="test-details">
                            Duration: {cpp_duration:.2f}s | Return Code: {cpp_rc}
                        </div>
                        {f'<div class="collapsible-content">{outputs}</div>' if outputs else ''}
                    </div>
                </div>
            </div>
        """)

    # ---------- template (double the CSS braces!) ----------
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DevCheck Test Report</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; margin: 0; padding: 20px; background-color: #f5f5f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 2.5em; font-weight: 300; }}
            .summary {{ padding: 20px 30px; background: #f8f9fa; border-bottom: 1px solid #e9ecef; }}
            .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-top: 15px; }}
            .summary-card {{ background: white; padding: 20px; border-radius: 6px; border-left: 4px solid #007bff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            .summary-card h3 {{ margin: 0 0 10px 0; color: #495057; font-size: 0.9em; text-transform: uppercase; letter-spacing: 1px; }}
            .summary-card .value {{ font-size: 1.8em; font-weight: bold; color: #212529; }}
            .section {{ padding: 30px; }}
            .section h2 {{ margin: 0 0 20px 0; color: #495057; border-bottom: 2px solid #e9ecef; padding-bottom: 10px; }}
            .test-grid {{ display: grid; gap: 15px; }}
            .test-item {{ background: #f8f9fa; border-radius: 6px; padding: 20px; border-left: 4px solid #6c757d; }}
            .test-item.pass {{ border-left-color: #28a745; background: #f8fff9; }}
            .test-item.fail {{ border-left-color: #dc3545; background: #fff8f8; }}
            .test-item.skip {{ border-left-color: #ffc107; background: #fffef8; }}
            .test-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
            .test-title {{ font-weight: bold; color: #212529; }}
            .test-status {{ padding: 4px 12px; border-radius: 20px; font-size: 0.8em; font-weight: bold; text-transform: uppercase; }}
            .test-status.pass {{ background: #28a745; color: white; }}
            .test-status.fail {{ background: #dc3545; color: white; }}
            .test-status.skip {{ background: #ffc107; color: #212529; }}
            .test-details {{ font-size: 0.9em; color: #6c757d; margin-bottom: 10px; }}
            .test-output {{ background: #2d3748; color: #e2e8f0; padding: 15px; border-radius: 4px; font-family: 'Courier New', monospace; font-size: 0.8em; overflow-x: auto; max-height: 200px; overflow-y: auto; }}
            .test-output.error {{ background: #742a2a; color: #fed7d7; }}
            .collapsible {{ cursor: pointer; user-select: none; }}
            .collapsible:hover {{ background: rgba(0,0,0,0.05); }}
            .collapsible-content {{ display: none; margin-top: 15px; }}
            .collapsible.active .collapsible-content {{ display: block; }}
            .system-info {{ background: #e9ecef; padding: 15px; border-radius: 4px; font-size: 0.9em; margin-top: 15px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>DevCheck Test Report</h1>
                <p>Generated on {timestamp}</p>
            </div>
            <div class="summary">
                <h2>Summary</h2>
                <div class="summary-grid">
                    <div class="summary-card"><h3>Total Tests</h3><div class="value">{total_tests}</div></div>
                    <div class="summary-card"><h3>Passed</h3><div class="value" style="color: #28a745;">{passed}</div></div>
                    <div class="summary-card"><h3>Failed</h3><div class="value" style="color: #dc3545;">{failed}</div></div>
                    <div class="summary-card"><h3>Skipped</h3><div class="value" style="color: #ffc107;">{skipped}</div></div>
                    <div class="summary-card"><h3>Duration</h3><div class="value">{duration:.1f}s</div></div>
                </div>
                <div class="system-info">
                    <strong>System:</strong> {platform}<br>
                    <strong>Python:</strong> {python_version}<br>
                    <strong>Architecture:</strong> {architecture}
                </div>
            </div>
            {sections}
        </div>
        <script>
            document.querySelectorAll('.collapsible').forEach(item => {{
                item.addEventListener('click', function() {{
                    this.classList.toggle('active');
                }});
            }});
        </script>
    </body>
    </html>
    """

    html = html_template.format(
        timestamp=results.get("started_at", time.strftime("%Y-%m-%d %H:%M:%S")),
        total_tests=total_tests,
        passed=passed,
        failed=failed,
        skipped=skipped,
        duration=total_duration,
        platform=(results.get("system_info", {}) or {}).get("platform", "Unknown"),
        python_version=(results.get("system_info", {}) or {}).get("python_version", "Unknown"),
        architecture=(results.get("system_info", {}) or {}).get("architecture", "Unknown"),
        sections="".join(sections),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

def escape_html(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#x27;"))

if __name__ == "__main__":
    main()
