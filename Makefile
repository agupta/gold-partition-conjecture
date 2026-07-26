.PHONY: all programs check check-python check-programs check-differential \
	check-shards paper clean

PAPER_ENV = SOURCE_DATE_EPOCH=1784937600 FORCE_SOURCE_DATE=1

all: programs paper

programs:
	scripts/build.sh

check-python:
	python3 -m unittest -v tests.test_aggregate
	python3 tests/reference_gpc.py 7

check-programs: programs
	python3 tests/check_programs.py build/gpc build/majority_census

check-differential: programs
	bash tests/check_differential.sh build/genposetg \
		build/gpc_classifier_driver build/reference_gpc

check-shards: programs
	tests/check_shards.sh

check: check-python check-programs check-differential check-shards

paper:
	cd paper && $(PAPER_ENV) pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && $(PAPER_ENV) pdflatex -interaction=nonstopmode -halt-on-error main.tex

clean:
	rm -rf build scripts/__pycache__ tests/__pycache__
	rm -f paper/main.aux paper/main.log paper/main.out
