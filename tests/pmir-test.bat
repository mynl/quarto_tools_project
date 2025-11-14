@echo off

echo Test from Project YAML files using PMIR

setlocal

pushd \tmp

REM /c for prod and /k for debug
set "CFLAG=/c"

REM all levels
start "PMIR All" cmd %CFLAG% "qt toc \s\TELOS\PMIR_StudyNote\working-blog pmir-all.tex -c 7 -m 2cm -w 6cm -h 10.5cm --no-debug --omit Bibliography && lualatex -interaction=batchmode pmir-all.tex && pmir-all.pdf"

REM three levels (no () within bullet sep list)
start "PMIR three" cmd %CFLAG% "qt toc \s\TELOS\PMIR_StudyNote\working-blog pmir-3.tex -c 7 -m 2cm -w 6cm -h 10.5cm --no-debug --omit Bibliography -v 3 && lualatex -interaction=batchmode pmir-3.tex && pmir-3.pdf"

REM Two levels
start "PMIR two" cmd %CFLAG%  "qt toc \s\TELOS\PMIR_StudyNote\working-blog pmir-2.tex -c 4 -m 3cm -w 8cm -h 8cm --no-debug -v 2 && lualatex -interaction=batchmode pmir-2.tex && pmir-2.pdf"

REM chapters only levels = 1
start "PMIR 1" cmd %CFLAG%  "qt toc \s\TELOS\PMIR_StudyNote\working-blog pmir-1.tex -c 4 -m 2cm -w 6cm -h 12cm --no-debug -v 1  && lualatex -interaction=batchmode pmir-1.tex && pmir-1.pdf"

REM chapter 2 only option -p
start "PMIR three" cmd %CFLAG% "qt toc \s\TELOS\PMIR_StudyNote\working-blog pmir-ch2.tex -c 3 -m 2cm -w 10cm -h 6cm --no-debug --omit Bibliography --promote-chapter 2 && lualatex -interaction=batchmode pmir-ch2.tex && pmir-ch2.pdf"

REM chapter 3 only option -p
start "PMIR three" cmd %CFLAG% "qt toc \s\TELOS\PMIR_StudyNote\working-blog pmir-ch3.tex -c 7 -m 2cm -w 6cm -h 10.5cm --no-debug --omit Bibliography --promote-chapter 3 && lualatex -interaction=batchmode pmir-ch3.tex && pmir-ch3.pdf"


popd \tmp
