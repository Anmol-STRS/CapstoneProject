# First‑Run Setup Guide

### WE CAN DISCUSS THIS IN-CLASS OR ON BLACKBOARD OR DM

This project includes a bootstrap script: **`scripts/setup.sh`**. Run it on a fresh clone (and any time you want to re‑bootstrap).
> Prefer the **Dev Container** workflow for a zero‑setup, identical environment across all dev machines.

---

## TL;DR

* **Dev Container (recommended)**

  1. Open the repo in VS Code → **Dev Containers: Reopen in Container**.
  2. The container builds once and runs `scripts/setup.sh` automatically (if configured).
  3. Validate:

     ```bash
     python test/run_dev_check.py --config devcheck.json
     ```

* **Local (no container)**

  ```bash
  chmod +x scripts/setup.sh
  bash scripts/setup.sh
  python test/checkDev.py 
  ```

> The test runner writes reports to `.devcheck/test_report.json`

---

## What `scripts/setup.sh` Does
* Insures Everything is installed correctly and everything is present 
* Creates `.devcheck/` if needed and drops a stamp file at `.devcheck/.setup_done` .
* Ensures Python basics (e.g. upgrades `pip`, installs `requirements.txt` if present).
* Performs one‑time heavy tasks on the first run, then skips them later.

---

## Using the Dev Container (Recommended)

**Prereqs:** Docker Desktop, VS Code, and the **Dev Containers** extension.

1. `git clone` the repo and open it in VS Code.
2. Command Palette → **Dev Containers: Reopen in Container**.
3. On first build, `postCreateCommand` can run:

   ```bash
   bash -lc 'chmod +x scripts/setup.sh && ./scripts/setup.sh --post-create'
   ```
4. On each start, `postStartCommand` can run:

   ```bash
   bash -lc 'scripts/setup.sh --on-start || true'
   ```

**Sanity checks inside the container:**

```bash
python --version
cmake --version
ninja --version
python test/checkDev.py --config devcheck.json
```

> CMake Tools is preconfigured (via `.devcontainer/devcontainer.json`) to use `scripts/` as the source dir and `.devcheck/build` as the build dir, with the **Ninja** generator.

---

## Running Locally (Linux/macOS)

```bash
# from repo root
chmod +x scripts/setup.sh
bash scripts/setup.sh
python test/checkDev.py --config devcheck.json
```

**macOS notes**

* If prompted, install **Xcode Command Line Tools**.
* If you need Homebrew tools, install brew and re‑run `setup.sh`.

---

## Running Locally (Windows)

You have three good options:

### A) Dev Container (recommended)

No local toolchain required; everything runs inside the container.

### B) Git Bash (native Windows)

```bash
# In Git Bash
chmod +x scripts/setup.sh
bash scripts/setup.sh
```

If your C++ build requires MSVC, launch the **x64 Native Tools Command Prompt** for Visual Studio to build locally, or let the test runner auto‑detect MSVC/Clang.

### C) WSL (Windows Subsystem for Linux)

Open your WSL distro (e.g. Ubuntu), `cd` to the repo, and follow the Linux steps.


## Verify the Environment

Run the unified health check:

```bash
python test/checkDev.py --config devcheck.json
```

**PASS** means:

* Each Python subproject’s entry script printed something containing **“working”**.
* The C++ module configured & built with CMake/Ninja and its binary printed **“working”**.

Artifacts:

* `.devcheck/build/` — CMake/Ninja build tree
* `.devcheck/test_report.json` — machine-readable summary
* `.devcheck/test_report.html` — pretty HTML report

---

## Cleaning & Re‑running

The test runner performs **mandatory cleanup** before each run (build dir + old venvs).
If you want to nuke everything manually:

```bash
rm -rf .devcheck/build .devcheck/venvs .venv_devcheck*
```

Then re‑run:

```bash
bash scripts/setup.sh
python test/run_dev_check.py --config devcheck.json
```

---

## Troubleshooting

**Permission denied (`setup.sh`)**

```bash
git config core.fileMode true
git checkout -- scripts/setup.sh
chmod +x scripts/setup.sh
```
## If we implement large files in future
Ensure LF endings via `.gitattributes` with:

```
*.sh text eol=lf
```

**“bash: command not found” on Windows**  → Use **Git Bash**, **WSL**, or the **Dev Container**.

**CMake/Ninja/Compiler missing locally**  → Prefer the **Dev Container** or install toolchains. The test runner can also bootstrap portable CMake/Ninja.

**VS Code can’t detect the CMake project**

* Ensure `cmake.sourceDirectory` points to `scripts/` and `cmake.buildDirectory` to `.devcheck/build`.
* Optionally add a `CMakePresets.json`.

---

## FAQ

### Again We can Discuss this in-class or on blackboard or DM 
---
**Where do builds go?**  → `.devcheck/build/` (ignored by Git).

**Can I rerun `setup.sh` anytime?**  → Yes. It’s idempotent and uses `.devcheck/.setup_done`.

**Do I need to install anything locally?**  → Not if you use the **Dev Container**.

---

## One‑Liner (Local)

```bash
chmod +x scripts/setup.sh && bash scripts/setup.sh && python test/checkDev.py --config devcheck.json
```
