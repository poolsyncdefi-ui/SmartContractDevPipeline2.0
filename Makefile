# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Makefile
# ==============================================================================

.PHONY: all install build test slither halmos pipeline deploy clean

all: clean install build test

install:
	pip install -r requirements.txt
	forge install

build:
	forge build

test:
	forge test -vv

slither:
	python scripts/run_slither.py

halmos:
	python scripts/run_halmos.py

pipeline:
	python scripts/run_pipeline.py

deploy-local:
	python scripts/deploy.py

clean:
	forge clean
	if exist slither-report.json del slither-report.json