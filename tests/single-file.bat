@echo off

echo Test from a Single File

setlocal

pushd \tmp

REM /c for prod and /k for debug
set "CFLAG=/k"

REM all levels
start "FFTs" cmd %CFLAG% "qt toc C:\Users\steve\S\TELOS\Blog\quarto\ConvexConsiderations\posts\notes\2025-01-23-Fourier-inversion-with-FFTs\index.qmd ffts.tex -c 7 -m 2cm -w 6cm -h 10.5cm --no-debug --omit Bibliography && lualatex -interaction=batchmode ffts.tex && ffts.pdf"


popd \tmp
