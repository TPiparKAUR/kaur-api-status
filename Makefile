.PHONY: help check report list validate test lint clean

help:
	@echo "Keskkonnaagentuuri API-de seire"
	@echo
	@echo "  make check      - kontrolli kõiki otspunkte, uuenda logi ja raport"
	@echo "  make report     - koosta REPORT.md olemasolevast logist"
	@echo "  make list       - näita inventari"
	@echo "  make validate   - kontrolli inventari süntaksit"
	@echo "  make test       - käivita testid"
	@echo "  make lint       - ruff + mypy (kui paigaldatud)"
	@echo "  make clean      - kustuta vahefailid"
	@echo
	@echo "Alustamiseks: python monitor.py import-urls urls.txt && make check"

check:
	python3 monitor.py check

report:
	python3 monitor.py report

list:
	python3 monitor.py list

validate:
	python3 monitor.py validate

test:
	python3 -m unittest discover -s tests -v

lint:
	@command -v ruff >/dev/null && ruff check src tests scripts || echo "ruff pole paigaldatud, jäetakse vahele"
	@command -v mypy >/dev/null && mypy src || echo "mypy pole paigaldatud, jäetakse vahele"

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .ruff_cache .mypy_cache
