@echo off


setlocal

pushd \tmp\bib

echo Bibtex test for PMIR
qt bibtex \s\TELOS\PMIR_StudyNote\working-blog -b pmir.bib -d pmir.csv


echo ------------------------------------------------------------------------------------
echo Bibtex test for CMM
qt bibtex C:\Users\steve\S\TELOS\CapitalModeling\TMA1 -b cmm.bib -d cmm.csv


echo ------------------------------------------------------------------------------------
echo Bibtex test for CMM
qt bibtex C:\Users\steve\S\TELOS\CMM_CAS\source -b C:\Users\steve\S\TELOS\CMM_CAS\source\cmm.bib

popd \tmp
