@echo off
setlocal enabledelayedexpansion

REM DevCheck Runner Script with Auto-Installation (Windows Batch)
REM Checks for required tools (Python, Git, CMake, C++ compiler) and installs them if missing
REM 
REM Usage:
REM   run_devcheck.bat                    # Run with default settings
REM   run_devcheck.bat --verbose          # Run with verbose output
REM   run_devcheck.bat --parallel         # Run Python tests in parallel
REM   run_devcheck.bat --help             # Show help

REM Colors for output (using ANSI escape codes where supported)
set "RED=[31m"
set "GREEN=[32m"
set "YELLOW=[33m"
set "BLUE=[34m"
set "PURPLE=[35m"
set "CYAN=[36m"
set "NC=[0m"

REM Global variables
set "PYTHON_CMD="
set "MISSING_TOOLS="
set "PACKAGE_MANAGER="
set "DEVCHECK_SCRIPT="
set "CHECK_ONLY=0"

REM Enable ANSI colors for Windows 10+
for /f "tokens=3" %%a in ('ver') do set VERSION=%%a
for /f "tokens=1 delims=." %%a in ("%VERSION%") do set MAJOR=%%a
if %MAJOR% GEQ 10 (
    REM Windows 10 or later supports ANSI codes
) else (
    REM Disable colors for older Windows
    set "RED="
    set "GREEN="
    set "YELLOW="
    set "BLUE="
    set "PURPLE="
    set "CYAN="
    set "NC="
)

REM Main execution
call :main %*
goto :eof

:main
    echo ========================================
    echo     DevCheck Runner with Auto-Install
    echo ========================================
    echo.
    
    REM Process command line arguments first
    call :process_arguments %*
    
    REM If help was requested, exit
    if "%SHOW_HELP%"=="1" goto :eof
    
    REM Detect package manager
    call :detect_package_manager
    
    REM Check for all required tools
    call :check_python
    call :check_git
    call :check_cmake
    call :check_cpp_compiler
    
    REM Install missing tools if any
    if not "!MISSING_TOOLS!"=="" (
        call :install_missing_tools
        
        REM Verify installation
        echo.
        call :verify_installation
        if errorlevel 1 (
            call :print_error "Installation verification failed. Please check the instructions above."
            exit /b 1
        )
    )
    
    echo.
    call :print_success "All required tools are available!"
    echo.
    
    REM If check-only mode, exit here
    if "%CHECK_ONLY%"=="1" (
        call :print_success "Tool check completed successfully!"
        exit /b 0
    )
    
    REM Find DevCheck script and validate project
    call :find_devcheck_script
    if errorlevel 1 exit /b 1
    
    call :check_project_structure
    
    REM Run DevCheck
    call :run_devcheck
    exit /b %ERRORLEVEL%

REM Function to print colored output
:print_info
    echo %BLUE%[INFO]%NC% %~1
    goto :eof

:print_success
    echo %GREEN%[SUCCESS]%NC% %~1
    goto :eof

:print_warning
    echo %YELLOW%[WARNING]%NC% %~1
    goto :eof

:print_error
    echo %RED%[ERROR]%NC% %~1
    goto :eof

:print_install
    echo %PURPLE%[INSTALL]%NC% %~1
    goto :eof

:print_check
    echo %CYAN%[CHECK]%NC% %~1
    goto :eof

REM Function to detect package manager
:detect_package_manager
    call :print_check "Detecting package manager..."
    
    REM Check for winget (Windows Package Manager)
    where winget >nul 2>&1
    if %errorlevel%==0 (
        set "PACKAGE_MANAGER=winget"
        call :print_info "Found Windows Package Manager (winget)"
        goto :eof
    )
    
    REM Check for Chocolatey
    where choco >nul 2>&1
    if %errorlevel%==0 (
        set "PACKAGE_MANAGER=choco"
        call :print_info "Found Chocolatey"
        goto :eof
    )
    
    REM Check for Scoop
    where scoop >nul 2>&1
    if %errorlevel%==0 (
        set "PACKAGE_MANAGER=scoop"
        call :print_info "Found Scoop"
        goto :eof
    )
    
    set "PACKAGE_MANAGER=none"
    call :print_warning "No package manager found. Manual installation may be required."
    goto :eof

REM Function to check Python
:check_python
    call :print_check "Checking for Python..."
    
    REM Try python3 first, then python, then py launcher
    for %%c in (python3 python py) do (
        where %%c >nul 2>&1
        if !errorlevel!==0 (
            REM Get Python version
            for /f "tokens=2" %%v in ('%%c --version 2^>^&1') do set "PY_VERSION=%%v"
            
            REM Extract major and minor version
            for /f "tokens=1,2 delims=." %%a in ("!PY_VERSION!") do (
                set "PY_MAJOR=%%a"
                set "PY_MINOR=%%b"
            )
            
            REM Check if Python 3.7+
            if !PY_MAJOR! GEQ 3 (
                if !PY_MINOR! GEQ 7 (
                    set "PYTHON_CMD=%%c"
                    call :print_success "Found Python !PY_VERSION!"
                    goto :check_pip
                ) else (
                    call :print_warning "Found Python !PY_VERSION! but Python 3.7+ required"
                )
            ) else (
                call :print_warning "Found Python !PY_VERSION! but Python 3.7+ required"
            )
        )
    )
    
    call :print_warning "Python 3.7+ not found"
    set "MISSING_TOOLS=!MISSING_TOOLS! python"
    
:check_pip
    if not "!PYTHON_CMD!"=="" (
        !PYTHON_CMD! -m pip --version >nul 2>&1
        if !errorlevel!==0 (
            call :print_success "pip is available"
        ) else (
            call :print_warning "pip not found"
            set "MISSING_TOOLS=!MISSING_TOOLS! pip"
        )
    )
    goto :eof

REM Function to check Git
:check_git
    call :print_check "Checking for Git..."
    
    where git >nul 2>&1
    if %errorlevel%==0 (
        for /f "tokens=3" %%v in ('git --version') do set "GIT_VERSION=%%v"
        call :print_success "Found Git !GIT_VERSION!"
    ) else (
        call :print_warning "Git not found"
        set "MISSING_TOOLS=!MISSING_TOOLS! git"
    )
    goto :eof

REM Function to check CMake
:check_cmake
    call :print_check "Checking for CMake..."
    
    where cmake >nul 2>&1
    if %errorlevel%==0 (
        for /f "tokens=3" %%v in ('cmake --version ^| findstr /i "version"') do set "CMAKE_VERSION=%%v"
        call :print_success "Found CMake !CMAKE_VERSION!"
    ) else (
        call :print_warning "CMake not found (will try portable installation if needed)"
    )
    goto :eof

REM Function to check C++ compiler
:check_cpp_compiler
    call :print_check "Checking for C++ compiler..."
    
    set "COMPILER_FOUND=0"
    
    REM Check for MSVC (cl.exe)
    where cl >nul 2>&1
    if !errorlevel!==0 (
        call :print_success "Found MSVC compiler (cl.exe)"
        set "COMPILER_FOUND=1"
        goto :eof
    )
    
    REM Check for MinGW g++
    where g++ >nul 2>&1
    if !errorlevel!==0 (
        for /f "tokens=3" %%v in ('g++ --version ^| findstr /i "g++"') do set "GPP_VERSION=%%v"
        call :print_success "Found g++ !GPP_VERSION!"
        set "COMPILER_FOUND=1"
        goto :eof
    )
    
    REM Check for Clang
    where clang++ >nul 2>&1
    if !errorlevel!==0 (
        call :print_success "Found clang++"
        set "COMPILER_FOUND=1"
        goto :eof
    )
    
    REM Check if Visual Studio is installed
    if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" (
        "%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -property installationPath >nul 2>&1
        if !errorlevel!==0 (
            call :print_success "Found Visual Studio installation"
            set "COMPILER_FOUND=1"
            goto :eof
        )
    )
    
    if "%COMPILER_FOUND%"=="0" (
        call :print_warning "No C++ compiler found"
        set "MISSING_TOOLS=!MISSING_TOOLS! cpp-compiler"
    )
    goto :eof

REM Function to install missing tools
:install_missing_tools
    echo.
    call :print_warning "Missing tools detected: !MISSING_TOOLS!"
    echo.
    
    REM Ask user for permission
    set /p "INSTALL_CONFIRM=Would you like to automatically install the missing tools? (y/N): "
    if /i not "!INSTALL_CONFIRM!"=="y" (
        call :print_info "Installation cancelled. Please install the missing tools manually:"
        call :show_manual_instructions
        exit /b 1
    )
    
    REM Check for admin privileges
    net session >nul 2>&1
    if %errorlevel% neq 0 (
        call :print_warning "Administrator privileges required for installation."
        call :print_info "Please run this script as Administrator or install tools manually."
        echo.
        call :show_manual_instructions
        exit /b 1
    )
    
    REM Install based on package manager
    if "%PACKAGE_MANAGER%"=="winget" (
        call :install_with_winget
    ) else if "%PACKAGE_MANAGER%"=="choco" (
        call :install_with_choco
    ) else if "%PACKAGE_MANAGER%"=="scoop" (
        call :install_with_scoop
    ) else (
        call :print_error "No package manager available. Please install tools manually."
        call :show_manual_instructions
        exit /b 1
    )
    goto :eof

REM Function to install with winget
:install_with_winget
    call :print_install "Installing tools with winget..."
    
    for %%t in (!MISSING_TOOLS!) do (
        if "%%t"=="python" (
            call :print_install "Installing Python..."
            winget install Python.Python.3.12 --silent --accept-license
        ) else if "%%t"=="git" (
            call :print_install "Installing Git..."
            winget install Git.Git --silent --accept-license
        ) else if "%%t"=="cpp-compiler" (
            call :print_install "Installing Visual Studio Build Tools..."
            winget install Microsoft.VisualStudio.2022.BuildTools --silent --accept-license
        )
    )
    
    REM Install CMake if needed
    where cmake >nul 2>&1
    if %errorlevel% neq 0 (
        call :print_install "Installing CMake..."
        winget install Kitware.CMake --silent --accept-license
    )
    goto :eof

REM Function to install with Chocolatey
:install_with_choco
    call :print_install "Installing tools with Chocolatey..."
    
    for %%t in (!MISSING_TOOLS!) do (
        if "%%t"=="python" (
            call :print_install "Installing Python..."
            choco install python -y
        ) else if "%%t"=="git" (
            call :print_install "Installing Git..."
            choco install git -y
        ) else if "%%t"=="cpp-compiler" (
            call :print_install "Installing Visual Studio Build Tools..."
            choco install visualstudio2022buildtools -y
        )
    )
    
    REM Install CMake if needed
    where cmake >nul 2>&1
    if %errorlevel% neq 0 (
        call :print_install "Installing CMake..."
        choco install cmake -y
    )
    goto :eof

REM Function to install with Scoop
:install_with_scoop
    call :print_install "Installing tools with Scoop..."
    
    for %%t in (!MISSING_TOOLS!) do (
        if "%%t"=="python" (
            call :print_install "Installing Python..."
            scoop install python
        ) else if "%%t"=="git" (
            call :print_install "Installing Git..."
            scoop install git
        ) else if "%%t"=="cpp-compiler" (
            call :print_install "Installing MinGW..."
            scoop install mingw
        )
    )
    
    REM Install CMake if needed
    where cmake >nul 2>&1
    if %errorlevel% neq 0 (
        call :print_install "Installing CMake..."
        scoop install cmake
    )
    goto :eof

REM Function to verify installation
:verify_installation
    call :print_check "Verifying installation..."
    
    set "MISSING_TOOLS="
    call :check_python
    call :check_git
    call :check_cmake
    call :check_cpp_compiler
    
    if not "!MISSING_TOOLS!"=="" (
        call :print_error "Some tools are still missing: !MISSING_TOOLS!"
        call :print_warning "You may need to restart your terminal or add tools to PATH."
        exit /b 1
    ) else (
        call :print_success "All tools verified successfully!"
    )
    exit /b 0

REM Function to find DevCheck script
:find_devcheck_script
    call :print_check "Looking for DevCheck script..."
    
    REM Check from current directory
    for %%p in (
        "test\checkDev.py"
        "tests\checkDev.py"
        "scripts\checkDev.py"
        "checkDev.py"
        "devcheck\checkDev.py"
    ) do (
        if exist %%p (
            set "DEVCHECK_SCRIPT=%%~p"
            call :print_success "Found DevCheck script: !DEVCHECK_SCRIPT!"
            exit /b 0
        )
    )
    
    REM Check from parent directory
    for %%p in (
        "..\test\checkDev.py"
        "..\tests\checkDev.py"
        "..\scripts\checkDev.py"
        "..\checkDev.py"
        "..\devcheck\checkDev.py"
    ) do (
        if exist %%p (
            set "DEVCHECK_SCRIPT=%%~p"
            call :print_success "Found DevCheck script: !DEVCHECK_SCRIPT!"
            exit /b 0
        )
    )
    
    REM Check from grandparent directory
    for %%p in (
        "..\..\test\checkDev.py"
        "..\..\tests\checkDev.py"
        "..\..\scripts\checkDev.py"
        "..\..\checkDev.py"
        "..\..\devcheck\checkDev.py"
    ) do (
        if exist %%p (
            set "DEVCHECK_SCRIPT=%%~p"
            call :print_success "Found DevCheck script: !DEVCHECK_SCRIPT!"
            exit /b 0
        )
    )
    
    call :print_error "DevCheck script not found. Looked in:"
    echo   - test\checkDev.py (from current, parent, and grandparent directories)
    echo   - tests\checkDev.py
    echo   - scripts\checkDev.py
    echo   - checkDev.py
    echo   - devcheck\checkDev.py
    echo.
    echo Current directory: %CD%
    exit /b 1

REM Function to check project structure
:check_project_structure
    call :print_check "Validating project structure..."
    
    set "STRUCTURE_OK=0"
    if exist ".git" set "STRUCTURE_OK=1"
    if exist "devcheck.json" set "STRUCTURE_OK=1"
    if exist "src" set "STRUCTURE_OK=1"
    if exist "scripts" set "STRUCTURE_OK=1"
    
    if "%STRUCTURE_OK%"=="0" (
        call :print_warning "Current directory doesn't look like a project root"
        call :print_warning "Make sure you're running this from your project's root directory"
    ) else (
        call :print_success "Project structure looks good"
    )
    goto :eof

REM Function to process command line arguments
:process_arguments
    set "SHOW_HELP=0"
    set "DEVCHECK_ARGS="
    
:process_loop
    if "%~1"=="" goto :eof
    
    if "%~1"=="--help" set "SHOW_HELP=1" & call :show_usage & goto :eof
    if "%~1"=="-h" set "SHOW_HELP=1" & call :show_usage & goto :eof
    if "%~1"=="--check-only" set "CHECK_ONLY=1" & shift & goto :process_loop
    if "%~1"=="--verbose" set "DEVCHECK_ARGS=!DEVCHECK_ARGS! --verbose" & shift & goto :process_loop
    if "%~1"=="-v" set "DEVCHECK_ARGS=!DEVCHECK_ARGS! --verbose" & shift & goto :process_loop
    if "%~1"=="--parallel" set "DEVCHECK_ARGS=!DEVCHECK_ARGS! --parallel" & shift & goto :process_loop
    if "%~1"=="-p" set "DEVCHECK_ARGS=!DEVCHECK_ARGS! --parallel" & shift & goto :process_loop
    if "%~1"=="--no-cleanup" (
        set "DEVCHECK_ARGS=!DEVCHECK_ARGS:--cleanup=! --no-cleanup"
        shift
        goto :process_loop
    )
    if "%~1"=="--config" (
        set "DEVCHECK_ARGS=!DEVCHECK_ARGS! --config %~2"
        shift
        shift
        goto :process_loop
    )
    if "%~1"=="--root" (
        set "DEVCHECK_ARGS=!DEVCHECK_ARGS! --root %~2"
        shift
        shift
        goto :process_loop
    )
    if "%~1"=="--timeout" (
        set "DEVCHECK_ARGS=!DEVCHECK_ARGS! --timeout %~2"
        shift
        shift
        goto :process_loop
    )
    if "%~1"=="--max-workers" (
        set "DEVCHECK_ARGS=!DEVCHECK_ARGS! --max-workers %~2"
        shift
        shift
        goto :process_loop
    )
    if "%~1"=="--no-color" (
        set "DEVCHECK_ARGS=!DEVCHECK_ARGS! --no-color"
        shift
        goto :process_loop
    )
    
    call :print_error "Unknown option: %~1"
    echo Use --help for usage information
    exit /b 1

REM Function to show usage
:show_usage
    echo DevCheck Runner Script with Auto-Installation
    echo.
    echo This script checks for required tools (Python, Git, CMake, C++ compiler)
    echo and can automatically install them if missing.
    echo.
    echo Usage: %~nx0 [OPTIONS]
    echo.
    echo Options:
    echo   --help, -h          Show this help message
    echo   --verbose, -v       Enable verbose output
    echo   --parallel, -p      Run Python tests in parallel
    echo   --no-cleanup        Keep temporary files after testing
    echo   --config FILE       Use custom config file
    echo   --root DIR          Set project root directory
    echo   --timeout SECONDS   Set timeout for operations
    echo   --max-workers N     Set maximum parallel workers
    echo   --check-only        Only check for tools, don't run tests
    echo.
    echo Examples:
    echo   %~nx0                           # Check tools and run tests
    echo   %~nx0 --check-only              # Only check for required tools
    echo   %~nx0 --verbose --parallel      # Verbose output with parallel execution
    echo   %~nx0 --config myconfig.json    # Use custom configuration
    echo.
    goto :eof

REM Function to show manual installation instructions
:show_manual_instructions
    echo.
    call :print_info "Manual installation instructions for Windows:"
    echo.
    echo Option 1: Using Windows Package Manager (winget)
    echo   winget install Python.Python.3.12
    echo   winget install Git.Git
    echo   winget install Kitware.CMake
    echo   winget install Microsoft.VisualStudio.2022.BuildTools
    echo.
    echo Option 2: Using Chocolatey (https://chocolatey.org/)
    echo   choco install python git cmake visualstudio2022buildtools -y
    echo.
    echo Option 3: Using Scoop (https://scoop.sh/)
    echo   scoop install python git cmake mingw
    echo.
    echo Option 4: Manual downloads
    echo   - Python 3.7+: https://python.org/downloads/
    echo   - Git 2.20+: https://git-scm.com/download/win
    echo   - CMake 3.16+: https://cmake.org/download/
    echo   - Visual Studio Build Tools: https://visualstudio.microsoft.com/downloads/
    echo.
    echo After installation, restart this script or your terminal.
    echo.
    goto :eof

REM Function to run DevCheck
:run_devcheck
    call :print_info "Running DevCheck with arguments: !DEVCHECK_ARGS!"
    echo.
    
    REM Run the DevCheck script
    !PYTHON_CMD! "!DEVCHECK_SCRIPT!" !DEVCHECK_ARGS!
    
    if %errorlevel%==0 (
        echo.
        call :print_success "DevCheck completed successfully!"
        
        REM Show report locations if they exist
        if exist ".devcheck\test_report.json" (
            call :print_info "JSON report: %CD%\.devcheck\test_report.json"
        )
        if exist ".devcheck\test_report.html" (
            call :print_info "HTML report: %CD%\.devcheck\test_report.html"
        )
        exit /b 0
    ) else (
        echo.
        call :print_error "DevCheck failed! Check the output above for details."
        
        REM Show report location even on failure
        if exist ".devcheck\test_report.json" (
            call :print_info "Check the detailed report: %CD%\.devcheck\test_report.json"
        )
        exit /b 1
    )

endlocal