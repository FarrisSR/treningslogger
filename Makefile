SHELL := /bin/bash

.PHONY: test prod

test:
	./scripts/deploy.sh test

prod: test
	./scripts/deploy.sh prod
