.PHONY: all programs census-programs check check-python check-programs \
	check-differential check-shards check-census check-certificate paper clean

PAPER_ENV = SOURCE_DATE_EPOCH=1784937600 FORCE_SOURCE_DATE=1

all: programs census-programs paper

programs:
	scripts/build.sh

census-programs:
	scripts/build_census.sh

check-python:
	python3 -m unittest -v tests.test_aggregate tests.test_aggregate_census \
		tests.test_analyze_witness_archive
	python3 tests/reference_gpc.py 7

check-programs: programs
	python3 tests/check_programs.py build/gpc build/majority_census

check-differential: programs
	bash tests/check_differential.sh build/genposetg \
		build/gpc_classifier_driver build/reference_gpc

check-shards: programs
	tests/check_shards.sh

check-census: census-programs
	bash tests/check_census.sh

check-certificate:
	python3 scripts/gpc_certificate.py --self-test 8

check: check-python check-programs check-differential check-shards \
	check-census check-certificate

paper:
	cd paper && $(PAPER_ENV) pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && $(PAPER_ENV) pdflatex -interaction=nonstopmode -halt-on-error main.tex

clean:
	rm -rf build scripts/__pycache__ tests/__pycache__
	rm -f paper/main.aux paper/main.log paper/main.out
