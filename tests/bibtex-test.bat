@echo off


setlocal

pushd \tmp\qt-test

echo Bibtex test for PMIR
rem qt bibtex \s\TELOS\PMIR_StudyNote\working-blog -b pmir.bib -d pmir.csv
qt bibtex pmir-test -w -o TEST-PREFIX


echo ------------------------------------------------------------------------------------
echo Bibtex test for CMM
qt bibtex cmm-test -w
rem qt bibtex C:\Users\steve\S\TELOS\CapitalModeling\TMA1 -b cmm.bib -d cmm.csv


bibtex C:/Users/steve/S/TELOS/CapitalModeling/TMA1 -b cmm.bib -d cmm.csv

popd
