REM Make test environment

@echo off
setlocal enabledelayedexpansion

set "TMPDIR=C:\tmp\qt-test"

if not exist "%TMPDIR%" (
    mkdir "%TMPDIR%"
    echo Created %TMPDIR%
) else (
    echo %TMPDIR% already exists
)

REM Source folders
set "PMIR_SRC=C:\Users\steve\S\TELOS\PMIR_StudyNote\working-blog"
set "CMM_SRC=C:\Users\steve\S\TELOS\CapitalModeling\TMA1"

REM Destinations under tmp
set "PMIR_DST=%TMPDIR%\pmir-test"
set "CMM_DST=%TMPDIR%\cmm-test"

REM -------------------------------------------------------------
REM Define (SRC, DST) pairs here
REM -------------------------------------------------------------
set PAIRS=^
    "%PMIR_SRC% %PMIR_DST%" ^
    "%CMM_SRC% %CMM_DST%"

REM -------------------------------------------------------------
REM Loop over each pair
REM -------------------------------------------------------------
for %%P in (%PAIRS%) do (
    for /f "tokens=1,2" %%A in (%%P) do (
        set "SRC=%%A"
        set "DST=%%B"

        echo.
        echo =====================================================
        echo Copying from !SRC!   to   !DST!
        echo =====================================================

        if not exist "!SRC!" (
            echo Source does not exist: !SRC!
            echo Skipping...
            echo.
        ) else (
            REM Recreate destination
            if exist "!DST!" rmdir /s /q "!DST!"
            mkdir "!DST!"

            REM 1. Copy selected file extensions
            robocopy "!SRC!" "!DST!" ^
                *.yaml *.yml *.qmd *.bib *.csl *.tex *.py *.css *.bat ^
                /s /r:1 /w:1 ^
                /xd .quarto .jupyter_cache .pytest_cache __pycache__ _freeze .ipynb_checkpoints

            REM 2. Copy static/ if present
            if exist "!SRC!\static" (
                robocopy "!SRC!\static" "!DST!\static" /e /r:1 /w:1
            )

            REM 3. Copy img/ if present
            if exist "!SRC!\img" (
                robocopy "!SRC!\img" "!DST!\img" /e /r:1 /w:1
            )

            echo Done copying !DST!.
            echo.
        )
    )
)

echo =====================================================
echo Copying some individual files
echo =====================================================
copy C:\S\TELOS\Blog\quarto\ConvexConsiderations\posts\notes\2025-11-15-The-Periodic-Table-Again\index.qmd elements.qmd
copy C:\Users\steve\S\TELOS\Blog\quarto\ConvexConsiderations\posts\notes\2025-02-06-Tweedie-distributions\index.qmd fft.qmd

echo Done.
endlocal
