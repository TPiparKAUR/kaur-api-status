.PHONY: install download download-all download-single list help clean test lint

help:
	@echo "Keskkonnaagentuuri andmelaadimine - saadaolevad käsud"
	@echo ""
	@echo "  make install          - Sõltuvuste paigaldamine"
	@echo "  make download         - Kõigi andmeallikate allalaadimine"
	@echo "  make download-kese    - KESE andmete allalaadimine"
	@echo "  make list             - Saadaolevate andmeallikate loend"
	@echo "  make lint             - Koodikontroll (ruff + mypy)"
	@echo "  make test             - Testide käivitamine"
	@echo "  make clean            - Puhastamine"

install:
	pip install -r requirements.txt

download:
	python main.py download

download-single:
	@read -p "Andmeallikas: " source; \
	python main.py download --source $$source

list:
	python main.py list-sources

lint:
	ruff check src/ main.py || true
	mypy src/ main.py || true

test:
	pytest tests/ -v || true

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info 2>/dev/null || true
