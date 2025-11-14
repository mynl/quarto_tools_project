@echo off

echo Test from a Glob Pattern File

setlocal

pushd \tmp

REM /c for prod and /k for debug
set "CFLAG=/c"

REM reading in 2024 with VSIs;
start "Reading" cmd %CFLAG% "qt toc C:\Users\steve\S\TELOS\Blog\quarto\ConvexConsiderations\posts\about\2024-02-18-Reading-in-2024 reading.tex -c 10 -m 2cm -w 5cm -h 9cm -g *.qmd -v 3  && lualatex -interaction=batchmode reading.tex && reading.pdf"

REM trees
start "Trees" cmd %CFLAG% "qt toc C:\Users\steve\S\TELOS\Blog\quarto\ConvexConsiderations\posts\notes\2024-10-18-Classifying-and-Identifying-Trees trees.tex -c 7 -m 2cm -w 6cm -h 5cm --no-debug --omit Bibliography -v 3 -g *.qmd && lualatex -interaction=batchmode trees.tex && trees.pdf"

REM Tweedie extravaganza - single file glob
start "Tweedie" cmd %CFLAG% "qt toc C:\Users\steve\S\TELOS\Blog\quarto\ConvexConsiderations\posts\notes\2025-02-06-Tweedie-distributions tweedie.tex -c 3 -m 2cm -w 6cm -h 5cm --no-debug --omit Bibliography -v 3 -g index.qmd && lualatex -interaction=batchmode tweedie.tex && tweedie.pdf"


popd \tmp
