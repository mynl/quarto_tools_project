set local

qt toc . toc/README.tex -f README.md && ^
pushd toc && ^
lualatex -interaction=batchmode README.tex && ^
README.pdf && ^
popd
